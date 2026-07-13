from __future__ import annotations

from io import BytesIO

from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.auth import get_current_user
from app.main import create_app
from app.schemas.cover_letter import COVER_LETTER_PDF_TEXT_MAX
from app.schemas.user import CurrentUser
from app.services.cover_letter_pdf import cover_letter_filename, render_cover_letter_pdf

USER_ID = "user-cover-letter-pdf"
SAMPLE_LETTER = """Jane Candidate
jane@example.com
Amsterdam, Netherlands

July 13, 2026

Dear Hiring Manager,

I am excited to apply for the Backend Engineer role at Acme & Sons.

My experience with Python, APIs, and distributed systems fits the role well.

Sincerely,

Jane Candidate"""


def _client(*, authenticated: bool = True) -> TestClient:
    app = create_app()
    if authenticated:
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            id=USER_ID,
            email="jane@example.com",
        )
    return TestClient(app)


def _pdf_text(pdf: bytes) -> str:
    reader = PdfReader(BytesIO(pdf))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_render_cover_letter_pdf_is_valid_and_extractable() -> None:
    pdf = render_cover_letter_pdf(SAMPLE_LETTER, company="Acme & Sons")

    assert pdf.startswith(b"%PDF-")
    reader = PdfReader(BytesIO(pdf))
    assert len(reader.pages) == 1
    assert reader.metadata.title == "Cover Letter - Acme & Sons"
    text = _pdf_text(pdf)
    assert "Jane Candidate" in text
    assert "Backend Engineer role" in text
    assert "Sincerely," in text


def test_renderer_escapes_markup_and_supports_multiple_pages() -> None:
    paragraph = "Use <script>alert('no')</script> as literal text. " + ("word " * 90)
    text = "Jane Candidate\n\nJuly 13, 2026\n\n" + "\n\n".join([paragraph] * 30)

    pdf = render_cover_letter_pdf(text)
    reader = PdfReader(BytesIO(pdf))

    assert len(reader.pages) > 1
    assert "<script>alert('no')</script>" in _pdf_text(pdf)


def test_cover_letter_filename_is_ascii_and_header_safe() -> None:
    assert cover_letter_filename("Acme & Sons / EU\r\nInjected") == (
        "Cover-Letter-Acme-Sons-EU-Injected.pdf"
    )
    assert cover_letter_filename("Ελληνική Εταιρεία") == "Cover-Letter.pdf"
    assert cover_letter_filename(None) == "Cover-Letter.pdf"


def test_pdf_endpoint_returns_downloadable_uncached_pdf() -> None:
    response = _client().post(
        "/cover-letter/pdf",
        json={"text": SAMPLE_LETTER, "company": "Acme & Sons"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"] == (
        'attachment; filename="Cover-Letter-Acme-Sons.pdf"'
    )
    assert response.content.startswith(b"%PDF-")
    assert "Jane Candidate" in _pdf_text(response.content)


def test_pdf_endpoint_requires_authentication() -> None:
    response = _client(authenticated=False).post(
        "/cover-letter/pdf",
        json={"text": SAMPLE_LETTER},
    )

    assert response.status_code == 401


def test_pdf_endpoint_rejects_blank_or_oversized_text() -> None:
    client = _client()

    blank = client.post("/cover-letter/pdf", json={"text": "   \n"})
    oversized = client.post(
        "/cover-letter/pdf",
        json={"text": "x" * (COVER_LETTER_PDF_TEXT_MAX + 1)},
    )

    assert blank.status_code == 422
    assert oversized.status_code == 422
