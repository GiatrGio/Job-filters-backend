"""Render user-edited cover-letter text to an in-memory PDF.

The renderer is intentionally pure: it receives text, writes to ``BytesIO``,
and returns bytes. It never persists the letter or PDF. User text is escaped
before it reaches ReportLab's ``Paragraph`` markup parser.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from html import escape
from io import BytesIO
from pathlib import Path

import reportlab
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_SAFE_FILENAME_CHARACTERS = re.compile(r"[^A-Za-z0-9 -]+")
_MULTIPLE_SEPARATORS = re.compile(r"[ -]+")

_REGULAR_FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    Path(reportlab.__file__).resolve().parent / "fonts" / "Vera.ttf",
)
_BOLD_FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    Path(reportlab.__file__).resolve().parent / "fonts" / "VeraBd.ttf",
)


def _first_existing(candidates: tuple[Path, ...]) -> Path:
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("No usable TrueType font is available for PDF rendering.")


@lru_cache(maxsize=1)
def _register_fonts() -> tuple[str, str]:
    regular_name = "CanvasjobSans"
    bold_name = "CanvasjobSansBold"
    if regular_name not in pdfmetrics.getRegisteredFontNames():
        regular_path = _first_existing(_REGULAR_FONT_CANDIDATES)
        pdfmetrics.registerFont(TTFont(regular_name, str(regular_path)))
    if bold_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(bold_name, str(_first_existing(_BOLD_FONT_CANDIDATES))))
    pdfmetrics.registerFontFamily(
        "CanvasjobSans",
        normal=regular_name,
        bold=bold_name,
        italic=regular_name,
        boldItalic=bold_name,
    )
    return regular_name, bold_name


def _normalise_text(text: str) -> str:
    normalised = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
    return _CONTROL_CHARACTERS.sub("", normalised).strip()


def _paragraph_markup(block: str, *, bold_first_line: bool = False) -> str:
    lines = [escape(line) for line in block.split("\n")]
    if bold_first_line and lines:
        lines[0] = f"<b>{lines[0]}</b>"
    return "<br/>".join(lines)


def cover_letter_filename(company: str | None) -> str:
    """Return an ASCII-only, header-safe download filename."""

    if not company:
        return "Cover-Letter.pdf"
    ascii_company = (
        unicodedata.normalize("NFKD", company).encode("ascii", "ignore").decode("ascii")
    )
    safe_company = _SAFE_FILENAME_CHARACTERS.sub("-", ascii_company).strip()
    safe_company = _MULTIPLE_SEPARATORS.sub("-", safe_company)[:80].strip("-")
    return f"Cover-Letter-{safe_company}.pdf" if safe_company else "Cover-Letter.pdf"


def render_cover_letter_pdf(text: str, *, company: str | None = None) -> bytes:
    """Render a polished A4 cover letter entirely in memory."""

    regular_font, _bold_font = _register_fonts()
    clean_text = _normalise_text(text)
    if not clean_text:
        raise ValueError("letter text must not be blank")

    output = BytesIO()
    document_title = (
        f"Cover Letter - {company.strip()}"
        if company and company.strip()
        else "Cover Letter"
    )
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=0.78 * inch,
        rightMargin=0.78 * inch,
        topMargin=0.72 * inch,
        bottomMargin=0.72 * inch,
        title=document_title,
        author="canvasjob",
        subject="Cover letter",
        creator="canvasjob",
    )

    body_style = ParagraphStyle(
        "CoverLetterBody",
        fontName=regular_font,
        fontSize=11,
        leading=16,
        textColor=HexColor("#172033"),
        alignment=TA_LEFT,
        allowWidows=0,
        allowOrphans=0,
        splitLongWords=1,
        spaceAfter=0,
    )
    header_style = ParagraphStyle(
        "CoverLetterHeader",
        parent=body_style,
        fontSize=10,
        leading=14,
        textColor=HexColor("#354255"),
    )
    date_style = ParagraphStyle(
        "CoverLetterDate",
        parent=body_style,
        fontSize=10.5,
        leading=14,
        textColor=HexColor("#536075"),
    )

    blocks = [block.strip() for block in _PARAGRAPH_BREAK.split(clean_text) if block.strip()]
    story: list[Paragraph | Spacer] = []
    for index, block in enumerate(blocks):
        if index == 0:
            style = header_style
            markup = _paragraph_markup(block, bold_first_line=True)
            spacing = 18
        elif index == 1:
            style = date_style
            markup = _paragraph_markup(block)
            spacing = 18
        else:
            style = body_style
            markup = _paragraph_markup(block)
            spacing = 13
        story.append(Paragraph(markup, style))
        if index < len(blocks) - 1:
            story.append(Spacer(1, spacing))

    document.build(story)
    return output.getvalue()
