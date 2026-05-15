#!/usr/bin/env python3
"""Generate a professional ARC application PDF."""

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


def generate_arc_application(
    guidance: dict[str, Any],
    applicant: dict[str, str],
) -> bytes:
    """Return PDF bytes for a completed ARC application."""

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=0.85 * inch,
        leftMargin=0.85 * inch,
        topMargin=0.85 * inch,
        bottomMargin=0.85 * inch,
    )

    styles = getSampleStyleSheet()
    dark = colors.HexColor("#0f172a")
    blue = colors.HexColor("#0ea5e9")
    light_bg = colors.HexColor("#f8fafc")
    red = colors.HexColor("#ef4444")

    title_style = ParagraphStyle(
        "Title", parent=styles["Normal"],
        fontSize=20, fontName="Helvetica-Bold", textColor=dark,
        spaceAfter=4,
    )
    sub_style = ParagraphStyle(
        "Sub", parent=styles["Normal"],
        fontSize=10, textColor=colors.HexColor("#64748b"),
        spaceAfter=2,
    )
    section_style = ParagraphStyle(
        "Section", parent=styles["Normal"],
        fontSize=11, fontName="Helvetica-Bold", textColor=blue,
        spaceBefore=14, spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "Body", parent=styles["Normal"],
        fontSize=10, textColor=dark, leading=15,
    )
    small_style = ParagraphStyle(
        "Small", parent=styles["Normal"],
        fontSize=8.5, textColor=colors.HexColor("#64748b"), leading=13,
    )
    check_style = ParagraphStyle(
        "Check", parent=styles["Normal"],
        fontSize=9.5, textColor=dark, leading=14, leftIndent=10,
    )

    hoa_name = guidance.get("hoa_name") or "Homeowners Association"
    project_type = guidance.get("project_type", "")
    story = []

    # ── Header ──────────────────────────────────────────────────────────────
    story.append(Paragraph(hoa_name, title_style))
    story.append(Paragraph("Architectural Review Committee — Application for Approval", sub_style))
    story.append(HRFlowable(width="100%", thickness=2, color=blue, spaceAfter=12))

    # ── Meta row ────────────────────────────────────────────────────────────
    meta_data = [
        ["Date:", date.today().strftime("%B %d, %Y"), "Project Type:", project_type],
    ]
    meta_table = Table(meta_data, colWidths=[1.1 * inch, 2.4 * inch, 1.2 * inch, 2.3 * inch])
    meta_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTNAME", (0, 0), (0, 0), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), dark),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 10))

    # ── Applicant information ────────────────────────────────────────────────
    story.append(Paragraph("1. Applicant Information", section_style))

    fields = [
        ("Owner Name", applicant.get("name", "")),
        ("Email Address", applicant.get("email", "")),
        ("Phone Number", applicant.get("phone", "")),
        ("Mailing Address", applicant.get("mailing_address", "")),
        ("Property / Project Address", applicant.get("property_address", "")),
    ]

    field_data = [[Paragraph(f"<b>{label}</b>", body_style),
                   Paragraph(value or "___________________________", body_style)]
                  for label, value in fields]

    field_table = Table(field_data, colWidths=[2.2 * inch, 4.8 * inch])
    field_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), light_bg),
        ("ROWBACKGROUND", (0, 0), (-1, -1), [light_bg, colors.white]),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(field_table)

    # ── Project description ──────────────────────────────────────────────────
    story.append(Paragraph("2. Project Description", section_style))
    desc = applicant.get("project_description") or guidance.get("overview", "")
    story.append(Paragraph(desc or "See attached plans.", body_style))
    story.append(Spacer(1, 8))

    # ── Required information checklist ───────────────────────────────────────
    req_info = guidance.get("required_info", [])
    if req_info:
        story.append(Paragraph("3. Information Provided in This Application", section_style))
        story.append(Paragraph(
            "Check each item confirming it is included or attached:", small_style))
        story.append(Spacer(1, 4))
        for item in req_info:
            story.append(Paragraph(f"☐  {item}", check_style))
        story.append(Spacer(1, 4))

    # ── Required documents ───────────────────────────────────────────────────
    req_docs = guidance.get("required_documents", [])
    if req_docs:
        story.append(Paragraph("4. Documents &amp; Attachments", section_style))
        for item in req_docs:
            story.append(Paragraph(f"☐  {item}", check_style))
        story.append(Spacer(1, 4))

    # ── Key rules acknowledgement ────────────────────────────────────────────
    key_rules = guidance.get("key_rules", [])
    if key_rules:
        story.append(Paragraph("5. Guideline Compliance Acknowledgement", section_style))
        story.append(Paragraph(
            "I confirm my project complies with the following guidelines:", small_style))
        story.append(Spacer(1, 4))
        for rule in key_rules:
            story.append(Paragraph(f"☐  {rule}", check_style))
        story.append(Spacer(1, 4))

    # ── Signature block ──────────────────────────────────────────────────────
    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0")))
    story.append(Spacer(1, 10))

    sig_data = [
        [
            Paragraph("<b>Applicant Signature</b>", body_style),
            Paragraph("<b>Printed Name</b>", body_style),
            Paragraph("<b>Date</b>", body_style),
        ],
        [
            Paragraph("________________________", body_style),
            Paragraph(applicant.get("name") or "________________________", body_style),
            Paragraph(date.today().strftime("%m / %d / %Y"), body_style),
        ],
    ]
    sig_table = Table(sig_data, colWidths=[2.7 * inch, 2.7 * inch, 1.6 * inch])
    sig_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(sig_table)

    # ── Footer note ──────────────────────────────────────────────────────────
    story.append(Spacer(1, 12))
    story.append(Paragraph(
        f"Submit this completed form and all attachments to the {hoa_name} Architectural Review Committee. "
        "Do not begin work until written approval is received. "
        "Generated by Ez-ARC Review · ezarc-friendly-review.lovable.app",
        small_style,
    ))

    doc.build(story)
    return buf.getvalue()
