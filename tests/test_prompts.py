from __future__ import annotations

from app.llm.prompts import SYSTEM_PROMPT, build_dom_diagnostics_user_message


def test_evaluation_prompt_requires_evidence_in_filter_language() -> None:
    assert "same language as that filter" in SYSTEM_PROMPT
    assert "competitief salaris" in SYSTEM_PROMPT
    assert "competitive salary" in SYSTEM_PROMPT


def test_dom_diagnostics_message_separates_html_from_json() -> None:
    telemetry = {
        "extractor": "jobs-v1",
        "outcome": "partial",
        "missing": ["title"],
        "job_html": '<main><h1 class="_abc123">A Title</h1></main>',
    }
    message = build_dom_diagnostics_user_message(telemetry)
    # HTML is rendered as a real fenced block...
    assert "```html" in message
    assert "_abc123" in message
    # ...and NOT duplicated inside the telemetry JSON block.
    json_block = message.split("```json", 1)[1].split("```", 1)[0]
    assert "job_html" not in json_block


def test_dom_diagnostics_message_notes_absent_html() -> None:
    telemetry = {"extractor": "jobs-v1", "outcome": "failed", "missing": ["description"]}
    message = build_dom_diagnostics_user_message(telemetry)
    assert "No HTML snapshot was available" in message
    assert "```html" not in message
