"""Customer invoice PDF, rendered from the warehouse (get_invoice_detail), so the document always matches what was
billed, posted and collected: header, bill-to, terms, lines, tax, total, payments and a status stamp."""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

SELLER = ["Echo Labs, Inc.", "548 Market Street, Suite 400", "San Francisco, CA 94104, USA", "billing@echolabs.example.com"]
REMIT = "Remit to: Echo Labs, Inc. · ACH routing 121000248 · account ending 4417 · reference the invoice number"


def _m(v, cur="USD"):
    v = float(v or 0)
    sym = {"USD": "$", "GBP": "£", "EUR": "€", "INR": "₹", "CAD": "C$"}.get(cur, "")
    return f"{sym}{v:,.2f}" if sym else f"{v:,.2f} {cur}"


def render(detail, out_dir: Path):
    h = detail["header"]
    tax = detail.get("tax") or {}
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{h['invoice_ref']}.pdf"
    ss = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=ss["Normal"], fontSize=8.5, leading=11)
    doc = SimpleDocTemplate(str(path), pagesize=LETTER, leftMargin=0.7 * inch, rightMargin=0.7 * inch,
                            topMargin=0.6 * inch, bottomMargin=0.6 * inch, title=f"Invoice {h['invoice_ref']}")
    status = (h.get("status") or "").upper()
    stamp = {"PAID": colors.HexColor("#1f7a4d")}.get(status, colors.HexColor("#b42318") if (h.get("days_past_due") or 0) > 0 else colors.HexColor("#9a6200"))
    head = Table([[Paragraph("<b><font size=16>Echo Labs</font></b><br/>" + "<br/>".join(SELLER), small),
                   Paragraph(f"<para align=right><b><font size=18>INVOICE</font></b><br/><font size=10>{h['invoice_ref']}</font><br/>"
                             f"<font color='{stamp.hexval()}'><b>{status or 'OPEN'}</b></font></para>", ss["Normal"])]],
                 colWidths=[3.8 * inch, 3.3 * inch])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    terms_days = (detail.get("contract") or {}).get("payment_terms_days") or h.get("terms_days")
    meta = [["Bill to", "Invoice date", "Due date", "Terms"],
            [Paragraph(f"<b>{h.get('customer_name') or h['customer_id']}</b><br/>Customer {h['customer_id']}"
                       + (f"<br/>{tax.get('country')}" if tax.get("country") else ""), small),
             h.get("invoice_date") or "", h.get("due_date") or "", f"Net {terms_days}" if terms_days else "Due on receipt"]]
    ref_line = []
    if h.get("project_id"):
        ref_line.append(f"Project {h['project_id']}{' · ' + h['project_name'] if h.get('project_name') else ''}")
    if h.get("contract_id"):
        ref_line.append(f"Contract {h['contract_id']}")
    if h.get("service_month"):
        ref_line.append(f"Service period {h['service_month']}")
    if (detail.get("stripe") or {}).get("invoice_number"):
        ref_line.append(f"Stripe {detail['stripe']['invoice_number']}")
    mt = Table(meta, colWidths=[2.8 * inch, 1.4 * inch, 1.4 * inch, 1.5 * inch])
    mt.setStyle(TableStyle([("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8), ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#787774")),
                            ("FONT", (0, 1), (-1, 1), "Helvetica", 9.5), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("LINEBELOW", (0, 1), (-1, 1), 0.5, colors.HexColor("#e9e9e7"))]))
    rows = [["#", "Description", "Quantity", "Rate", "Amount"]]
    for l in detail.get("rows", []):
        qty = f"{float(l['hours']):,.2f} h" if l.get("hours") else "1"
        rate = f"{float(l['rate']):,.4f}" if l.get("rate") and float(l["rate"]) < 10 else (_m(l["rate"]) if l.get("rate") else "")
        rows.append([str(l.get("line_no", "")), Paragraph(str(l.get("description") or l.get("line_type")), small), qty, rate, _m(l["amount"])])
    subtotal = float(h["amount"] or 0)
    tax_usd = float(tax.get("tax_usd") or 0)
    rows += [["", "", "", "Subtotal", _m(subtotal)]]
    if tax:
        rows += [["", "", "", f"Tax ({tax.get('tax_regime')}, {float(tax.get('tax_rate') or 0):.2%})", _m(tax_usd)]]
    rows += [["", "", "", "Total due (USD)", _m(subtotal + tax_usd)]]
    if tax and tax.get("currency") and tax["currency"] != "USD":
        rows += [["", "", "", f"In {tax['currency']} at {float(tax.get('invoice_rate') or 0):.4f}", _m(tax.get("amount_local"), tax["currency"])]]
    lt = Table(rows, colWidths=[0.35 * inch, 3.5 * inch, 1.0 * inch, 1.15 * inch, 1.1 * inch], repeatRows=1)
    n = len(detail.get("rows", []))
    lt.setStyle(TableStyle([("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f7f7f5")),
                            ("FONT", (0, 1), (-1, -1), "Helvetica", 9), ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
                            ("LINEBELOW", (0, 0), (-1, n), 0.4, colors.HexColor("#e9e9e7")),
                            ("FONT", (3, -1), (-1, -1), "Helvetica-Bold", 10), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story = [head, Spacer(1, 16), mt, Spacer(1, 6), Paragraph(" · ".join(ref_line), small), Spacer(1, 14), lt, Spacer(1, 14)]
    pays = [p for p in detail.get("payments", []) if p.get("applied_ref") == h["invoice_ref"]]
    if pays:
        story += [Paragraph("<b>Payments received</b>", small)]
        story += [Paragraph(f"{p['received_date']} · {p['payment_id']} · {_m(p['amount'])}", small) for p in pays]
        story += [Paragraph(f"<b>Balance due: {_m(h.get('balance'))}</b>", small), Spacer(1, 10)]
    story += [Paragraph(REMIT, small), Spacer(1, 4),
              Paragraph("Generated by Finance OS from the general ledger and billing records; this copy matches the posted invoice.", small)]
    doc.build(story)
    return path
