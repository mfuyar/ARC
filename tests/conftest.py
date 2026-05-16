"""Shared fixtures for Ez-ARC Review tests."""
import os
import pytest

# Provide a fake API key so _make_client() doesn't raise before mocking kicks in
os.environ.setdefault("GOOGLE_API_KEY", "test-key-not-real")

from app import app as flask_app  # noqa: E402


# Minimal valid PDF bytes (1-page blank PDF)
MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
    b"xref\n0 4\n"
    b"0000000000 65535 f \n"
    b"0000000009 00000 n \n"
    b"0000000058 00000 n \n"
    b"0000000115 00000 n \n"
    b"trailer<</Size 4/Root 1 0 R>>\n"
    b"startxref\n190\n%%EOF"
)

MOCK_REVIEW = {
    "error": None,
    "hoa_name": "Test HOA",
    "details": {"name": "Jane Smith", "address": "123 Main St"},
    "decision": "Approved",
    "rationale": "All requirements met.",
    "non_compliant_items": [],
    "conditions": [],
    "compliance_letter": "",
    "quick_tips": ["Submit early in the month."],
}

MOCK_GUIDANCE = {
    "hoa_name": "Test HOA",
    "project_type": "Fences",
    "overview": "Fences must be wooden and no taller than 6 feet.",
    "required_info": ["Fence height", "Material"],
    "required_documents": ["Plot plan"],
    "key_rules": ["Max 6 ft height (§3.06)"],
    "common_mistakes": ["Missing neighbor signatures"],
    "fast_approval_tips": ["Include a site plan"],
    "form_fields": [
        {
            "section": "Applicant Information",
            "fields": [
                {"label": "Owner Name", "type": "text", "required": True},
                {"label": "Property Address", "type": "text", "required": True},
                {"label": "Email", "type": "text", "required": False},
            ],
        },
        {
            "section": "Project Details",
            "fields": [
                {"label": "Type of Improvement", "type": "text", "required": True},
                {"label": "Project Description", "type": "textarea", "required": True},
                {"label": "Anticipated Start Date", "type": "date", "required": False},
            ],
        },
        {
            "section": "Acknowledgements",
            "fields": [
                {"label": "I agree to notify neighbors", "type": "checkbox", "required": True},
                {"label": "Applicant Signature", "type": "signature", "required": True},
            ],
        },
    ],
}

MOCK_PROJECT_TYPES = {
    "hoa_name": "Test HOA",
    "project_types": [
        {"label": "Fences", "value": "Fences", "group": "Fencing"},
        {"label": "Decks", "value": "Decks", "group": "Structures"},
    ],
}


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.test_client() as c:
        yield c
