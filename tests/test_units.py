"""Unit tests for PDF generation and helper utilities."""
import io
import os

import pypdf

os.environ.setdefault("GOOGLE_API_KEY", "test-key-not-real")

from pdf_generator import _auto_fill, generate_arc_application
from conftest import MOCK_GUIDANCE


def _extract_text(pdf_bytes: bytes) -> str:
    """Extract all text from PDF bytes using pypdf."""
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


APPLICANT = {
    "name": "Jane Smith",
    "email": "jane@example.com",
    "phone": "555-0100",
    "mailing_address": "123 Main St, Raleigh NC",
    "property_address": "456 Oak Ave, Raleigh NC",
    "project_description": "6-foot wooden privacy fence",
}


# ── _auto_fill ────────────────────────────────────────────────────────────────

def test_autofill_name():
    assert _auto_fill("Owner Name", APPLICANT, MOCK_GUIDANCE) == "Jane Smith"

def test_autofill_name_variants():
    for label in ("Applicant Name", "Homeowner Name", "Property Owner"):
        assert _auto_fill(label, APPLICANT, MOCK_GUIDANCE) == "Jane Smith"

def test_autofill_email():
    assert _auto_fill("Email Address", APPLICANT, MOCK_GUIDANCE) == "jane@example.com"

def test_autofill_phone():
    assert _auto_fill("Phone Number", APPLICANT, MOCK_GUIDANCE) == "555-0100"

def test_autofill_mailing_address():
    assert _auto_fill("Mailing Address", APPLICANT, MOCK_GUIDANCE) == "123 Main St, Raleigh NC"

def test_autofill_property_address():
    assert _auto_fill("Property Address", APPLICANT, MOCK_GUIDANCE) == "456 Oak Ave, Raleigh NC"

def test_autofill_property_address_fallback():
    applicant_no_prop = {**APPLICANT, "property_address": ""}
    result = _auto_fill("Property Address", applicant_no_prop, MOCK_GUIDANCE)
    assert result == "123 Main St, Raleigh NC"

def test_autofill_project_description():
    assert _auto_fill("Description of Work", APPLICANT, MOCK_GUIDANCE) == "6-foot wooden privacy fence"

def test_autofill_project_type():
    assert _auto_fill("Type of Improvement", APPLICANT, MOCK_GUIDANCE) == "Fences"

def test_autofill_unknown_field_returns_empty():
    assert _auto_fill("Some Unknown Field", APPLICANT, MOCK_GUIDANCE) == ""


# ── PDF generation ────────────────────────────────────────────────────────────

def test_generate_pdf_returns_bytes():
    pdf = generate_arc_application(MOCK_GUIDANCE, APPLICANT)
    assert isinstance(pdf, bytes)

def test_generate_pdf_is_valid_pdf():
    pdf = generate_arc_application(MOCK_GUIDANCE, APPLICANT)
    assert pdf[:4] == b"%PDF"

def test_generate_pdf_contains_hoa_name():
    pdf = generate_arc_application(MOCK_GUIDANCE, APPLICANT)
    assert "Test HOA" in _extract_text(pdf)

def test_generate_pdf_contains_applicant_name():
    pdf = generate_arc_application(MOCK_GUIDANCE, APPLICANT)
    assert "Jane Smith" in _extract_text(pdf)

def test_generate_pdf_with_form_fields():
    text = _extract_text(generate_arc_application(MOCK_GUIDANCE, APPLICANT))
    assert "Applicant Information" in text
    assert "Project Details" in text
    assert "Acknowledgements" in text

def test_generate_pdf_fallback_no_form_fields():
    guidance = {**MOCK_GUIDANCE, "form_fields": []}
    pdf = generate_arc_application(guidance, APPLICANT)
    assert pdf[:4] == b"%PDF"
    assert "Applicant Information" in _extract_text(pdf)

def test_generate_pdf_empty_applicant():
    pdf = generate_arc_application(MOCK_GUIDANCE, {})
    assert pdf[:4] == b"%PDF"

def test_generate_pdf_missing_hoa_name():
    guidance = {**MOCK_GUIDANCE, "hoa_name": ""}
    pdf = generate_arc_application(guidance, APPLICANT)
    assert "Homeowners Association" in _extract_text(pdf)


# ── _is_pdf (via app import) ──────────────────────────────────────────────────

def test_is_pdf_valid():
    from app import _is_pdf
    from io import BytesIO
    from werkzeug.datastructures import FileStorage
    fs = FileStorage(stream=BytesIO(b"%PDF-1.4 rest of file"), filename="test.pdf")
    assert _is_pdf(fs) is True

def test_is_pdf_invalid():
    from app import _is_pdf
    from io import BytesIO
    from werkzeug.datastructures import FileStorage
    fs = FileStorage(stream=BytesIO(b"not a pdf file"), filename="test.txt")
    assert _is_pdf(fs) is False

def test_is_pdf_empty():
    from app import _is_pdf
    from io import BytesIO
    from werkzeug.datastructures import FileStorage
    fs = FileStorage(stream=BytesIO(b""), filename="empty.pdf")
    assert _is_pdf(fs) is False
