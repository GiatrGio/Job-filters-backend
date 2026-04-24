"""Prompt templates for job-filter evaluation.

The prompt is shared across providers; each provider enforces the JSON output
shape through its own structured-output mechanism (Anthropic tool_use / OpenAI
function calling), but the system instructions and user framing are identical.
"""

from __future__ import annotations

from app.schemas.evaluate import FilterInput, JobInput

SYSTEM_PROMPT = """You are a strict evaluator of LinkedIn job postings against user-defined filters.

For EACH filter provided, decide whether the job posting satisfies it:
- true  → the description explicitly supports the filter.
- false → the description explicitly contradicts the filter.
- null  → the description is silent or ambiguous. Do NOT guess.

Rules:
- Use ONLY the information in the job description. Do not infer from company names or stereotypes.
- "Evidence" must be a short direct quote from the description (≤25 words) or exactly "not mentioned" when the filter cannot be decided from the text.
- Return one result per filter, in the SAME ORDER as the input filters.
- Echo the filter text verbatim in the "filter" field.
"""


def build_user_message(job: JobInput, filters: list[FilterInput]) -> str:
    filter_block = "\n".join(f"{i + 1}. {f.text}" for i, f in enumerate(filters))
    header_parts = [
        f"Job title: {job.job_title or 'unknown'}",
        f"Company: {job.job_company or 'unknown'}",
        f"Location: {job.job_location or 'unknown'}",
    ]
    header = "\n".join(header_parts)
    return (
        f"{header}\n\n"
        f"Job description:\n\"\"\"\n{job.job_description}\n\"\"\"\n\n"
        f"Filters to evaluate (in order):\n{filter_block}\n\n"
        "Return the evaluation via the return_evaluation tool."
    )


# JSON Schema for the tool input / function arguments. Kept here so both
# providers stay in sync with the pydantic EvaluationResult shape.
EVALUATION_TOOL_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "filter": {"type": "string"},
                    "pass": {"type": ["boolean", "null"]},
                    "evidence": {"type": "string"},
                },
                "required": ["filter", "pass", "evidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}

TOOL_NAME = "return_evaluation"
TOOL_DESCRIPTION = "Return the evaluation of the job posting against every provided filter."
