"""Demo video transcript extraction.

We only need the *transcript* — the cross-check verifier compares what the
candidate claims in the video to repo / live-URL evidence. Costly multimodal
analysis is out of scope for v1.0.

Supported sources for v1.0:
- YouTube (via youtube-transcript-api)
- Anything else: explicit `unsupported` return, no scraping attempts.
  Loom support was best-effort and unreliable; it is deferred to v1.1.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class VideoTranscript:
    url: str
    source: str
    transcript: str
    available: bool
    error: str | None = None


def fetch_transcript(url: str | None) -> VideoTranscript:
    if not url:
        return VideoTranscript(url="", source="none", transcript="", available=False)
    url = url.strip()
    if "youtube.com" in url or "youtu.be" in url:
        return _youtube(url)
    if "loom.com" in url:
        return VideoTranscript(
            url=url,
            source="loom",
            transcript="",
            available=False,
            error="Loom transcripts not supported in v1.0; use YouTube instead.",
        )
    return VideoTranscript(
        url=url,
        source="unsupported",
        transcript="",
        available=False,
        error="unsupported video host (v1.0 supports YouTube only)",
    )


def _youtube_video_id(url: str) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/|/embed/)([\w\-]{6,})", url)
    return m.group(1) if m else None


def _youtube(url: str) -> VideoTranscript:
    vid = _youtube_video_id(url)
    if not vid:
        return VideoTranscript(
            url=url,
            source="youtube",
            transcript="",
            available=False,
            error="cannot parse video id",
        )
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        items = YouTubeTranscriptApi.get_transcript(vid)
        text = " ".join(i["text"] for i in items)
        return VideoTranscript(url=url, source="youtube", transcript=text[:10_000], available=True)
    except Exception as exc:
        logger.warning("YouTube transcript fetch failed for %s: %s", url, exc)
        return VideoTranscript(
            url=url, source="youtube", transcript="", available=False, error=str(exc)
        )
