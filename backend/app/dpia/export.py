"""The assessment as a PDF with the draft notice on every page."""

import io
from datetime import date
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.records.builder import NOTICE

BAND_COLORS = {
    "low": colors.HexColor("#DDEFD9"),
    "medium": colors.HexColor("#FFF2C2"),
    "high": colors.HexColor("#FFD3A8"),
    "very_high": colors.HexColor("#F5B5B0"),
}


def to_pdf(data: dict[str, Any], generated: date) -> bytes:
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9, leading=12)
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10)
    notice = ParagraphStyle(
        "notice", parent=small, textColor=colors.HexColor("#9C2A00"), fontName="Helvetica-Oblique"
    )

    def p(text: str, style: ParagraphStyle = body) -> Paragraph:
        return Paragraph(escape(text or "").replace("\n", "<br/>"), style)

    def footer(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica-Oblique", 7)
        canvas.drawString(15 * mm, 8 * mm, NOTICE)
        canvas.drawRightString(A4[0] - 15 * mm, 8 * mm, f"Page {doc.page}")
        canvas.restoreState()

    out = io.BytesIO()
    doc = SimpleDocTemplate(
        out,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=14 * mm,
        bottomMargin=16 * mm,
        title="Data protection impact assessment",
        author="ProcessLedger",
    )
    story: list[Any] = [
        Paragraph("Data protection impact assessment", styles["Title"]),
        p(NOTICE, notice),
        p(
            f"Activity: {data['activity_name']}    Status: {data['status'].replace('_', ' ')}    Generated: {generated.isoformat()}",
            small,
        ),
        Spacer(1, 4 * mm),
        Paragraph("Screening", styles["Heading2"]),
    ]
    rows = [[p("Criterion", small), p("Met", small), p("Basis", small)]]
    for c in data["screening"].get("criteria", []):
        rows.append(
            [
                p(c["label"], small),
                p({True: "yes", False: "no", None: "unknown"}[c["met"]], small),
                p(c["basis"], small),
            ]
        )
    table = Table(rows, colWidths=[55 * mm, 15 * mm, 110 * mm])
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
            ]
        )
    )
    story += [table, Spacer(1, 3 * mm)]
    story += [
        Paragraph("Systematic description", styles["Heading2"]),
        p(data["description"] or "Not yet written."),
    ]
    story += [
        Paragraph("Necessity and proportionality", styles["Heading2"]),
        p(data["necessity_proportionality"] or "Not yet written."),
    ]

    story.append(Paragraph("Risk register", styles["Heading2"]))
    risk_rows = [
        [p(h, small) for h in ("Risk", "L", "S", "Level", "Mitigation", "Residual", "Source")]
    ]
    styles_cmd: list[Any] = [
        ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
    ]
    for index, r in enumerate(data["risks"], start=1):
        residual = f"{r['residual_likelihood'] or '-'} x {r['residual_severity'] or '-'} ({(r['residual_level'] or 'not rated').replace('_', ' ')})"
        risk_rows.append(
            [
                p(r["title"], small),
                p(str(r["likelihood"]), small),
                p(str(r["severity"]), small),
                p(r["inherent_level"].replace("_", " "), small),
                p(r["mitigation"] or "", small),
                p(residual, small),
                p(r["citation"] or "", small),
            ]
        )
        styles_cmd.append(("BACKGROUND", (3, index), (3, index), BAND_COLORS[r["inherent_level"]]))
    if len(risk_rows) == 1:
        risk_rows.append([p("No risks recorded yet.", small)] + [p("", small)] * 6)
    risks = Table(
        risk_rows,
        colWidths=[42 * mm, 8 * mm, 8 * mm, 18 * mm, 48 * mm, 28 * mm, 28 * mm],
        repeatRows=1,
    )
    risks.setStyle(TableStyle(styles_cmd))
    story += [risks, Spacer(1, 3 * mm)]
    story.append(
        p(f"Overall residual risk: {(data['residual_risk'] or 'not rated').replace('_', ' ')}")
    )
    story += [
        Paragraph("Privacy officer opinion", styles["Heading2"]),
        p(data["officer_opinion"] or "Not yet given."),
    ]
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return out.getvalue()
