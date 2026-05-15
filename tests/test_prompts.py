from __future__ import annotations

from app.llm.prompts import SYSTEM_PROMPT


def test_evaluation_prompt_requires_evidence_in_filter_language() -> None:
    assert "same language as that filter" in SYSTEM_PROMPT
    assert "competitief salaris" in SYSTEM_PROMPT
    assert "competitive salary" in SYSTEM_PROMPT
