#!/usr/bin/env python3
"""Generate a professional ARC application PDF using HOA-extracted form fields."""

from __future__ import annotations

import io
from datetime import date
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_DARK = colors.HexColor("#0f172a")
_BLUE = colors.HexColor("#0ea5e9")
_LIGHT_BG = colors.HexColor("#f8fafc")
_WHITE = colors.white
_BORDER = colors.HexColor("#e2e8f0")
_MUTED = colors.HexColor("#64748b")
_RED = colors.HexColor("#ef4444")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("ATitle", parent=base["Normal"],
            fontSize=20, fontName="Helvetica-Bold", textColor=_DARK, spaceAfter=4),
        "sub": ParagraphStyle("ASub", parent=base["Normal"],
            fontSize=10, textColor=_MUTED, spaceAfter=2),
        "section": ParagraphStyle("ASection", parent=base["Normal"],
            fontSize=11, fontName="Helvetica-Bold", textColor=_BLUE,
            spaceBefore=14, spaceAfter=5),
        "body": ParagraphStyle("ABody", parent=base["Normal"],
            fontSize=10, textColor=_DARK, leading=15),
        "small": ParagraphStyle("ASmall", parent=base["Normal"],
            fontSize=8.5, textColor=_MUTED, leading=13),
        "check": ParagraphStyle("ACheck", parent=base["Normal"],
            fontSize=9.5, textColor=_DARK, leading=14, leftIndent=8),
        "flabel": ParagraphStyle("AFlabel", parent=base["Normal"],
            fontSize=8.5, fontName="Helvetica-Bold", textColor=_MUTED, leading=12),
        "fvalue": ParagraphStyle("AFvalue", parent=base["Normal"],
            fontSize=10, textColor=_DARK, leading=14),
    }


# Keywords used to auto-fill fields from applicant data
_FILL_RULES: list[tuple[list[str], str]] = [
    (["owner name", "applicant name", "homeowner name", "property owner", "your name", "resident name"], "name"),
    (["email", "e-mail", "electronic mail"], "email"),
    (["phone", "telephone", "cell", "contact number", "mobile"], "phone"),
    (["mailing address", "billing address"], "mailing_address"),
    (["property address", "project address", "site address", "property location", "lot address"], "property_address"),
    (["description of work", "project description", "describe the", "scope of work",
      "work to be performed", "nature of improvement", "proposed work"], "project_description"),
    (["type of improvement", "project type", "type of project", "type of request",
      "improvement type", "category"], "project_type_"),  # special: from guidance
]


def _auto_fill(label: str, applicant: dict[str, str], guidance: dict[str, Any]) -> str:
    ll = label.lower()
    for keywords, key in _FILL_RULES:
        if any(kw in ll for kw in keywords):
            if key == "project_type_":
                return guidance.get("project_type", "")
            val = applicant.get(key, "")
            if not val and key == "property_address":
                val = applicant.get("mailing_address", "")
            return val
    if "date" in ll and any(w in ll for w in ("application date", "date of application",
                                               "date submitted", "submission date", "today")):
        return date.today().strftime("%B %d, %Y")
    return ""


def _field_row(story: list, label: str, value: str, required: bool, s: dict) -> None:
    req = ' <font color="#ef4444">*</font>' if required else ""
    data = [[
        Paragraph(f"{label}{req}", s["flabel"]),
        Paragraph(value or "___________________________", s["fvalue"]),
    ]]
    t = Table(data, colWidths=[2.1 * inch, 4.9 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), _LIGHT_BG),
        ("BACKGROUND", (1, 0), (1, 0), _WHITE),
        ("BOX", (0, 0), (-1, -1), 0.5, _BORDER),
        ("LINEAFTER", (0, 0), (0, 0), 0.5, _BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(t)
    story.append(Spacer(1, 1))


def _textarea_row(story: list, label: str, value: str, required: bool, s: dict) -> None:
    req = ' <font color="#ef4444">*</font>' if required else ""
    rows = [
        [Paragraph(f"{label}{req}", s["flabel"])],
        [Paragraph(value or " \n \n ", s["fvalue"])],
    ]
    t = Table(rows, colWidths=[7.0 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _LIGHT_BG),
        ("BACKGROUND", (0, 1), (-1, 1), _WHITE),
        ("BOX", (0, 0), (-1, -1), 0.5, _BORDER),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, _BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 18),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(t)
    story.append(Spacer(1, 1))


def _sig_row(story: list, label: str, applicant: dict[str, str], s: dict) -> None:
    story.append(Spacer(1, 10))
    data = [[
        Paragraph(f"<b>{label}</b>", s["body"]),
        Paragraph("_" * 28, s["body"]),
        Paragraph("<b>Printed Name</b>", s["body"]),
        Paragraph(applicant.get("name") or "_" * 20, s["body"]),
        Paragraph("<b>Date</b>", s["body"]),
        Paragraph(date.today().strftime("%m/%d/%Y"), s["body"]),
    ]]
    t = Table(data, colWidths=[1.5*inch, 1.6*inch, 1.1*inch, 1.5*inch, 0.6*inch, 0.9*inch])
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
    ]))
    story.append(t)
    story.append(Spacer(1, 4))


def generate_arc_application(
    guidance: dict[str, Any],
    applicant: dict[str, str],
) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        rightMargin=0.85*inch, leftMargin=0.85*inch,
        topMargin=0.85*inch, bottomMargin=0.85*inch,
    )
    s = _styles()
    hoa_name = guidance.get("hoa_name") or "Homeowners Association"
    project_type = guidance.get("project_type", "")
    form_fields: list[dict] = guidance.get("form_fields") or []
    story: list = []

    # ── Header ───────────────────────────────────────────────────────────────
    story.append(Paragraph(hoa_name, s["title"]))
    story.append(Paragraph("Architectural Review Committee — Application for Approval", s["sub"]))
    story.append(HRFlowable(width="100%", thickness=2, color=_BLUE, spaceAfter=10))

    meta = Table(
        [["Date:", date.today().strftime("%B %d, %Y"), "Project Type:", project_type]],
        colWidths=[1.0*inch, 2.5*inch, 1.1*inch, 2.4*inch],
    )
    meta.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTNAME", (0, 0), (0, 0), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), _DARK),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(meta)
    story.append(Spacer(1, 14))

    # ── Form body ─────────────────────────────────────────────────────────────
    if form_fields:
        has_sig = False
        for sec in form_fields:
            story.append(Paragraph(sec.get("section", ""), s["section"]))
            for field in sec.get("fields", []):
                ftype = field.get("type", "text")
                label = field.get("label", "")
                required = bool(field.get("required", False))
                value = _auto_fill(label, applicant, guidance)

                if ftype == "checkbox":
                    story.append(Paragraph(f"☐  {label}", s["check"]))
                    story.append(Spacer(1, 3))
                elif ftype == "signature":
                    _sig_row(story, label, applicant, s)
                    has_sig = True
                elif ftype == "textarea":
                    _textarea_row(story, label, value, required, s)
                else:
                    _field_row(story, label, value, required, s)
        if not has_sig:
            _add_default_sig(story, applicant, s)
    else:
        # Fallback: generic layout
        story.append(Paragraph("1. Applicant Information", s["section"]))
        for label, key in [
            ("Owner Name", "name"), ("Email", "email"), ("Phone", "phone"),
            ("Mailing Address", "mailing_address"), ("Property Address", "property_address"),
        ]:
            _field_row(story, label, applicant.get(key, ""), False, s)

        story.append(Paragraph("2. Project Description", s["section"]))
        _textarea_row(story, "Description of Work",
                      applicant.get("project_description") or guidance.get("overview", ""),
                      False, s)

        for heading, key in [
            ("3. Information to Include", "required_info"),
            ("4. Documents & Attachments", "required_documents"),
            ("5. Guideline Compliance", "key_rules"),
        ]:
            items = guidance.get(key, [])
            if items:
                story.append(Paragraph(heading, s["section"]))
                for item in items:
                    story.append(Paragraph(f"☐  {item}", s["check"]))
                story.append(Spacer(1, 4))

        _add_default_sig(story, applicant, s)

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 14))
    story.append(Paragraph(
        f"Submit this completed form and all attachments to the {hoa_name} Architectural Review "
        "Committee. Do not begin work until written approval is received. "
        "Generated by Ez-ARC Review · ezarc-friendly-review.lovable.app",
        s["small"],
    ))

    doc.build(story)
    return buf.getvalue()


def _add_default_sig(story: list, applicant: dict[str, str], s: dict) -> None:
    story.append(Spacer(1, 18))
    story.append(HRFlowable(width="100%", thickness=0.5, color=_BORDER))
    story.append(Spacer(1, 10))
    sig_data = [
        [Paragraph("<b>Applicant Signature</b>", s["body"]),
         Paragraph("<b>Printed Name</b>", s["body"]),
         Paragraph("<b>Date</b>", s["body"])],
        [Paragraph("________________________", s["body"]),
         Paragraph(applicant.get("name") or "________________________", s["body"]),
         Paragraph(date.today().strftime("%m / %d / %Y"), s["body"])],
    ]
    t = Table(sig_data, colWidths=[2.7*inch, 2.7*inch, 1.6*inch])
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
