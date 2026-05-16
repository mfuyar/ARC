#!/usr/bin/env python3
"""HOA / ARC PDF review helper."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError as exc:
    raise SystemExit(
        "Missing dependency 'google-genai'. Install it with: pip install google-genai"
    ) from exc


_SYSTEM_PROMPT = (
    "You are an HOA/ARC review specialist. Be precise and evidence-based throughout. "
    "Every finding must cite the exact guideline section, rule title, or page, AND quote "
    "or paraphrase the specific text from the application that triggered it. "
    "Never use vague language like 'may not comply' or 'appears to be missing' — "
    "state exactly what the guideline requires and exactly what the application says or omits.\n\n"

    "FIRST, verify that the HOA guideline document is actually an HOA/ARC guideline "
    "(it should contain community rules, architectural standards, approval criteria, or "
    "similar governing content). If it is not — for example it is a blank form, a random "
    "document, or an ARC application itself — do not attempt a review. Instead return a "
    "JSON object with only the 'error' key set to a clear, friendly explanation such as: "
    "'No HOA guideline found. The first document does not appear to be an HOA guideline — "
    "it looks like [describe what it actually is]. Please upload the correct HOA guideline PDF.' "
    "Set all other fields to their empty defaults when returning an error.\n\n"

    "SECOND, extract the full official name of the HOA or community from the guideline document "
    "(e.g. 'Maplewood Homeowners Association', 'Lakeside Community HOA'). "
    "Use this name consistently throughout every field — in the rationale, in each non-compliant "
    "item, in the compliance letter header, body, and signature, and in the quick tips. "
    "Never write generic phrases like 'the HOA' or 'the community' — always use the actual name. "
    "The compliance letter must be signed: 'Sincerely,\\n[HOA Name] Architectural Review Committee'. "
    "If the name cannot be determined, use 'the HOA'.\n\n"

    "Given the HOA guideline document and the ARC application document, do the following:\n\n"

    "1. Extract key applicant details directly from the application "
    "(name, email, mailing address, project/property address, project description, "
    "and any other relevant fields present). Format each as 'Label: Value'.\n\n"

    "2. Compare the application against the HOA guidelines and decide whether it "
    "should be Approved, Partially Approved, or Pending Compliance.\n\n"
    "Decision criteria:\n"
    "- Approved: application meets all guideline requirements.\n"
    "- Partially Approved: application mostly meets requirements but needs "
    "conditions or clarifications.\n"
    "- Pending Compliance: application has material gaps or violations. Do NOT "
    "outright decline — instead give the homeowner a clear path to resubmit.\n\n"
    "For each non-compliant item use this exact format on a single string, "
    "with a newline between each sub-field:\n"
    "  Issue: <short title>\n"
    "  Guideline: <section/rule reference and quoted requirement>\n"
    "  Application: <what the application states or what is missing>\n"
    "  Required fix: <exactly what must be corrected or provided>\n\n"

    "3. Write a formal letter addressed to the homeowner by name for ALL decisions:\n\n"
    "  If Approved: write a warm official approval letter that:\n"
    "  - Greets the homeowner by name and opens with congratulations.\n"
    "  - States the project is formally approved, listing the project type, address, "
    "and description from the application.\n"
    "  - States any standard conditions that apply (e.g. work must match submitted plans, "
    "notify the committee upon completion, permits must be obtained if required).\n"
    "  - Closes warmly.\n"
    "  - Is signed from '[HOA Name] Architectural Review Committee'.\n\n"
    "  If Partially Approved or Pending Compliance: write a warm, respectful compliance letter that:\n"
    "  - Greets the homeowner by name and acknowledges their project positively.\n"
    "  - Lists each compliance issue as a numbered item with three short lines:\n"
    "      Guideline: <section and quoted rule>\n"
    "      Problem: <what the application says or omits>\n"
    "      Fix: <exactly what must be corrected or provided>\n"
    "    Keep each line concise — no paragraph prose inside the list.\n"
    "  - Closes with an encouraging invitation to resubmit.\n"
    "  - Is signed from '[HOA Name] Architectural Review Committee'.\n\n"

    "4. Generate quick tips for the homeowner based on the HOA guidelines — "
    "practical, specific actions they should take before submitting (or resubmitting) "
    "to maximize their chance of approval. Each tip must reference the specific guideline "
    "rule it comes from. Write tips as short, actionable sentences (one idea per tip). "
    "Always generate tips regardless of the decision.\n\n"

    "Return only a JSON object with exactly these keys:\n"
    "  error                — non-empty string if the guideline document is invalid/missing; "
    "empty string otherwise\n"
    "  hoa_name             — official name of the HOA extracted from the guideline; "
    "empty string if error\n"
    "  details              — list of 'Label: Value' strings extracted from the application; "
    "empty list if error\n"
    "  decision             — one of: Approved | Partially Approved | Pending Compliance; "
    "empty string if error\n"
    "  rationale            — 2-4 sentences citing specific guideline sections and application content; "
    "empty string if error\n"
    "  non_compliant_items  — list of strings, each citing the guideline rule, the application's "
    "actual text or omission, and the required fix; empty list if none or error\n"
    "  conditions           — list of strings (conditions for partial approval); "
    "empty list if not applicable or error\n"
    "  compliance_letter    — full letter text for ALL decisions: approval letter if Approved, "
    "compliance letter if Partially Approved or Pending Compliance; empty string only if error\n"
    "  quick_tips           — list of short actionable tip strings referencing specific guideline rules; "
    "empty list if error"
)

# ---------------------------------------------------------------------------
# HOA guideline context cache — text first, PDF fallback
# ---------------------------------------------------------------------------

_CACHE_TTL = 3600          # 1 hour
_CACHE_REFRESH_BUFFER = 120  # re-create 2 min before expiry
_MIN_TEXT_CHARS = 2000      # minimum chars to consider text file sufficient

_cache_lock = threading.Lock()
_park_avenue_cache_name: str | None = None
_park_avenue_cache_expiry: float = 0.0


def _build_park_avenue_cache(client: genai.Client, guideline_path: Path) -> str | None:
    """Try to create a Gemini context cache. Returns cache name or None if unsupported."""
    txt_path = guideline_path.with_suffix(".txt")
    use_text = txt_path.exists() and txt_path.stat().st_size >= _MIN_TEXT_CHARS

    try:
        if use_text:
            guideline_text = txt_path.read_text(encoding="utf-8", errors="replace")
            contents = [
                genai_types.Content(
                    role="user",
                    parts=[
                        genai_types.Part(
                            text=f"PARK AVENUE HOA GUIDELINE DOCUMENT:\n\n{guideline_text}"
                        )
                    ],
                )
            ]
            cache = client.caches.create(
                model="gemini-2.5-flash",
                config=genai_types.CreateCachedContentConfig(
                    contents=contents,
                    system_instruction=_SYSTEM_PROMPT,
                    ttl=f"{_CACHE_TTL}s",
                ),
            )
            return cache.name
        else:
            uploaded = client.files.upload(
                file=guideline_path,
                config=genai_types.UploadFileConfig(mime_type="application/pdf"),
            )
            _wait_active(client, uploaded)
            try:
                cache = client.caches.create(
                    model="gemini-2.5-flash",
                    config=genai_types.CreateCachedContentConfig(
                        contents=[
                            genai_types.Content(
                                role="user",
                                parts=[
                                    genai_types.Part.from_uri(
                                        file_uri=uploaded.uri,
                                        mime_type="application/pdf",
                                    )
                                ],
                            )
                        ],
                        system_instruction=_SYSTEM_PROMPT,
                        ttl=f"{_CACHE_TTL}s",
                    ),
                )
                return cache.name
            finally:
                try:
                    client.files.delete(name=uploaded.name)
                except Exception:
                    pass
    except Exception:
        # Context caching not supported for this model/plan — fall back to direct call
        return None


def _get_or_create_park_avenue_cache(client: genai.Client, guideline_path: Path) -> str | None:
    global _park_avenue_cache_name, _park_avenue_cache_expiry

    with _cache_lock:
        now = time.time()
        if _park_avenue_cache_name and now < _park_avenue_cache_expiry:
            return _park_avenue_cache_name

        name = _build_park_avenue_cache(client, guideline_path)
        if name:
            _park_avenue_cache_name = name
            _park_avenue_cache_expiry = now + _CACHE_TTL - _CACHE_REFRESH_BUFFER
        return name


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _make_client() -> genai.Client:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY environment variable is not set.")
    return genai.Client(api_key=api_key)


def _wait_active(client: genai.Client, file, timeout: int = 30) -> None:
    """Poll until the uploaded file reaches ACTIVE state."""
    for _ in range(timeout):
        f = client.files.get(name=file.name)
        state = f.state.name if hasattr(f.state, "name") else str(f.state)
        if state == "ACTIVE":
            return
        if state == "FAILED":
            raise ValueError(f"Gemini file processing failed for {file.name}")
        time.sleep(1)
    raise ValueError(f"Gemini file did not become active within {timeout}s")


def compare_pdf_files(
    guideline_path: Path | None,
    application_path: Path,
    is_park_avenue: bool = False,
) -> dict[str, object]:
    """Upload PDFs to Gemini and return a structured review result.

    For Park Avenue members, the guideline is served from a context cache —
    only the application PDF is uploaded per request.
    """
    client = _make_client()

    # Always upload the application PDF
    app_file = client.files.upload(
        file=application_path,
        config=genai_types.UploadFileConfig(mime_type="application/pdf"),
    )
    _wait_active(client, app_file)

    try:
        cache_name = None
        if is_park_avenue and guideline_path:
            cache_name = _get_or_create_park_avenue_cache(client, guideline_path)

        if cache_name:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    genai_types.Part.from_uri(
                        file_uri=app_file.uri,
                        mime_type="application/pdf",
                    ),
                    "This is the ARC application document. "
                    "Follow your system instructions and return the JSON review.",
                ],
                config=genai_types.GenerateContentConfig(
                    cached_content=cache_name,
                    response_mime_type="application/json",
                ),
            )
        else:
            # Check for txt guideline (Park Avenue fallback or uploaded txt)
            txt_path = Path(guideline_path).with_suffix(".txt") if guideline_path else None
            if txt_path and txt_path.exists() and txt_path.stat().st_size >= _MIN_TEXT_CHARS:
                guideline_text = txt_path.read_text(encoding="utf-8", errors="replace")
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[
                        genai_types.Part(
                            text=f"HOA GUIDELINE DOCUMENT:\n\n{guideline_text}"
                        ),
                        genai_types.Part.from_uri(
                            file_uri=app_file.uri,
                            mime_type="application/pdf",
                        ),
                        "The first content is the HOA guideline text. "
                        "The second is the ARC application PDF. "
                        "Follow your system instructions and return the JSON review.",
                    ],
                    config=genai_types.GenerateContentConfig(
                        system_instruction=_SYSTEM_PROMPT,
                        response_mime_type="application/json",
                    ),
                )
            else:
                # Upload guideline PDF
                guideline_file = client.files.upload(
                    file=guideline_path,
                    config=genai_types.UploadFileConfig(mime_type="application/pdf"),
                )
                _wait_active(client, guideline_file)
                try:
                    response = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=[
                            genai_types.Part.from_uri(
                                file_uri=guideline_file.uri,
                                mime_type="application/pdf",
                            ),
                            genai_types.Part.from_uri(
                                file_uri=app_file.uri,
                                mime_type="application/pdf",
                            ),
                            "The first document is the HOA guideline. "
                            "The second is the ARC application. "
                            "Follow your system instructions and return the JSON review.",
                        ],
                        config=genai_types.GenerateContentConfig(
                            system_instruction=_SYSTEM_PROMPT,
                            response_mime_type="application/json",
                        ),
                    )
                finally:
                    try:
                        client.files.delete(name=guideline_file.name)
                    except Exception:
                        pass
    finally:
        try:
            client.files.delete(name=app_file.name)
        except Exception:
            pass

    return json.loads(response.text)


_EXTRACT_TYPES_PROMPT = (
    "You are an HOA guideline analyst. Read the HOA guideline document and extract every "
    "project type or improvement category that requires an ARC (Architectural Review Committee) "
    "application or approval. Include everything — structures, fencing, landscaping, equipment, "
    "signage, etc.\n\n"
    "Return only a JSON object with exactly these keys:\n"
    "  hoa_name     — official name of the HOA\n"
    "  project_types — list of objects, each with:\n"
    "                  'label': readable name of the project type (include section ref if available)\n"
    "                  'value': same as label (used as form value)\n"
    "                  'group': category group name for grouping in a dropdown\n"
    "Order the groups and items logically."
)


def extract_project_types(guideline_path: Path) -> dict[str, object]:
    """Extract project types from an HOA guideline PDF."""
    client = _make_client()

    txt_path = guideline_path.with_suffix(".txt")
    if txt_path.exists() and txt_path.stat().st_size >= _MIN_TEXT_CHARS:
        guideline_text = txt_path.read_text(encoding="utf-8", errors="replace")
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[genai_types.Part(text=f"HOA GUIDELINE DOCUMENT:\n\n{guideline_text}")],
            config=genai_types.GenerateContentConfig(
                system_instruction=_EXTRACT_TYPES_PROMPT,
                response_mime_type="application/json",
            ),
        )
    else:
        uploaded = client.files.upload(
            file=guideline_path,
            config=genai_types.UploadFileConfig(mime_type="application/pdf"),
        )
        _wait_active(client, uploaded)
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    genai_types.Part.from_uri(
                        file_uri=uploaded.uri,
                        mime_type="application/pdf",
                    )
                ],
                config=genai_types.GenerateContentConfig(
                    system_instruction=_EXTRACT_TYPES_PROMPT,
                    response_mime_type="application/json",
                ),
            )
        finally:
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                pass

    return json.loads(response.text)


_APPLY_SYSTEM_PROMPT = (
    "You are an HOA/ARC application specialist. A homeowner wants to submit an ARC application "
    "and needs to know exactly what to include to get approved fast. "
    "You will be given the HOA guideline document and the homeowner's project type and description.\n\n"
    "Extract the official HOA name from the guideline and use it throughout your response.\n\n"
    "Be specific and evidence-based — always cite the exact guideline section or rule number "
    "when listing requirements. Never use vague language.\n\n"
    "Return only a JSON object with exactly these keys:\n"
    "  hoa_name             — official HOA name from the guideline\n"
    "  project_type         — the project type as provided\n"
    "  overview             — 2-3 sentence summary of what this project requires under the guidelines\n"
    "  required_info        — list of specific information the homeowner must state in their application "
    "(e.g. exact dimensions, materials, colors, location on property). "
    "Each item must cite the guideline section it comes from.\n"
    "  required_documents   — list of documents, drawings, photos, or attachments required for submission. "
    "Each item must cite the guideline section it comes from.\n"
    "  key_rules            — list of the most important guideline rules for this project type "
    "(e.g. max height, setback requirements, approved materials). "
    "Each item must quote the rule and cite its section.\n"
    "  common_mistakes      — list of specific mistakes homeowners make on this project type "
    "that cause rejection or delay. Each must reference the guideline rule being violated.\n"
    "  fast_approval_tips   — list of short actionable tips to get this specific project approved faster, "
    "each referencing the relevant guideline rule\n"
    "  form_fields          — the HOA's ARC application form structured as sections. "
    "Extract this from the actual application template in the guideline; if none exists, "
    "infer the fields from the stated requirements for this project type. "
    "Return a list of section objects, each with:\n"
    "    'section': section heading (e.g. 'Applicant Information', 'Project Details')\n"
    "    'fields': list of field objects, each with:\n"
    "      'label': exact field label as it appears on the form\n"
    "      'type': one of 'text', 'textarea', 'date', 'checkbox', 'signature'\n"
    "      'required': true or false\n"
    "  Use 'checkbox' for acknowledgement items and initials lines. "
    "Use 'signature' only for signature/date pairs at the end."
)


def get_application_guidance(
    guideline_path: Path | None,
    project_type: str,
    project_description: str,
    is_park_avenue: bool = False,
) -> dict[str, object]:
    """Return a checklist and guidance for building an ARC application."""
    client = _make_client()

    user_request = (
        f"PROJECT TYPE: {project_type}\n"
        f"HOMEOWNER DESCRIPTION: {project_description or 'Not provided'}\n\n"
        "Based on the HOA guideline, tell me exactly what to include in my ARC application "
        "to get approved as fast as possible."
    )

    # Always use txt or PDF directly — the review cache uses a different system prompt
    txt_path = Path(guideline_path).with_suffix(".txt") if guideline_path else None
    if txt_path and txt_path.exists() and txt_path.stat().st_size >= _MIN_TEXT_CHARS:
        guideline_text = txt_path.read_text(encoding="utf-8", errors="replace")
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                genai_types.Part(text=f"HOA GUIDELINE DOCUMENT:\n\n{guideline_text}"),
                genai_types.Part(text=user_request),
            ],
            config=genai_types.GenerateContentConfig(
                system_instruction=_APPLY_SYSTEM_PROMPT,
                response_mime_type="application/json",
            ),
        )
    else:
        guideline_file = client.files.upload(
            file=guideline_path,
            config=genai_types.UploadFileConfig(mime_type="application/pdf"),
        )
        _wait_active(client, guideline_file)
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    genai_types.Part.from_uri(
                        file_uri=guideline_file.uri,
                        mime_type="application/pdf",
                    ),
                    genai_types.Part(text=user_request),
                ],
                config=genai_types.GenerateContentConfig(
                    system_instruction=_APPLY_SYSTEM_PROMPT,
                    response_mime_type="application/json",
                ),
            )
        finally:
            try:
                client.files.delete(name=guideline_file.name)
            except Exception:
                pass

    return json.loads(response.text)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Review HOA guideline vs ARC application PDFs for compliance."
    )
    parser.add_argument("guideline_pdf", type=Path, help="Path to the HOA guideline PDF")
    parser.add_argument("application_pdf", type=Path, help="Path to the ARC application PDF")
    args = parser.parse_args()

    if not args.guideline_pdf.exists():
        print(f"Error: guideline file not found: {args.guideline_pdf}", file=sys.stderr)
        return 1
    if not args.application_pdf.exists():
        print(f"Error: application file not found: {args.application_pdf}", file=sys.stderr)
        return 1

    result = compare_pdf_files(args.guideline_pdf, args.application_pdf)
    print("Decision:", result["decision"])
    print("Summary:", result["rationale"])
    if result["non_compliant_items"]:
        print("Non-compliant items:")
        for item in result["non_compliant_items"]:
            print(f"  - {item}")
    if result["conditions"]:
        print("Conditions:")
        for item in result["conditions"]:
            print(f"  - {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
