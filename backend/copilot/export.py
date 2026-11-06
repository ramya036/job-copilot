"""Render a tailored draft as a one-page-style Word document or PDF."""
from __future__ import annotations

import io

from .resume import Resume

ASCII = str.maketrans({"–": "-", "—": "-", "’": "'", "‘": "'", "“": '"', "”": '"', "•": "-", "→": "->", "é": "e", "…": "..."})


def _sections(draft: dict, resume: Resume):
    """(heading, rows) pairs in the draft's order, with titles and dates copied from the résumé, never the model."""
    exp, proj = [], []
    for s in draft["sections"]:
        src = resume.section(s["id"])
        if not src or not s["bullets"]:
            continue
        if "company" in src:
            exp.append((f"{src['company']} | {src['title']}", f"{src['location']}  {src['dates']}", s["bullets"]))
        else:
            proj.append((f"{src['name']} | {src['subtitle']}", ", ".join(src.get("tech", [])[:6]), s["bullets"]))
    return exp, proj


def to_docx(draft: dict, resume: Resume) -> bytes:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name, style.font.size = "Calibri", Pt(10.5)
    for sec in doc.sections:
        sec.left_margin = sec.right_margin = sec.top_margin = sec.bottom_margin = Pt(40)

    c = resume.raw["contact"]
    h = doc.add_paragraph()
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = h.add_run(resume.name.upper())
    r.bold, r.font.size = True, Pt(16)
    line = doc.add_paragraph(" | ".join(v for v in [c.get("email"), c.get("linkedin"), c.get("github"), c.get("location")] if v))
    line.alignment = WD_ALIGN_PARAGRAPH.CENTER

    def heading(text):
        p = doc.add_paragraph()
        run = p.add_run(text.upper())
        run.bold, run.font.size = True, Pt(11.5)
        p.paragraph_format.space_before = Pt(8)

    if draft.get("summary"):
        heading("Summary")
        doc.add_paragraph(draft["summary"])

    exp, proj = _sections(draft, resume)
    for title, rows in (("Experience", exp), ("Projects", proj)):
        if not rows:
            continue
        heading(title)
        for head, meta, bullets in rows:
            p = doc.add_paragraph()
            p.add_run(head).bold = True
            p.add_run(f"    {meta}")
            for b in bullets:
                doc.add_paragraph(b["text"], style="List Bullet")

    if draft.get("skills"):
        heading("Skills")
        doc.add_paragraph(", ".join(draft["skills"]))
    heading("Education")
    for e in resume.raw.get("education", []):
        p = doc.add_paragraph()
        p.add_run(f"{e['degree']}, {e['school']}").bold = True
        p.add_run(f"    {e['dates']}" + (f"  GPA {e['gpa']}" if e.get("gpa") else ""))

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def to_pdf(draft: dict, resume: Resume) -> bytes:
    from fpdf import FPDF

    pdf = FPDF(format="Letter")
    pdf.set_margins(16, 14, 16)
    pdf.set_auto_page_break(True, 14)
    pdf.add_page()
    t = lambda s: str(s).translate(ASCII).encode("latin-1", "replace").decode("latin-1")
    w = pdf.w - pdf.l_margin - pdf.r_margin

    pdf.set_font("Helvetica", "B", 17)
    pdf.cell(w, 8, t(resume.name), align="C", new_x="LMARGIN", new_y="NEXT")
    c = resume.raw["contact"]
    pdf.set_font("Helvetica", "", 9.5)
    pdf.cell(w, 5, t(" | ".join(v for v in [c.get("email"), c.get("linkedin"), c.get("github"), c.get("location")] if v)),
             align="C", new_x="LMARGIN", new_y="NEXT")

    def heading(text):
        pdf.ln(2.5)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(w, 6, t(text.upper()), new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(120, 120, 140)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + w, pdf.get_y())
        pdf.ln(1.2)

    def para(text, size=9.8):
        pdf.set_font("Helvetica", "", size)
        pdf.multi_cell(w, 4.6, t(text), new_x="LMARGIN", new_y="NEXT")

    if draft.get("summary"):
        heading("Summary")
        para(draft["summary"])
    exp, proj = _sections(draft, resume)
    for title, rows in (("Experience", exp), ("Projects", proj)):
        if not rows:
            continue
        heading(title)
        for head, meta, bullets in rows:
            pdf.set_font("Helvetica", "B", 10.2)
            pdf.cell(w * 0.62, 5.2, t(head))
            pdf.set_font("Helvetica", "", 9.2)
            pdf.cell(w * 0.38, 5.2, t(meta), align="R", new_x="LMARGIN", new_y="NEXT")
            for b in bullets:
                pdf.set_font("Helvetica", "", 9.8)
                pdf.set_x(pdf.l_margin + 2)
                pdf.multi_cell(w - 2, 4.6, t("-  " + b["text"]), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(0.8)
    if draft.get("skills"):
        heading("Skills")
        para(", ".join(draft["skills"]))
    heading("Education")
    for e in resume.raw.get("education", []):
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(w * 0.7, 5.2, t(f"{e['degree']}, {e['school']}"))
        pdf.set_font("Helvetica", "", 9.2)
        pdf.cell(w * 0.3, 5.2, t(e["dates"]), align="R", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
