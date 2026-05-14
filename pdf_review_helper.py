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


def _build_park_avenue_cache(client: genai.Client, guideline_path: Path) -> str:
    """Create a Gemini context cache for the Park Avenue guideline.

    Strategy:
      1. If a .txt file exists alongside the PDF and has enough content,
         embed the text directly — zero file upload cost.
      2. Otherwise upload the PDF (handles images/illustrations).
    """
    txt_path = guideline_path.with_suffix(".txt")
    use_text = txt_path.exists() and txt_path.stat().st_size >= _MIN_TEXT_CHARS

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
    else:
        # Fall back to PDF upload (preserves images and illustrations)
        uploaded = client.files.upload(
            file=guideline_path,
            config=genai_types.UploadFileConfig(mime_type="application/pdf"),
        )
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
        finally:
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                pass

    return cache.name


def _get_or_create_park_avenue_cache(client: genai.Client, guideline_path: Path) -> str:
    global _park_avenue_cache_name, _park_avenue_cache_expiry

    with _cache_lock:
        now = time.time()
        if _park_avenue_cache_name and now < _park_avenue_cache_expiry:
            return _park_avenue_cache_name

        _park_avenue_cache_name = _build_park_avenue_cache(client, guideline_path)
        _park_avenue_cache_expiry = now + _CACHE_TTL - _CACHE_REFRESH_BUFFER
        return _park_avenue_cache_name


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _make_client() -> genai.Client:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY environment variable is not set.")
    return genai.Client(api_key=api_key)


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

    try:
        if is_park_avenue and guideline_path:
            # Use cached guideline — system_instruction is part of the cache
            cache_name = _get_or_create_park_avenue_cache(client, guideline_path)
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
            # Upload guideline PDF fresh for every non-Park-Avenue request
            guideline_file = client.files.upload(
                file=guideline_path,
                config=genai_types.UploadFileConfig(mime_type="application/pdf"),
            )
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
