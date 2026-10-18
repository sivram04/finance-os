"""Incoming vendor bill PDFs (data/inbox/ap) and their ground truth.

Each vendor bill (GPU vendor, GCP) and subcontractor bill becomes a PDF in that vendor's own layout:
different labels for the invoice number, date, PO and total. Every bill also gets the vendor's own
invoice number, which the ERP records too (AP clerks key it in), so intake can match a document to the
posted bill without any ground truth.

Document issues from config are injected here: a total that doesn't equal its lines, the same invoice
sent twice, a bill citing another vendor's PO. The ground truth (ap_document_truth, _lines) records what
each PDF really says; tests compare extraction against it. The warehouse never uses it for matching.
"""
from decimal import Decimal
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

STYLES = getSampleStyleSheet()
LINE_LABEL = {"gpu_usage": "GPU compute", "commit_shortfall": "Reserved capacity shortfall",
              "cloud_services": "Cloud services"}


def assign_vendor_invoice_numbers(cfg, bills, sub_bills):
    """Give every bill the vendor's own invoice number (also stored on the ERP record)."""
    layouts = cfg["ap_documents"]["layouts"]
    seq = {}
    for b in sorted(bills + sub_bills, key=lambda b: (b["bill_date"], b["bill_id"])):
        v = b["vendor_id"]
        seq[v] = seq.get(v, 0) + 1
        b["vendor_invoice_number"] = f"{layouts[v]['prefix']}-{b['bill_date']:%Y}-{seq[v]:04d}"


def build_ap_truth(cfg, bills, bill_lines, sub_bills):
    """One truth row per PDF that will land in the inbox (plus lines)."""
    layouts = cfg["ap_documents"]["layouts"]
    issues = cfg["ap_documents"]["issues"]
    lines_by_bill = {}
    for l in bill_lines:
        lines_by_bill.setdefault(l["bill_id"], []).append(l)

    def issue_for(vendor_id, month, project_id=None):
        return next((i for i in issues if i["vendor_id"] == vendor_id and i["service_month"] == month
                     and i.get("project_id", project_id) == project_id), None)

    docs, doc_lines = [], []

    def add(bill, month, lines, po_number):
        issue = issue_for(bill["vendor_id"], month, bill.get("project_id"))
        kind = issue["kind"] if issue else None
        printed_total = sum(l["amount"] for l in lines)
        if kind == "arithmetic_error":
            printed_total += Decimal(issue["total_delta"])
        if kind == "wrong_po":
            po_number = issue["printed_po"]
        copies = 2 if kind == "duplicate_submission" else 1
        for copy in range(1, copies + 1):
            doc_id = f"{bill['vendor_invoice_number']}" + (f"_copy{copy}" if copy > 1 else "")
            docs.append({
                "doc_file": f"{doc_id}.pdf", "erp_bill_id": bill["bill_id"], "vendor_id": bill["vendor_id"],
                "vendor_name": layouts[bill["vendor_id"]]["name"], "vendor_invoice_number": bill["vendor_invoice_number"],
                "invoice_date": bill["bill_date"], "po_number": po_number, "total": printed_total,
                "doc_issue": kind if (kind != "duplicate_submission" or copy > 1) else None,
            })
            for n, l in enumerate(lines, 1):
                doc_lines.append({"doc_file": f"{doc_id}.pdf", "line_no": n, **l})

    for b in bills:
        lines = [{"description": f"{LINE_LABEL[l['line_type']]}" + (f" ({l['gpu_type']})" if l["gpu_type"] else ""),
                  "quantity": l["quantity_hours"], "amount": l["amount"]} for l in lines_by_bill[b["bill_id"]]]
        add(b, b["service_month"], lines, None)
    for b in sub_bills:
        add(b, b["bill_date"].replace(day=1),
            [{"description": f"{b['description']} - project {b['project_id']}", "quantity": None, "amount": b["amount"]}],
            b["po_id"])
    return docs, doc_lines


def render_ap_pdfs(cfg, docs, doc_lines, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.pdf"):
        old.unlink()
    layouts = cfg["ap_documents"]["layouts"]
    lines_by_doc = {}
    for l in doc_lines:
        lines_by_doc.setdefault(l["doc_file"], []).append(l)
    for d in docs:
        lay = layouts[d["vendor_id"]]
        story = [Paragraph(lay["name"], STYLES["Title"]), Spacer(1, 6),
                 Paragraph("Bill to: Echo Labs, Inc., Accounts Payable", STYLES["Normal"]), Spacer(1, 10)]
        header = [[f"{lay['number_label']}:", d["vendor_invoice_number"]],
                  [f"{lay['date_label']}:", d["invoice_date"].isoformat()]]
        if d["po_number"]:
            header.append([f"{lay['po_label']}:", d["po_number"]])
        story += [Table(header, colWidths=[1.6 * inch, 3 * inch],
                        style=TableStyle([("FONT", (0, 0), (0, -1), "Helvetica-Bold")])), Spacer(1, 12)]
        rows = [["Description", "Quantity", "Amount"]]
        for l in lines_by_doc[d["doc_file"]]:
            rows.append([l["description"], f"{l['quantity']:,.4f}" if l["quantity"] is not None else "", f"{l['amount']:,.2f}"])
        rows.append([f"{lay['total_label']}:", "", f"{d['total']:,.2f}"])
        story.append(Table(rows, colWidths=[3.6 * inch, 1.2 * inch, 1.4 * inch],
                           style=TableStyle([("FONT", (0, 0), (-1, 0), "Helvetica-Bold"),
                                             ("FONT", (0, -1), (-1, -1), "Helvetica-Bold"),
                                             ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                                             ("LINEBELOW", (0, 0), (-1, 0), 0.5, "black"),
                                             ("LINEABOVE", (0, -1), (-1, -1), 0.5, "black")])))
        story += [Spacer(1, 12), Paragraph("Currency: USD. Payment terms: net 30.", STYLES["Normal"])]
        SimpleDocTemplate(str(out_dir / d["doc_file"]), pagesize=LETTER).build(story)
