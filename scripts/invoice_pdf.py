"""Invoice PDF with backup detail (FR-7.3), read from the warehouse.

    python scripts/invoice_pdf.py --invoice PINV00014 [--db data/finance_os.duckdb] [--out reports/invoices]
    python scripts/invoice_pdf.py --project P-105          # every invoice on a project

Page 1: invoice header, bill-to, lines and total. For T&M invoices, page 2 is the backup: approved hours
by person and labor category for the service month. Validation exceptions on the invoice are printed in a
banner so nothing questionable goes out unnoticed.
"""
import argparse
from datetime import timedelta
from pathlib import Path

import duckdb
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

STYLES = getSampleStyleSheet()
GRID = TableStyle([
    ("FONT", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
    ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
])


def money(v):
    return f"${v:,.2f}" if v is not None else ""


def build(con, invoice_id, out_dir: Path):
    inv = con.execute("""
        select i.invoice_id, i.invoice_date, i.service_month, i.amount, i.project_id, p.project_name,
               p.project_type, k.contract_id, k.payment_terms_days, i.customer_id
        from staging.stg_projects__project_invoices i
        join staging.stg_projects__projects p using (project_id)
        join staging.stg_projects__contracts k on k.contract_id = i.contract_id
        where i.invoice_id = ?""", [invoice_id]).fetchone()
    if inv is None:
        raise SystemExit(f"No invoice {invoice_id}")
    (inv_id, inv_date, service_month, total, project_id, project_name, project_type,
     contract_id, terms, customer_id) = inv
    lines = con.execute("""
        select line_no, line_type, clin_id, labor_category, milestone_id, hours, rate, amount
        from staging.stg_projects__project_invoice_lines where invoice_id = ? order by line_no""", [inv_id]).fetchall()
    exceptions = con.execute("select detail from marts.fct_billing_exceptions where invoice_id = ?", [inv_id]).fetchall()

    path = out_dir / f"{inv_id}.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=LETTER, leftMargin=0.75 * inch, rightMargin=0.75 * inch)
    story = [
        Paragraph("Echo Labs, Inc.", STYLES["Title"]),
        Paragraph(f"<b>Invoice {inv_id}</b>", STYLES["Heading2"]),
        Table([
            ["Bill to", customer_id, "Invoice date", str(inv_date)],
            ["Project", f"{project_id} - {project_name}", "Due date", str(inv_date + timedelta(days=terms))],
            ["Contract", f"{contract_id} ({project_type})", "Service period", str(service_month or "Milestone")],
        ], colWidths=[0.9 * inch, 3.1 * inch, 1.1 * inch, 1.6 * inch],
            style=TableStyle([("FONT", (0, 0), (0, -1), "Helvetica-Bold"), ("FONT", (2, 0), (2, -1), "Helvetica-Bold")])),
        Spacer(1, 12),
    ]
    if exceptions:
        story.append(Paragraph("<font color='red'><b>Validation exceptions — do not send until resolved:</b> "
                               + "; ".join(e[0] for e in exceptions) + "</font>", STYLES["Normal"]))
        story.append(Spacer(1, 8))

    rows = [["#", "Description", "CLIN", "Hours", "Rate", "Amount"]]
    for n, ltype, clin, cat, ms, hours, rate, amount in lines:
        desc = {"labor": f"Labor - {cat}", "odc": "Other direct costs (at cost)", "milestone": f"Milestone {ms}"}[ltype]
        rows.append([n, desc, clin or "", f"{hours:,.2f}" if hours else "", money(rate) if rate else "", money(amount)])
    rows.append(["", "Total due", "", "", "", money(total)])
    t = Table(rows, colWidths=[0.3 * inch, 3.0 * inch, 0.6 * inch, 0.8 * inch, 0.9 * inch, 1.1 * inch])
    t.setStyle(GRID)
    t.setStyle(TableStyle([("FONT", (0, -1), (-1, -1), "Helvetica-Bold")]))
    story += [t, Spacer(1, 12), Paragraph(f"Payment terms: net {terms} days.", STYLES["Normal"])]

    if service_month is not None:
        backup = con.execute("""
            select t.employee_id, e.employee_name, t.labor_category, sum(t.hours)
            from staging.stg_projects__timesheets t
            join staging.stg_payroll__employees e using (employee_id)
            where t.project_id = ? and t.work_month = ? and t.approved
            group by all order by 3, 1""", [project_id, service_month]).fetchall()
        brows = [["Employee", "Name", "Labor category", "Hours"]] + [
            [eid, name, cat, f"{h:,.2f}"] for eid, name, cat, h in backup]
        brows.append(["", "", "Total", f"{sum(b[3] for b in backup):,.2f}"])
        bt = Table(brows, colWidths=[0.9 * inch, 1.8 * inch, 2.2 * inch, 1.0 * inch])
        bt.setStyle(GRID)
        story += [PageBreak(), Paragraph(f"Backup: approved hours for {service_month:%B %Y}", STYLES["Heading2"]), bt]

    doc.build(story)
    return path


def main():
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--invoice")
    g.add_argument("--project")
    p.add_argument("--db", default="data/finance_os.duckdb")
    p.add_argument("--out", default="reports/invoices")
    a = p.parse_args()
    con = duckdb.connect(a.db, read_only=True)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    ids = [a.invoice] if a.invoice else [r[0] for r in con.execute(
        "select invoice_id from staging.stg_projects__project_invoices where project_id = ? order by invoice_date",
        [a.project]).fetchall()]
    for inv_id in ids:
        print(build(con, inv_id, out))


if __name__ == "__main__":
    main()
