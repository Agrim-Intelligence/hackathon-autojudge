"""Runtime configuration loaded from environment variables.

Single source of truth for provider keys, model names per provider, paths,
and the hackathon window used by integrity checks.

Supports four providers:
- groq      : free dev/testing tier (OpenAI-compatible)
- gemini    : paid prod (Google AI Studio OpenAI-compatible endpoint)
- openrouter: paid prod (multi-model routing, OpenAI-compatible)
- anthropic : paid prod (native Messages API)
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["groq", "gemini", "openrouter", "anthropic"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    groq_api_key: str | None = None
    gemini_api_key: str | None = None
    openrouter_api_key: str | None = None
    anthropic_api_key: str | None = None
    github_token: str | None = None

    autojudge_primary_provider: Provider = "gemini"
    autojudge_fallback_provider: Provider | None = "openrouter"

    autojudge_groq_reasoning_model: str = "llama-3.3-70b-versatile"
    autojudge_groq_extraction_model: str = "llama-3.1-8b-instant"
    autojudge_gemini_reasoning_model: str = "gemini-2.5-pro"
    autojudge_gemini_extraction_model: str = "gemini-2.5-flash"
    autojudge_openrouter_reasoning_model: str = "anthropic/claude-sonnet-4.5"
    autojudge_openrouter_extraction_model: str = "openai/gpt-4o-mini"
    autojudge_anthropic_reasoning_model: str = "claude-sonnet-4-20250514"
    autojudge_anthropic_extraction_model: str = "claude-haiku-4-5-20251001"

    autojudge_openrouter_referer: str = "https://agrim.ai"
    autojudge_openrouter_title: str = "Agrim AutoJudge"

    autojudge_hackathon_start: datetime = Field(
        default_factory=lambda: datetime(2026, 5, 22, tzinfo=timezone.utc)
    )
    autojudge_hackathon_end: datetime = Field(
        default_factory=lambda: datetime(2026, 5, 23, 23, 59, 59, tzinfo=timezone.utc)
    )

    autojudge_data_dir: Path = Path("./data")
    autojudge_db_path: Path = Path("./data/traces.db")

    database_url: str | None = None

    autojudge_browser_headless: bool = True
    autojudge_browser_timeout_s: int = 45
    autojudge_browser_max_steps: int = 12
    autojudge_browser_max_steps_spa: int = 20

    autojudge_submission_timeout_s: int = 900
    autojudge_snapshot_ttl_days: int = 14

    autojudge_dashboard_basic_auth_user: str | None = None
    autojudge_dashboard_basic_auth_pass: str | None = None
    autojudge_intake_basic_auth_user: str | None = None
    autojudge_intake_basic_auth_pass: str | None = None

    @field_validator("autojudge_fallback_provider", mode="before")
    @classmethod
    def blank_fallback_provider_is_none(cls, value: object) -> object:
        """Treat unset/blank env as no fallback (Railway often leaves ``=`` empty)."""
        if value == "":
            return None
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def blank_database_url_is_none(cls, value: object) -> object:
        """Empty string ``DATABASE_URL`` falls back to SQLite, same as missing."""
        if value == "":
            return None
        return value

    @property
    def submissions_dir(self) -> Path:
        return self.autojudge_data_dir / "submissions"

    def api_key_for(self, provider: Provider) -> str | None:
        return {
            "groq": self.groq_api_key,
            "gemini": self.gemini_api_key,
            "openrouter": self.openrouter_api_key,
            "anthropic": self.anthropic_api_key,
        }[provider]

    def model_for(self, provider: Provider, tier: Literal["reasoning", "extraction"]) -> str:
        mapping = {
            ("groq", "reasoning"): self.autojudge_groq_reasoning_model,
            ("groq", "extraction"): self.autojudge_groq_extraction_model,
            ("gemini", "reasoning"): self.autojudge_gemini_reasoning_model,
            ("gemini", "extraction"): self.autojudge_gemini_extraction_model,
            ("openrouter", "reasoning"): self.autojudge_openrouter_reasoning_model,
            ("openrouter", "extraction"): self.autojudge_openrouter_extraction_model,
            ("anthropic", "reasoning"): self.autojudge_anthropic_reasoning_model,
            ("anthropic", "extraction"): self.autojudge_anthropic_extraction_model,
        }
        return mapping[(provider, tier)]

    def ensure_dirs(self) -> None:
        self.autojudge_data_dir.mkdir(parents=True, exist_ok=True)
        self.submissions_dir.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.ensure_dirs()
    return _settings
