"""5-slide deck PDF parser.

Extracts text per slide so the cross-check verifier can compare the deck's
claims with repo / live-URL evidence.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class DeckParse:
    path: str
    slides: list[str] = field(default_factory=list)
    available: bool = False
    error: str | None = None

    @property
    def joined(self) -> str:
        return "\n\n".join(f"-- Slide {i + 1} --\n{s}" for i, s in enumerate(self.slides))


def parse_deck(path: str | None) -> DeckParse:
    if not path:
        return DeckParse(path="", available=False, error="no deck provided")
    p = Path(path)
    if not p.exists():
        return DeckParse(path=str(p), available=False, error="file not found")
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(p))
        slides: list[str] = []
        for page in reader.pages[:12]:
            text = (page.extract_text() or "").strip()
            slides.append(text)
        return DeckParse(path=str(p), slides=slides, available=True)
    except Exception as exc:
        logger.warning("Deck parse failed for %s: %s", path, exc)
        return DeckParse(path=str(p), available=False, error=str(exc))
