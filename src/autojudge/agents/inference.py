"""Inference Agent.

Synthesises a structured `InferredSubmission` from whatever artifacts the
candidate provided. Two execution paths:

- Tool-calling loop (provider=anthropic): the agent calls `list_repo_tree`,
  `read_repo_file`, `read_deck`, `read_video_transcript`, `read_live_page`,
  `read_free_text` to selectively read what it needs, then emits the final
  payload through `record_inference`.

- Single-shot fallback (any other provider): tool calls are not available,
  so all artifact previews are inlined into the user message and the agent
  returns a JSON object in one round-trip.

In both paths the output is the same `InferredSubmission` Pydantic model.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..llm import LLMResponse, PromptPart, get_llm, supports_tool_calling
from ..models import (
    BuildLogEntry,
    CandidateInfo,
    InferredAIComponent,
    InferredClaim,
    InferredField,
    InferredJourney,
    InferredSubmission,
    Provenance,
)
from .inference_tools import (
    ANTHROPIC_TOOL_SPECS,
    ArtifactBundle,
    dispatch_tool,
    read_deck,
    read_free_text,
    read_live_page,
    read_repo_file,
    read_video_transcript,
)

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS = 8


def _load_prompt() -> str:
    return (Path(__file__).resolve().parents[3] / "prompts" / "inference.md").read_text(
        encoding="utf-8"
    )


def run_inference(bundle: ArtifactBundle) -> tuple[InferredSubmission, list[LLMResponse]]:
    """Entry point. Picks tool-calling vs single-shot based on provider."""
    settings = get_settings()
    if supports_tool_calling(settings.autojudge_primary_provider):
        return _run_tool_loop(bundle)
    return _run_single_shot(bundle)


# ---------------------------------------------------------------------------
# Tool-calling loop (Anthropic)
# ---------------------------------------------------------------------------


def _run_tool_loop(bundle: ArtifactBundle) -> tuple[InferredSubmission, list[LLMResponse]]:
    llm = get_llm()
    system_parts = [
        PromptPart(text=_load_prompt(), cacheable=True),
        PromptPart(text=_render_artifact_manifest(bundle), cacheable=False),
    ]
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": (
                "Begin synthesis. Use tool calls to read what you need and "
                "then emit the final payload via record_inference. "
                "Do NOT produce a text-only summary; the only valid completion "
                "is a record_inference tool call."
            ),
        }
    ]
    calls: list[LLMResponse] = []
    payload: dict[str, Any] | None = None
    tool_calls_made = 0
    artifacts_seen: list[str] = []
    nudge_used = False

    for _ in range(MAX_TOOL_CALLS):
        resp = llm.complete_tools(
            system=system_parts,
            messages=messages,
            tools=ANTHROPIC_TOOL_SPECS,
            tier="reasoning",
            max_tokens=4096,
        )
        calls.append(resp)

        if not resp.tool_calls:
            parsed = _extract_json_from_text(resp.text)
            if parsed is not None:
                payload = parsed
                break
            if not nudge_used:
                nudge_used = True
                if resp.text:
                    messages.append({"role": "assistant", "content": [{"type": "text", "text": resp.text}]})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "You did not call record_inference. Text-only output "
                            "is not a valid completion. Emit the final payload now "
                            "by calling the record_inference tool with the full "
                            "schema. Do not output JSON in text — use the tool."
                        ),
                    }
                )
                continue
            break

        assistant_blocks: list[dict[str, Any]] = []
        if resp.text:
            assistant_blocks.append({"type": "text", "text": resp.text})
        for call in resp.tool_calls:
            assistant_blocks.append(
                {
                    "type": "tool_use",
                    "id": call["id"],
                    "name": call["name"],
                    "input": call["input"] or {},
                }
            )
        messages.append({"role": "assistant", "content": assistant_blocks})

        tool_results: list[dict[str, Any]] = []
        terminate = False
        for call in resp.tool_calls:
            if call["name"] == "record_inference":
                raw_input = call["input"] or {}
                # Accept either {"payload": {...}} or {...fields...} directly.
                # Haiku in particular sometimes flattens the nested schema.
                if isinstance(raw_input, dict) and isinstance(raw_input.get("payload"), dict):
                    payload = raw_input["payload"]
                elif isinstance(raw_input, dict) and _looks_like_inferred_schema(raw_input):
                    payload = raw_input
                else:
                    payload = None
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call["id"],
                        "content": "ok",
                    }
                )
                terminate = True
                continue
            tool_calls_made += 1
            artifacts_seen.append(call["name"])
            result = dispatch_tool(bundle, call["name"], call["input"] or {})
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call["id"],
                    "content": result[:32_000],
                }
            )
        messages.append({"role": "user", "content": tool_results})
        if terminate:
            break

    if payload is None:
        logger.warning(
            "Inference agent did not produce a payload (nudge_used=%s); degrading to empty.",
            nudge_used,
        )
        inferred = InferredSubmission(
            gaps=["Inference Agent produced no payload — judges should review raw artifacts."],
            tool_calls_made=tool_calls_made,
            artifacts_seen=sorted(set(artifacts_seen)),
        )
        return inferred, calls

    inferred = _coerce_inferred(payload)
    inferred.tool_calls_made = tool_calls_made
    inferred.artifacts_seen = sorted(set(artifacts_seen))
    return inferred, calls


_INFERRED_KEYS = {
    "candidate_identity",
    "problem_statement",
    "tech_stack",
    "known_limitations",
    "build_log",
    "acknowledgements",
    "claims",
    "user_journeys",
    "ai_components",
    "gaps",
    "summary_for_scorer",
}


def _looks_like_inferred_schema(d: dict[str, Any]) -> bool:
    """True when the dict has enough InferredSubmission fields at the top level
    to be the flattened-payload variant a model sometimes emits.
    """
    return len(_INFERRED_KEYS.intersection(d.keys())) >= 3


def _extract_json_from_text(text: str | None) -> dict[str, Any] | None:
    """Best-effort JSON recovery from a model's free-text response.

    Handles: bare JSON, ```json ... ``` fences, ``` ... ``` fences, and a leading
    prose preamble followed by an object. Returns None if no valid object found.
    """
    if not text:
        return None
    candidate = text.strip()
    # Strip a leading code fence if present.
    if candidate.startswith("```"):
        # Drop the opening fence line.
        candidate = candidate.split("\n", 1)[-1] if "\n" in candidate else ""
        # Drop a trailing fence.
        if "```" in candidate:
            candidate = candidate.rsplit("```", 1)[0]
        candidate = candidate.strip()
    # Direct parse.
    try:
        obj = json.loads(candidate)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    # Last-ditch: grab the first {...} block.
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end > start:
        try:
            obj = json.loads(candidate[start : end + 1])
            if isinstance(obj, dict):
                return obj
        except Exception:
            return None
    return None


def _render_artifact_manifest(bundle: ArtifactBundle) -> str:
    return (
        "### Available artifacts for this submission\n"
        f"- GitHub repo: {bundle.repo_url or '(none)'}\n"
        f"- Live URL: {bundle.live_url or '(none)'}\n"
        f"- Demo video: {bundle.video_url or '(none)'}\n"
        f"- Slide deck: {'attached' if bundle.deck_path else '(none)'}\n"
        f"- Free-form context length: {len(bundle.free_text)} chars\n"
    )


# ---------------------------------------------------------------------------
# Single-shot fallback (Groq, Gemini, OpenRouter)
# ---------------------------------------------------------------------------


def _run_single_shot(bundle: ArtifactBundle) -> tuple[InferredSubmission, list[LLMResponse]]:
    llm = get_llm()
    system_parts = [PromptPart(text=_load_prompt(), cacheable=False)]

    sections: list[str] = [_render_artifact_manifest(bundle)]

    free_text = read_free_text(bundle)
    sections.append(f"### Free-form context\n{free_text}")

    if bundle.repo_url:
        try:
            from ..intake import github as gh

            readme_paths = gh.find_files_by_pattern(
                bundle.repo_url, ["README*", "readme*"], max_results=3
            )
            entry_paths = gh.find_files_by_pattern(
                bundle.repo_url,
                ["main.py", "app.py", "index.ts", "index.tsx", "server.py", "agent.py"],
                max_results=3,
            )
            paths = list(dict.fromkeys(readme_paths + entry_paths))
            files = gh.fetch_files(bundle.repo_url, paths, max_bytes=12_000) if paths else {}
            sections.append(
                "### Repo previews\n"
                + (
                    "\n\n".join(f"-- {p} --\n{content[:6000]}" for p, content in files.items())
                    or "(no files retrieved)"
                )
            )
        except Exception as exc:
            sections.append(f"### Repo previews\n(failed: {exc})")

    if bundle.live_url:
        sections.append(f"### Live page probe\n{read_live_page(bundle)}")
    if bundle.video_url:
        sections.append(f"### Video transcript\n{read_video_transcript(bundle)[:6000]}")
    if bundle.deck_path:
        sections.append(f"### Deck text\n{read_deck(bundle)[:8000]}")

    user = "\n\n".join(sections)
    try:
        data, resp = llm.complete_json(
            system=system_parts, user=user, tier="reasoning", max_tokens=4096
        )
    except Exception as exc:
        logger.warning("Inference single-shot failed: %s", exc)
        return (
            InferredSubmission(
                gaps=[f"Inference single-shot LLM call failed: {exc}"],
            ),
            [],
        )

    inferred = _coerce_inferred(data)
    inferred.artifacts_seen = sorted(
        {
            kind
            for kind, present in [
                ("free_text", bool(bundle.free_text.strip())),
                ("repo", bool(bundle.repo_url)),
                ("live", bool(bundle.live_url)),
                ("video", bool(bundle.video_url)),
                ("deck", bool(bundle.deck_path)),
            ]
            if present
        }
    )
    return inferred, [resp]


# ---------------------------------------------------------------------------
# Coercion: raw JSON dict -> Pydantic InferredSubmission
# ---------------------------------------------------------------------------


def _provenance(raw: Any) -> Provenance:
    if not isinstance(raw, str):
        return "unknown"
    val = raw.lower()
    if val in ("stated", "inferred", "verified", "unknown"):
        return val  # type: ignore[return-value]
    return "unknown"


def _field_str(raw: Any) -> InferredField[str]:
    if not isinstance(raw, dict):
        return InferredField[str](value=str(raw) if raw else None)
    return InferredField[str](
        value=raw.get("value") if isinstance(raw.get("value"), str) else (
            str(raw.get("value")) if raw.get("value") is not None else None
        ),
        source=_provenance(raw.get("source")),
        provenance=str(raw.get("provenance", "")),
        confidence=float(raw.get("confidence", 0.0) or 0.0),
    )


def _field_str_list(raw: Any) -> InferredField[list[str]]:
    if not isinstance(raw, dict):
        items = raw if isinstance(raw, list) else []
        return InferredField[list[str]](value=[str(x) for x in items] or None)
    value = raw.get("value")
    if isinstance(value, list):
        coerced = [str(x) for x in value]
    else:
        coerced = None
    return InferredField[list[str]](
        value=coerced,
        source=_provenance(raw.get("source")),
        provenance=str(raw.get("provenance", "")),
        confidence=float(raw.get("confidence", 0.0) or 0.0),
    )


def _field_dict_str(raw: Any) -> InferredField[dict[str, str]]:
    if not isinstance(raw, dict):
        return InferredField[dict[str, str]]()
    value = raw.get("value")
    coerced: dict[str, str] | None
    if isinstance(value, dict):
        coerced = {str(k): str(v) for k, v in value.items() if v is not None}
    else:
        coerced = None
    return InferredField[dict[str, str]](
        value=coerced,
        source=_provenance(raw.get("source")),
        provenance=str(raw.get("provenance", "")),
        confidence=float(raw.get("confidence", 0.0) or 0.0),
    )


def _field_candidate(raw: Any) -> InferredField[CandidateInfo]:
    if not isinstance(raw, dict):
        return InferredField[CandidateInfo]()
    value = raw.get("value")
    coerced: CandidateInfo | None = None
    if isinstance(value, dict) and value.get("name"):
        coerced = CandidateInfo(
            name=str(value.get("name") or "unknown"),
            email=value.get("email"),
            team=value.get("team"),
        )
    return InferredField[CandidateInfo](
        value=coerced,
        source=_provenance(raw.get("source")),
        provenance=str(raw.get("provenance", "")),
        confidence=float(raw.get("confidence", 0.0) or 0.0),
    )


def _field_build_log(raw: Any) -> InferredField[list[BuildLogEntry]]:
    if not isinstance(raw, dict):
        return InferredField[list[BuildLogEntry]]()
    value = raw.get("value")
    coerced: list[BuildLogEntry] | None = None
    if isinstance(value, list):
        coerced = [
            BuildLogEntry(
                timestamp=str(item.get("timestamp")) if isinstance(item, dict) and item.get("timestamp") else None,
                task=str(item.get("task")) if isinstance(item, dict) and item.get("task") else None,
            )
            for item in value
            if isinstance(item, dict)
        ]
    return InferredField[list[BuildLogEntry]](
        value=coerced,
        source=_provenance(raw.get("source")),
        provenance=str(raw.get("provenance", "")),
        confidence=float(raw.get("confidence", 0.0) or 0.0),
    )


def _coerce_claims(raw: Any) -> list[InferredClaim]:
    if not isinstance(raw, list):
        return []
    out: list[InferredClaim] = []
    for i, c in enumerate(raw):
        if not isinstance(c, dict) or not c.get("text"):
            continue
        out.append(
            InferredClaim(
                id=str(c.get("id") or f"C{i + 1}"),
                text=str(c.get("text", "")),
                category=str(c.get("category", "feature")),
                testable=bool(c.get("testable", True)),
                expected_outcome=c.get("expected_outcome"),
                source=_provenance(c.get("source")),
                provenance=str(c.get("provenance", "")),
                confidence=float(c.get("confidence", 0.5) or 0.5),
            )
        )
    return out


def _coerce_journeys(raw: Any) -> list[InferredJourney]:
    if not isinstance(raw, list):
        return []
    out: list[InferredJourney] = []
    for i, j in enumerate(raw):
        if not isinstance(j, dict):
            continue
        steps_raw = j.get("steps") or []
        steps = [str(s) for s in steps_raw if s]
        if not steps:
            continue
        out.append(
            InferredJourney(
                name=str(j.get("name") or f"Journey {i + 1}"),
                steps=steps,
                expected_outcome=str(j.get("expected_outcome", "") or ""),
                sample_input=j.get("sample_input"),
                source=_provenance(j.get("source")),
                provenance=str(j.get("provenance", "")),
                confidence=float(j.get("confidence", 0.5) or 0.5),
            )
        )
    return out


def _coerce_ai_components(raw: Any) -> list[InferredAIComponent]:
    if not isinstance(raw, list):
        return []
    out: list[InferredAIComponent] = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        tools = item.get("tools") or []
        out.append(
            InferredAIComponent(
                name=str(item.get("name", "")),
                models=item.get("models"),
                description=item.get("description"),
                agentic_claim=item.get("agentic_claim"),
                tools=[str(t) for t in tools if t],
                evals=item.get("evals"),
                source=_provenance(item.get("source")),
                provenance=str(item.get("provenance", "")),
                confidence=float(item.get("confidence", 0.5) or 0.5),
            )
        )
    return out


def _coerce_inferred(data: dict[str, Any]) -> InferredSubmission:
    return InferredSubmission(
        candidate_identity=_field_candidate(data.get("candidate_identity")),
        problem_statement=_field_str(data.get("problem_statement")),
        tech_stack=_field_dict_str(data.get("tech_stack")),
        known_limitations=_field_str_list(data.get("known_limitations")),
        build_log=_field_build_log(data.get("build_log")),
        acknowledgements=_field_str_list(data.get("acknowledgements")),
        claims=_coerce_claims(data.get("claims")),
        user_journeys=_coerce_journeys(data.get("user_journeys")),
        ai_components=_coerce_ai_components(data.get("ai_components")),
        gaps=[str(g) for g in (data.get("gaps") or []) if g],
        summary_for_scorer=str(data.get("summary_for_scorer", "")),
    )
