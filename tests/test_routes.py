"""Route tests for the Ez-ARC Review Flask app."""
import io
import json
from unittest.mock import patch

from conftest import MINIMAL_PDF, MOCK_GUIDANCE, MOCK_PROJECT_TYPES, MOCK_REVIEW


# ── Static pages ──────────────────────────────────────────────────────────────

def test_index_loads(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"Ez-ARC Review" in r.data


def test_apply_loads(client):
    r = client.get("/apply")
    assert r.status_code == 200
    assert b"Build a complete ARC application" in r.data


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert b"ok" in r.data


def test_sitemap(client):
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert b"urlset" in r.data


def test_robots(client):
    r = client.get("/robots.txt")
    assert r.status_code == 200


# ── Review — input validation ─────────────────────────────────────────────────

def test_review_no_files_redirects(client):
    r = client.post("/review", data={"is_park_avenue": "false"})
    assert r.status_code == 302  # flash + redirect


def test_review_invalid_pdf_rejected(client):
    bad_file = (io.BytesIO(b"not a pdf"), "fake.pdf")
    r = client.post("/review", data={
        "is_park_avenue": "false",
        "application_pdf": bad_file,
        "guideline_pdf": (io.BytesIO(MINIMAL_PDF), "guide.pdf"),
    }, content_type="multipart/form-data")
    assert r.status_code == 302


def test_review_missing_application_redirects(client):
    r = client.post("/review", data={
        "is_park_avenue": "false",
        "guideline_pdf": (io.BytesIO(MINIMAL_PDF), "guide.pdf"),
    }, content_type="multipart/form-data")
    assert r.status_code == 302


# ── Review — successful (mocked AI) ──────────────────────────────────────────

def test_review_park_avenue_success(client):
    with patch("app.compare_pdf_files", return_value=MOCK_REVIEW):
        r = client.post("/review", data={
            "is_park_avenue": "true",
            "application_pdf": (io.BytesIO(MINIMAL_PDF), "application.pdf"),
        }, content_type="multipart/form-data")
    assert r.status_code == 200
    assert b"Test HOA" in r.data
    assert b"Approved" in r.data


def test_review_non_member_success(client):
    with patch("app.compare_pdf_files", return_value=MOCK_REVIEW):
        r = client.post("/review", data={
            "is_park_avenue": "false",
            "application_pdf": (io.BytesIO(MINIMAL_PDF), "application.pdf"),
            "guideline_pdf": (io.BytesIO(MINIMAL_PDF), "guideline.pdf"),
        }, content_type="multipart/form-data")
    assert r.status_code == 200
    assert b"Test HOA" in r.data


def test_review_ai_error_shown(client):
    error_result = {**MOCK_REVIEW, "error": "Not a valid HOA guideline."}
    with patch("app.compare_pdf_files", return_value=error_result):
        r = client.post("/review", data={
            "is_park_avenue": "true",
            "application_pdf": (io.BytesIO(MINIMAL_PDF), "application.pdf"),
        }, content_type="multipart/form-data")
    assert r.status_code == 302  # flashes error and redirects


# ── Apply — input validation ──────────────────────────────────────────────────

def test_apply_missing_project_type_redirects(client):
    r = client.post("/apply", data={
        "is_park_avenue": "true",
        "project_type": "",
    })
    assert r.status_code == 302


def test_apply_non_member_missing_guideline_redirects(client):
    r = client.post("/apply", data={
        "is_park_avenue": "false",
        "project_type": "Fences",
    }, content_type="multipart/form-data")
    assert r.status_code == 302


# ── Apply — successful (mocked AI) ───────────────────────────────────────────

def test_apply_park_avenue_success(client):
    with patch("app.get_application_guidance", return_value=MOCK_GUIDANCE):
        r = client.post("/apply", data={
            "is_park_avenue": "true",
            "project_type": "Fences",
            "project_description": "6-foot wooden fence",
        })
    assert r.status_code == 200
    assert b"Test HOA" in r.data
    assert b"Fences" in r.data
    assert b"Fence height" in r.data


def test_apply_non_member_success(client):
    with patch("app.get_application_guidance", return_value=MOCK_GUIDANCE):
        r = client.post("/apply", data={
            "is_park_avenue": "false",
            "project_type": "Fences",
            "project_description": "wooden fence",
            "guideline_pdf": (io.BytesIO(MINIMAL_PDF), "guide.pdf"),
        }, content_type="multipart/form-data")
    assert r.status_code == 200
    assert b"Fences" in r.data


# ── Extract project types ─────────────────────────────────────────────────────

def test_extract_types_no_file(client):
    r = client.post("/extract-project-types")
    assert r.status_code == 400
    data = json.loads(r.data)
    assert "error" in data


def test_extract_types_invalid_pdf(client):
    r = client.post("/extract-project-types", data={
        "guideline_pdf": (io.BytesIO(b"not a pdf"), "bad.pdf"),
    }, content_type="multipart/form-data")
    assert r.status_code == 400


def test_extract_types_success(client):
    with patch("app.extract_project_types", return_value=MOCK_PROJECT_TYPES):
        r = client.post("/extract-project-types", data={
            "guideline_pdf": (io.BytesIO(MINIMAL_PDF), "guide.pdf"),
        }, content_type="multipart/form-data")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["hoa_name"] == "Test HOA"
    assert len(data["project_types"]) == 2


# ── Generate PDF ──────────────────────────────────────────────────────────────

def test_generate_pdf_success(client):
    r = client.post("/generate-application", data={
        "guidance_json": json.dumps(MOCK_GUIDANCE),
        "name": "Jane Smith",
        "email": "jane@example.com",
        "phone": "555-0100",
        "mailing_address": "123 Main St",
        "property_address": "123 Main St",
        "project_description": "6-foot wooden fence",
    })
    assert r.status_code == 200
    assert r.content_type == "application/pdf"
    assert r.data[:4] == b"%PDF"


def test_generate_pdf_empty_applicant(client):
    r = client.post("/generate-application", data={
        "guidance_json": json.dumps(MOCK_GUIDANCE),
        "name": "",
        "email": "",
    })
    assert r.status_code == 200
    assert r.data[:4] == b"%PDF"


def test_generate_pdf_no_form_fields(client):
    guidance_no_fields = {**MOCK_GUIDANCE, "form_fields": []}
    r = client.post("/generate-application", data={
        "guidance_json": json.dumps(guidance_no_fields),
        "name": "John Doe",
    })
    assert r.status_code == 200
    assert r.data[:4] == b"%PDF"
