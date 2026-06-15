"""Schemas for DOM-extraction diagnostics (Measure 3).

When the extension's LinkedIn scraper fails or comes back partial, it POSTs
diagnostics here. The backend runs a diagnostic LLM analysis and logs both to
`llm_calls` so we can triage breakage in /admin without asking the user to run
console scripts.

PRIVACY — "capture the job, exclude the user": the payload is telemetry (which
selectors matched/missed, extractor version, URL, page <title>) plus `job_html`,
a sanitized snapshot of the JOB POSTING subtree — structure + job text, with the
member's identity, the global chrome (nav/feed/messaging) and all media
excluded/redacted on the client (see the extension's lib/linkedin/snapshot).
Job-posting content is public listing data already sent to the LLM during normal
evaluation; the member's personal identity is excluded. That keeps diagnostics
silent + privacy-policy-disclosed rather than opt-in. Do not widen `job_html` to
include the global chrome without revisiting the consent model.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ExtractionOutcome = Literal["ok", "partial", "failed"]


class DomFieldReport(BaseModel):
    name: str = Field(..., max_length=32)
    found: bool
    # The strategy that produced the value (a selector string, "doc-title",
    # "anchor", …) or null when nothing matched. Never the value itself.
    source: str | None = Field(default=None, max_length=256)


class DomDiagnosticsRequest(BaseModel):
    extractor: str = Field(..., min_length=1, max_length=64)
    outcome: ExtractionOutcome
    job_id: str = Field(..., min_length=1, max_length=64)
    url: str = Field(..., max_length=2048)
    doc_title: str = Field(default="", max_length=512)
    missing: list[str] = Field(default_factory=list, max_length=16)
    fields: list[DomFieldReport] = Field(default_factory=list, max_length=16)
    # Sanitized job-container HTML (client caps it at ~50KB; the slack here
    # tolerates multi-byte content). null when no usable subtree was found.
    job_html: str | None = Field(default=None, max_length=120_000)
    user_agent: str = Field(default="", max_length=512)
    captured_at: str = Field(default="", max_length=64)


class DomDiagnosticsResult(BaseModel):
    """Structured LLM analysis of an extraction failure, shown in /admin."""

    likely_cause: str
    # What the scraper could not retrieve, in the model's words.
    missing_data: list[str]
    # What probably changed in LinkedIn's DOM to cause this.
    suspected_dom_change: str
    # Concrete CSS selectors the model believes now locate the missing fields,
    # read off the sanitized HTML when present (e.g. ["h1._abc123 → title"]).
    # Empty when no HTML was available or nothing could be pinpointed.
    suggested_selectors: list[str]
    # Concrete next step for us (e.g. "add `h1._abc123` to TITLE_SELECTORS").
    recommended_fix: str
    confidence: Literal["low", "medium", "high"]
