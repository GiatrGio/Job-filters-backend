from __future__ import annotations

import re
from typing import Any

from app.llm.base import LLMProvider
from app.schemas.cover_letter import (
    CoverLetterContent,
    CoverLetterInstructionsValidationResult,
)
from app.schemas.cv import CvContact, CvProfile
from app.schemas.diagnostics import DomDiagnosticsResult
from app.schemas.evaluate import EvaluationResult, FilterInput, JobInput, TokenUsage
from app.schemas.filter import FilterKind, FilterValidationResult, FilterValidationVerdict
from app.schemas.fit import FitDimensions, FitPoint, JobFitResult

_SKILL_VOCAB = [
    "python", "aws", "kubernetes", "docker", "react", "sql", "java", "go",
    "terraform", "fastapi",
]


def _classify_kind(text: str) -> FilterKind:
    """Heuristic mirror of the validator's kind classification.

    Real Anthropic / OpenAI providers ask the LLM for a verdict; in tests
    we lean on shape: open-ended starters and questions that don't begin
    with a yes/no form ("Is", "Does", "Can", "Are", "Will", "Has") map to
    "question"; everything else stays "criterion". Stable enough for
    tests to assert on the kind without hitting a real model.
    """
    stripped = text.strip().lower()
    yes_no_starters = ("is ", "does ", "do ", "can ", "are ", "was ", "were ", "will ", "has ", "have ", "should ", "must ")
    if any(stripped.startswith(s) for s in yes_no_starters):
        return FilterKind.criterion
    open_starters = ("what", "which", "who", "whom", "when", "where", "why", "how", "list", "tell", "describe", "name", "extract", "find", "show", "give", "enumerate")
    first_word = stripped.split(" ", 1)[0] if stripped else ""
    if first_word in open_starters:
        return FilterKind.question
    if stripped.endswith("?"):
        # A question that didn't match a yes/no starter — assume open-ended.
        return FilterKind.question
    return FilterKind.criterion


class FakeLLMProvider(LLMProvider):
    """Deterministic provider for tests.

    Returns `pass=True` for every filter whose lowercased text appears in the
    job description, `False` for every filter whose text starts with "must not",
    and `None` otherwise. Records how many times `evaluate` was called.

    For "question" kind filters, evaluate returns pass=null and synthesises
    a short answer from the description (echoing the criterion behavior
    that the live providers have to learn from the prompt).

    `validate_filter` keys off prefixes in the filter text so each verdict
    has a stable trigger:
      - text contains "[vague]"     → vague
      - text contains "[rejected]"  → rejected
      - anything else               → good
    Kind is derived from text shape via `_classify_kind`.
    """

    name = "fake"
    model = "fake-model"

    def __init__(self) -> None:
        self.calls = 0
        self.validation_calls = 0
        self.diagnostics_calls = 0
        self.cv_parse_calls = 0
        self.cv_contact_calls = 0
        self.fit_calls = 0
        self.cover_letter_calls = 0
        self.cover_letter_validation_calls = 0

    async def evaluate(
        self,
        job: JobInput,
        filters: list[FilterInput],
    ) -> tuple[list[EvaluationResult], TokenUsage]:
        self.calls += 1
        description_lc = job.job_description.lower()
        results: list[EvaluationResult] = []
        for f in filters:
            text_lc = f.text.lower()
            if f.kind == FilterKind.question:
                pass_val: bool | None = None
                evidence = "stub answer based on description"
            elif text_lc.startswith("must not") and text_lc[9:].strip() in description_lc:
                pass_val = False
                evidence = "mentioned in description"
            elif text_lc in description_lc:
                pass_val = True
                evidence = "matched literal substring"
            else:
                pass_val = None
                evidence = "not mentioned"
            results.append(
                EvaluationResult.model_validate(
                    {
                        "filter": f.text,
                        "pass": pass_val,
                        "evidence": evidence,
                        "kind": f.kind.value,
                    }
                )
            )
        return results, TokenUsage(input_tokens=1, output_tokens=1)

    async def validate_filter(
        self,
        text: str,
    ) -> tuple[FilterValidationResult, TokenUsage]:
        self.validation_calls += 1
        lower = text.lower()
        kind = _classify_kind(text)
        if "[rejected]" in lower:
            result = FilterValidationResult(
                verdict=FilterValidationVerdict.rejected,
                reason="not a job-posting filter",
                suggestion=None,
                kind=kind,
            )
        elif "[vague]" in lower:
            result = FilterValidationResult(
                verdict=FilterValidationVerdict.vague,
                reason="too subjective to evaluate",
                suggestion="Try a measurable criterion instead.",
                kind=kind,
            )
        else:
            result = FilterValidationResult(
                verdict=FilterValidationVerdict.good,
                reason="clear and decidable",
                suggestion=None,
                kind=kind,
            )
        return result, TokenUsage(input_tokens=1, output_tokens=1)

    async def diagnose_extraction(
        self,
        telemetry: dict[str, Any],
    ) -> tuple[DomDiagnosticsResult, TokenUsage]:
        self.diagnostics_calls += 1
        missing = telemetry.get("missing") or []
        has_html = bool(telemetry.get("job_html"))
        result = DomDiagnosticsResult(
            likely_cause="stub diagnosis based on telemetry",
            missing_data=list(missing),
            suspected_dom_change="selectors likely rotated",
            suggested_selectors=["h1.stub-title"] if has_html else [],
            recommended_fix="capture a fresh fixture",
            confidence="low",
        )
        return result, TokenUsage(input_tokens=1, output_tokens=1)

    async def parse_cv(
        self,
        cv_text: str,
    ) -> tuple[CvProfile, TokenUsage]:
        """Deterministically derive a non-PII profile from the text.

        Skills are picked from a small vocabulary present in the text, so two
        different CVs parse to different profiles (and therefore different
        cv_hash values) — which lets fit-cache tests exercise invalidation.
        """
        self.cv_parse_calls += 1
        lc = cv_text.lower()
        skills = [s.capitalize() for s in _SKILL_VOCAB if s in lc]
        profile = CvProfile(
            skills=skills,
            years_experience=5.0,
            seniority="senior" if "senior" in lc else "mid",
            titles=["Engineer"],
            domains=["software"],
            education=["BSc Computer Science"],
            languages=["English"],
            summary="Experienced engineer.",
        )
        return profile, TokenUsage(input_tokens=1, output_tokens=1)

    async def evaluate_fit(
        self,
        job: JobInput,
        cv: CvProfile,
    ) -> tuple[JobFitResult, TokenUsage]:
        """Score fit by how many of the CV's skills appear in the description."""
        self.fit_calls += 1
        desc_lc = job.job_description.lower()
        matched = [s for s in cv.skills if s.lower() in desc_lc]
        missing = [s for s in cv.skills if s.lower() not in desc_lc]
        overlap = min(5, max(1, len(matched) + 1))
        result = JobFitResult(
            score=overlap,
            dimensions=FitDimensions(skills=overlap, experience=4, domain=3),
            strengths=[
                FitPoint(point=f"Has {s}", evidence="in CV and job") for s in matched[:8]
            ],
            gaps=[
                FitPoint(point=f"Job is silent on {s}", evidence="not in job") for s in missing[:8]
            ],
            summary=f"{len(matched)} matching skills.",
        )
        return result, TokenUsage(input_tokens=1, output_tokens=1)

    async def generate_cover_letter(
        self,
        job: JobInput,
        cv: CvProfile,
        instructions: str,
    ) -> tuple[CoverLetterContent, TokenUsage]:
        """Deterministically compose a short letter from the inputs.

        References the job + a couple of CV skills + the instructions so tests
        can assert the inputs flowed through. Never emits identity (the live
        prompt isn't given name/contact either).
        """
        self.cover_letter_calls += 1
        skills = ", ".join(cv.skills[:3]) or "my background"
        paragraphs = [
            f"I am applying for the {job.job_title or 'role'} at "
            f"{job.job_company or 'your company'}.",
            f"My experience with {skills} fits what the role needs.",
        ]
        if instructions.strip():
            paragraphs.append(f"Per your instructions: {instructions.strip()}")
        content = CoverLetterContent(
            greeting="Dear Hiring Manager,",
            body_paragraphs=paragraphs,
            closing="Sincerely,",
        )
        return content, TokenUsage(input_tokens=1, output_tokens=1)

    async def extract_cv_contact(
        self,
        cv_text: str,
    ) -> tuple[CvContact, TokenUsage]:
        """Deterministically pull contact details from the CV text.

        Name = first line that looks like a name; email/phone via regex;
        location from an optional 'Location: ...' marker. Enough for prefill
        tests to assert empty fields fill and non-empty ones are preserved.
        """
        self.cv_contact_calls += 1
        lines = [ln.strip() for ln in cv_text.splitlines() if ln.strip()]
        first = lines[0] if lines else ""
        looks_like_name = (
            bool(first)
            and "@" not in first
            and not any(c.isdigit() for c in first)
            and 1 <= len(first.split()) <= 4
        )
        full_name = first if looks_like_name else ""
        email = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", cv_text)
        phone = re.search(r"[+(]?\d[\d\s().-]{6,}\d", cv_text)
        location = re.search(r"(?im)^location:\s*(.+)$", cv_text)
        contact = CvContact(
            full_name=full_name,
            email=email.group(0) if email else "",
            phone=phone.group(0).strip() if phone else "",
            location=location.group(1).strip() if location else "",
        )
        return contact, TokenUsage(input_tokens=1, output_tokens=1)

    async def validate_cover_letter_instructions(
        self,
        text: str,
    ) -> tuple[CoverLetterInstructionsValidationResult, TokenUsage]:
        self.cover_letter_validation_calls += 1
        lower = text.lower()
        if "[rejected]" in lower:
            result = CoverLetterInstructionsValidationResult(
                verdict=FilterValidationVerdict.rejected,
                reason="not cover-letter instructions",
                suggestion=None,
            )
        elif "[vague]" in lower:
            result = CoverLetterInstructionsValidationResult(
                verdict=FilterValidationVerdict.vague,
                reason="too fuzzy to act on",
                suggestion="Specify tone and length.",
            )
        else:
            result = CoverLetterInstructionsValidationResult(
                verdict=FilterValidationVerdict.good,
                reason="clear guidance",
                suggestion=None,
            )
        return result, TokenUsage(input_tokens=1, output_tokens=1)
