from __future__ import annotations

import json

import pytest

from app.schemas.cv import CvProfile
from app.services.cv import CvService, compute_cv_hash
from app.services.cv_extract import (
    EmptyCvText,
    UnsupportedCvFormat,
    extract_cv_text,
)
from tests.fakes.fake_db import FakeDB
from tests.fakes.fake_provider import FakeLLMProvider

USER = "user-cv"

# A CV with obvious PII we must never persist or log.
CV_TEXT = (
    "John Smith\n"
    "john.smith@example.com\n"
    "+1 (555) 010-2345\n"
    "Senior Backend Engineer\n"
    "Skills: Python, AWS, Docker\n"
)


def _service(db: FakeDB, provider: FakeLLMProvider, settings) -> CvService:
    return CvService(db=db, provider=provider, settings=settings)


# --- text extraction -------------------------------------------------------
def test_extract_txt_returns_cleaned_text() -> None:
    text = extract_cv_text(
        data=b"  Hello\n\n\nWorld  ", filename="cv.txt", content_type="text/plain"
    )
    assert text == "Hello\nWorld"


def test_extract_rejects_unknown_format() -> None:
    with pytest.raises(UnsupportedCvFormat):
        extract_cv_text(data=b"\x00\x01", filename="cv.rtf", content_type="application/rtf")


def test_extract_rejects_empty_file() -> None:
    with pytest.raises(EmptyCvText):
        extract_cv_text(data=b"", filename="cv.txt", content_type="text/plain")


# --- parse + store ---------------------------------------------------------
async def test_parse_and_store_persists_only_profile(settings) -> None:
    db = FakeDB()
    provider = FakeLLMProvider()
    svc = _service(db, provider, settings)

    resp = await svc.parse_and_store(user_id=USER, cv_text=CV_TEXT)

    assert provider.cv_parse_calls == 1
    assert "Python" in resp.profile.skills
    assert resp.profile.seniority == "senior"

    rows = db.store.tables["cv_profiles"]
    assert len(rows) == 1
    assert rows[0]["user_id"] == USER
    assert rows[0]["cv_hash"] == compute_cv_hash(resp.profile)
    # The raw CV text must never be persisted.
    assert "john.smith@example.com" not in json.dumps(rows[0])


async def test_cv_parse_log_redacts_raw_cv(settings) -> None:
    """PRIVACY: the llm_calls log must not contain the member's name/contact."""
    db = FakeDB()
    provider = FakeLLMProvider()
    svc = _service(db, provider, settings)

    await svc.parse_and_store(user_id=USER, cv_text=CV_TEXT)

    log = db.store.tables["llm_calls"][0]
    assert log["call_type"] == "cv_parse"
    prompt_json = json.dumps(log["prompt"])
    assert "John Smith" not in prompt_json
    assert "john.smith@example.com" not in prompt_json
    assert "010-2345" not in prompt_json
    assert "redacted" in prompt_json.lower()


async def test_reupload_upserts_single_row(settings) -> None:
    db = FakeDB()
    provider = FakeLLMProvider()
    svc = _service(db, provider, settings)

    await svc.parse_and_store(user_id=USER, cv_text=CV_TEXT)
    await svc.parse_and_store(user_id=USER, cv_text="Junior dev. Skills: React, SQL")

    rows = db.store.tables["cv_profiles"]
    assert len(rows) == 1  # one profile per user
    assert rows[0]["profile"]["seniority"] == "mid"


def test_compute_cv_hash_changes_with_profile() -> None:
    a = CvProfile(skills=["Python"], seniority="senior")
    b = CvProfile(skills=["Python", "AWS"], seniority="senior")
    assert compute_cv_hash(a) != compute_cv_hash(b)
    assert compute_cv_hash(a) == compute_cv_hash(CvProfile(skills=["Python"], seniority="senior"))


async def test_delete_removes_profile_and_fit_rows(settings) -> None:
    db = FakeDB()
    db.store.seed("cv_profiles", [{"user_id": USER, "profile": {}, "cv_hash": "h"}])
    db.store.seed(
        "job_fit_evaluations",
        [{"id": "1", "user_id": USER, "source": "linkedin", "job_id": "j", "cv_hash": "h"}],
    )
    svc = _service(db, FakeLLMProvider(), settings)

    svc.delete(USER)

    assert db.store.tables["cv_profiles"] == []
    assert db.store.tables["job_fit_evaluations"] == []


async def test_get_returns_none_when_absent(settings) -> None:
    svc = _service(FakeDB(), FakeLLMProvider(), settings)
    assert svc.get(USER) is None
    assert svc.get_response(USER) is None


async def test_update_profile_rehashes_and_preserves_provenance(settings) -> None:
    db = FakeDB()
    provider = FakeLLMProvider()
    svc = _service(db, provider, settings)

    original = await svc.parse_and_store(user_id=USER, cv_text=CV_TEXT)
    original_hash = db.store.tables["cv_profiles"][0]["cv_hash"]

    edited = original.profile.model_copy(update={"skills": [*original.profile.skills, "Rust"]})
    svc.update_profile(user_id=USER, profile=edited)

    rows = db.store.tables["cv_profiles"]
    assert len(rows) == 1  # still one row per user
    assert "Rust" in rows[0]["profile"]["skills"]
    # A different profile → different hash → fit cache invalidates on next view.
    assert rows[0]["cv_hash"] != original_hash
    # The original parse's provenance is kept (no LLM call on edit).
    assert rows[0]["provider"] == "fake"
    assert provider.cv_parse_calls == 1


async def test_update_profile_creates_row_when_absent(settings) -> None:
    db = FakeDB()
    svc = _service(db, FakeLLMProvider(), settings)

    profile = CvProfile(skills=["Python"], seniority="mid")
    svc.update_profile(user_id=USER, profile=profile)

    rows = db.store.tables["cv_profiles"]
    assert len(rows) == 1
    assert rows[0]["provider"] == "manual"
