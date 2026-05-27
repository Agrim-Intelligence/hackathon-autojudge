"""Unified LLM client across Groq, Gemini, OpenRouter, and Anthropic.

Groq, Gemini, and OpenRouter expose OpenAI-compatible chat completions
(openai SDK + base_url). Anthropic uses its native Messages API
(anthropic SDK), which is required for `cache_control: ephemeral` blocks
and the tools API used by the Inference Agent.

Provider routing is purely .env-driven via `AUTOJUDGE_PRIMARY_PROVIDER`
and `AUTOJUDGE_FALLBACK_PROVIDER`. There is no run-mode abstraction.
Capability flags (caching, tool calling) activate per-provider.

Tiers:
- reasoning : strong model used by verifiers and the rubric scorer
- extraction: cheap fast model used for sanitization and field extraction
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import Provider, get_settings

logger = logging.getLogger(__name__)

Tier = Literal["reasoning", "extraction"]

PROVIDER_BASE_URLS: dict[Provider, str] = {
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "openrouter": "https://openrouter.ai/api/v1",
}

# Per-provider input/output budgets in characters. Groq free tier has the
# tightest body-size limit; Anthropic and the others can take much more.
PROVIDER_LIMITS: dict[Provider, dict[str, int]] = {
    "groq": {"max_user_chars": 24_000, "max_system_chars": 8_000},
    "gemini": {"max_user_chars": 60_000, "max_system_chars": 20_000},
    "openrouter": {"max_user_chars": 60_000, "max_system_chars": 20_000},
    "anthropic": {"max_user_chars": 120_000, "max_system_chars": 40_000},
}

# (input $/M tok, output $/M tok). Used as heuristic when the provider does
# not surface usage; used as the precise base for Anthropic with cache_create
# costed at 1.25x input and cache_read at 0.10x input.
PROVIDER_RATES: dict[Provider, dict[str, tuple[float, float]]] = {
    "groq": {
        "default": (0.0, 0.0),
    },
    "gemini": {
        "gemini-2.5-pro": (1.25, 10.0),
        "gemini-2.5-flash": (0.30, 2.50),
        "gemini-3.0-pro": (2.0, 12.0),
        "gemini-3.0-flash": (0.40, 3.0),
        "default": (1.25, 10.0),
    },
    "openrouter": {
        "claude-sonnet": (3.0, 15.0),
        "claude-haiku": (0.80, 4.0),
        "gpt-4o-mini": (0.15, 0.60),
        "gpt-4o": (2.5, 10.0),
        "default": (3.0, 15.0),
    },
    "anthropic": {
        "claude-sonnet": (3.0, 15.0),
        "claude-haiku": (0.80, 4.0),
        "claude-opus": (15.0, 75.0),
        "default": (3.0, 15.0),
    },
}

# Anthropic cache pricing multipliers per the ephemeral cache spec.
ANTHROPIC_CACHE_WRITE_MULTIPLIER = 1.25
ANTHROPIC_CACHE_READ_MULTIPLIER = 0.10


@dataclass
class PromptPart:
    """A chunk of system prompt with an advisory caching flag.

    When the active provider is Anthropic, parts with `cacheable=True` are
    marked with `cache_control: ephemeral` so the prefix is cached server-side
    and reused at 10% input cost on subsequent calls within the 5-minute TTL.

    Other providers ignore the flag and concatenate the parts into one string.
    """

    text: str
    cacheable: bool = False


SystemPrompt = str | PromptPart | list[PromptPart]


def _normalize_system(system: SystemPrompt) -> list[PromptPart]:
    if isinstance(system, str):
        return [PromptPart(text=system, cacheable=False)]
    if isinstance(system, PromptPart):
        return [system]
    return list(system)


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: Provider
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    # True when token usage was reported by the API (and therefore cost is
    # precise). False when we are estimating from a heuristic rate table.
    usage_reported: bool = False
    # Anthropic tool-call response objects exposed verbatim for the inference
    # agent to dispatch. Empty for plain text completions.
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str | None = None

    @property
    def estimated_cost_usd(self) -> float:
        in_rate, out_rate = _pick_rate(self.provider, self.model)
        if self.provider == "anthropic":
            base = self.input_tokens * in_rate
            cache_write = self.cache_creation_input_tokens * in_rate * ANTHROPIC_CACHE_WRITE_MULTIPLIER
            cache_read = self.cache_read_input_tokens * in_rate * ANTHROPIC_CACHE_READ_MULTIPLIER
            out = self.output_tokens * out_rate
            return (base + cache_write + cache_read + out) / 1_000_000
        return (self.input_tokens * in_rate + self.output_tokens * out_rate) / 1_000_000

    @property
    def cost_is_precise(self) -> bool:
        return self.provider == "anthropic" and self.usage_reported


def _pick_rate(provider: Provider, model: str) -> tuple[float, float]:
    rates = PROVIDER_RATES[provider]
    for key, value in rates.items():
        if key != "default" and key in model:
            return value
    return rates["default"]


def supports_prompt_caching(provider: Provider) -> bool:
    return provider == "anthropic"


def supports_tool_calling(provider: Provider) -> bool:
    return provider == "anthropic"


class LLMClient:
    """Provider-agnostic client.

    Public API:
    - `complete()` — single completion, returns text + token usage.
    - `complete_json()` — wraps `complete()` and parses a JSON object.
    - `complete_tools()` — Anthropic native tool-calling turn (Anthropic only).
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self._clients: dict[Provider, Any] = {}
        self._anthropic_client: Any | None = None

    # --- client construction -------------------------------------------------

    def _client_for(self, provider: Provider):
        if provider == "anthropic":
            return self._anthropic_client_for()

        if provider in self._clients:
            return self._clients[provider]

        from openai import OpenAI

        api_key = self.settings.api_key_for(provider)
        if not api_key:
            raise RuntimeError(f"API key for provider '{provider}' not set in environment")

        kwargs: dict[str, Any] = {"api_key": api_key, "base_url": PROVIDER_BASE_URLS[provider]}
        if provider == "openrouter":
            kwargs["default_headers"] = {
                "HTTP-Referer": self.settings.autojudge_openrouter_referer,
                "X-Title": self.settings.autojudge_openrouter_title,
            }

        client = OpenAI(**kwargs)
        self._clients[provider] = client
        return client

    def _anthropic_client_for(self):
        if self._anthropic_client is not None:
            return self._anthropic_client

        from anthropic import Anthropic

        api_key = self.settings.api_key_for("anthropic")
        if not api_key:
            raise RuntimeError("API key for provider 'anthropic' not set in environment")

        self._anthropic_client = Anthropic(api_key=api_key)
        return self._anthropic_client

    # --- helpers -------------------------------------------------------------

    def _truncate(self, provider: Provider, system: str, user: str) -> tuple[str, str]:
        limits = PROVIDER_LIMITS[provider]
        max_sys = limits["max_system_chars"]
        max_usr = limits["max_user_chars"]
        if len(system) > max_sys:
            system = system[:max_sys] + "\n...[system truncated]"
        if len(user) > max_usr:
            user = user[:max_usr] + "\n...[user truncated to fit provider limits]"
        return system, user

    def _truncate_parts(
        self, provider: Provider, parts: list[PromptPart], user: str
    ) -> tuple[list[PromptPart], str]:
        # For caching to work, do not truncate cacheable parts (they must stay
        # bytewise stable across calls). Truncate only the non-cacheable tail
        # and the user message.
        limits = PROVIDER_LIMITS[provider]
        max_sys = limits["max_system_chars"]
        max_usr = limits["max_user_chars"]

        cacheable_chars = sum(len(p.text) for p in parts if p.cacheable)
        budget_for_dynamic = max(2_000, max_sys - cacheable_chars)

        out: list[PromptPart] = []
        dynamic_used = 0
        for p in parts:
            if p.cacheable:
                out.append(p)
                continue
            if dynamic_used + len(p.text) > budget_for_dynamic:
                remaining = budget_for_dynamic - dynamic_used
                if remaining > 200:
                    out.append(
                        PromptPart(
                            text=p.text[:remaining] + "\n...[dynamic system truncated]",
                            cacheable=False,
                        )
                    )
                dynamic_used = budget_for_dynamic
                break
            out.append(p)
            dynamic_used += len(p.text)

        if len(user) > max_usr:
            user = user[:max_usr] + "\n...[user truncated to fit provider limits]"
        return out, user

    # --- main entrypoint -----------------------------------------------------

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=8),
        reraise=True,
    )
    def complete(
        self,
        system: SystemPrompt,
        user: str,
        *,
        tier: Tier = "reasoning",
        provider: Provider | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> LLMResponse:
        primary = provider or self.settings.autojudge_primary_provider
        parts = _normalize_system(system)
        parts, user = self._truncate_parts(primary, parts, user)
        try:
            return self._call(primary, tier, parts, user, max_tokens, temperature)
        except Exception as exc:
            err = str(exc).lower()
            if "413" in err or "too large" in err or "request_too_large" in err:
                logger.warning("Payload too large for %s; retrying with halved context", primary)
                halved_user = user[: max(len(user) // 2, 4000)]
                halved_parts = self._halve_parts(parts)
                try:
                    return self._call(primary, tier, halved_parts, halved_user, max_tokens, temperature)
                except Exception:
                    pass
            fallback = self.settings.autojudge_fallback_provider
            if (
                not fallback
                or fallback == primary
                or not self.settings.api_key_for(fallback)
            ):
                raise
            logger.warning(
                "Primary provider %s failed (%s); falling back to %s",
                primary,
                exc,
                fallback,
            )
            f_parts, f_user = self._truncate_parts(fallback, parts, user)
            return self._call(fallback, tier, f_parts, f_user, max_tokens, temperature)

    def _halve_parts(self, parts: list[PromptPart]) -> list[PromptPart]:
        out: list[PromptPart] = []
        for p in parts:
            if p.cacheable:
                out.append(p)
            else:
                out.append(PromptPart(text=p.text[: max(len(p.text) // 2, 1500)], cacheable=False))
        return out

    def _call(
        self,
        provider: Provider,
        tier: Tier,
        parts: list[PromptPart],
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        model = self.settings.model_for(provider, tier)
        if provider == "anthropic":
            return self._call_anthropic(model, parts, user, max_tokens, temperature)

        client = self._client_for(provider)
        system_text = "\n\n".join(p.text for p in parts)
        resp = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_text},
                {"role": "user", "content": user},
            ],
        )
        text = resp.choices[0].message.content or ""
        usage = resp.usage
        in_tok = getattr(usage, "prompt_tokens", 0) if usage else 0
        out_tok = getattr(usage, "completion_tokens", 0) if usage else 0
        return LLMResponse(
            text=text,
            model=model,
            provider=provider,
            input_tokens=in_tok,
            output_tokens=out_tok,
            usage_reported=bool(usage),
        )

    def _call_anthropic(
        self,
        model: str,
        parts: list[PromptPart],
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        client = self._anthropic_client_for()
        system_blocks = _to_anthropic_system(parts)
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_blocks,
            messages=[{"role": "user", "content": user}],
        )
        text = ""
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                text += block.text
        usage = resp.usage
        return LLMResponse(
            text=text,
            model=model,
            provider="anthropic",
            input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
            cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            usage_reported=bool(usage),
            stop_reason=getattr(resp, "stop_reason", None),
        )

    # --- JSON convenience ----------------------------------------------------

    def complete_json(
        self,
        system: SystemPrompt,
        user: str,
        *,
        tier: Tier = "reasoning",
        max_tokens: int = 2048,
    ) -> tuple[dict[str, Any], LLMResponse]:
        """Run a completion and parse a JSON object from the response."""
        instruction = (
            "\n\nRespond with a single JSON object. Do not wrap in markdown fences. "
            "Do not include any prose outside the JSON."
        )
        parts = _normalize_system(system)
        if parts:
            parts = list(parts)
            last = parts[-1]
            parts[-1] = PromptPart(text=last.text + instruction, cacheable=False)
        else:
            parts = [PromptPart(text=instruction, cacheable=False)]
        resp = self.complete(parts, user, tier=tier, max_tokens=max_tokens)
        return _extract_json(resp.text), resp

    # --- Tool calling (Anthropic only) ---------------------------------------

    def complete_tools(
        self,
        system: SystemPrompt,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        tier: Tier = "reasoning",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """One Anthropic tools turn. Caller manages the multi-turn loop.

        Returns an LLMResponse with `tool_calls` populated when the model
        emitted `tool_use` blocks, and `stop_reason` reflecting the API's
        termination signal. `text` contains any free-text the model emitted
        alongside the tool calls.
        """
        if self.settings.autojudge_primary_provider != "anthropic":
            raise RuntimeError(
                "complete_tools requires AUTOJUDGE_PRIMARY_PROVIDER=anthropic. "
                "For other providers, use complete_json with all artifacts inlined."
            )
        parts = _normalize_system(system)
        # Trim only dynamic parts; do not touch cacheable ones (must stay stable).
        parts, _ = self._truncate_parts("anthropic", parts, "")
        client = self._anthropic_client_for()
        model = self.settings.model_for("anthropic", tier)
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=_to_anthropic_system(parts),
            tools=tools,
            messages=messages,
        )
        text_chunks: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for block in resp.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_chunks.append(block.text)
            elif btype == "tool_use":
                tool_calls.append(
                    {
                        "id": block.id,
                        "name": block.name,
                        "input": getattr(block, "input", {}) or {},
                    }
                )
        usage = resp.usage
        return LLMResponse(
            text="".join(text_chunks),
            model=model,
            provider="anthropic",
            input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
            cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            usage_reported=bool(usage),
            tool_calls=tool_calls,
            stop_reason=getattr(resp, "stop_reason", None),
        )


def _to_anthropic_system(parts: list[PromptPart]) -> list[dict[str, Any]]:
    """Convert PromptParts into Anthropic system blocks.

    A `cache_control: ephemeral` marker is added to each cacheable part.
    Anthropic supports up to 4 cache breakpoints; we cap at the last 4
    cacheable parts to stay within that limit.
    """
    blocks: list[dict[str, Any]] = []
    cacheable_indices = [i for i, p in enumerate(parts) if p.cacheable]
    keep_cache = set(cacheable_indices[-4:])
    for i, p in enumerate(parts):
        block: dict[str, Any] = {"type": "text", "text": p.text}
        if p.cacheable and i in keep_cache:
            block["cache_control"] = {"type": "ephemeral"}
        blocks.append(block)
    return blocks


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


_client: LLMClient | None = None


def get_llm() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client


def reset_llm_for_tests() -> None:
    global _client
    _client = None
