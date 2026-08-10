import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from autojudge.agents.inference import _run_tool_loop
from autojudge.agents.inference_tools import ArtifactBundle
from autojudge.models import InferredSubmission


class _FakeLLM:
    def __init__(self, *, complete_json_result=None, complete_json_raises=None):
        self._complete_json_result = complete_json_result
        self._complete_json_raises = complete_json_raises

    def complete_tools(self, **kwargs):
        raise RuntimeError("model: claude-sonnet-4-20250514 not found")

    def complete_json(self, **kwargs):
        if self._complete_json_raises:
            raise self._complete_json_raises
        return self._complete_json_result, None


def test_tool_loop_falls_back_to_single_shot_on_total_outage():
    fake = _FakeLLM(complete_json_raises=RuntimeError("groq also down"))
    with patch("autojudge.agents.inference.get_llm", return_value=fake):
        inferred, calls = _run_tool_loop(ArtifactBundle())

    assert isinstance(inferred, InferredSubmission)
    assert any("Tool-calling reasoning path failed" in g for g in inferred.gaps)
    assert any("single-shot" in g.lower() for g in inferred.gaps)
    assert calls == []


def test_tool_loop_falls_back_to_single_shot_and_recovers_payload():
    payload = {
        "problem_statement": "x",
        "summary_for_scorer": "recovered via single-shot",
    }
    fake = _FakeLLM(complete_json_result=payload)
    with patch("autojudge.agents.inference.get_llm", return_value=fake):
        inferred, calls = _run_tool_loop(ArtifactBundle())

    assert isinstance(inferred, InferredSubmission)
    assert any("Tool-calling reasoning path failed" in g for g in inferred.gaps)
    assert inferred.summary_for_scorer == "recovered via single-shot"
