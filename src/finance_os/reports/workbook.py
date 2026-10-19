"""The finance workbook (.xlsx): every statement and schedule a finance team keeps in Excel, built from the warehouse.

    python -m finance_os.reports.workbook --period quarter      # → reports/finance_workbook.xlsx

Sheets: Summary (contents and headline KPIs), Income statement, Balance sheet, Cash flow (one column per period),
KPIs, Budget vs actual, AR aging, Forecast, Unit economics, Cost structure, Price volume mix, Runway sensitivity and
Five-year plan.

Layout follows the conventions of a board workbook: a title block (company, sheet, period, units) on every sheet,
a styled header row with frozen panes, columns sized to their content, numbers right-aligned with thousands
separators and negatives in red brackets, statement lines indented under shaded section rows with ruled totals,
banded tables with filters and totals, gridlines off, and print set to landscape, one page wide, headers repeated.
"""
import argparse
import io
from datetime import date

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties

from finance_os.app import tools
from finance_os.paths import ROOT

COMPANY = "Echo Labs, Inc."
USD = '#,##0;[Red](#,##0);"–"'
USD2 = '#,##0.00;[Red](#,##0.00);"–"'
PCT = '0.0%;[Red](0.0%);"–"'
NUM1 = '0.0;[Red](0.0);"–"'
INT = '#,##0;[Red](#,##0);"–"'
XMULT = '0.0"x";[Red](0.0"x");"–"'

FONT = "Calibri"
INK, MUTED, RULE = "1F2937", "6B7280", "9CA3AF"
HEAD_FILL = PatternFill("solid", fgColor="1F3A5F")
SECTION_FILL = PatternFill("solid", fgColor="E8EDF3")
BAND_FILL = PatternFill("solid", fgColor="F6F8FA")
TOP = Border(top=Side(style="thin", color=RULE))
TOTAL = Border(top=Side(style="thin", color=INK), bottom=Side(style="double", color=INK))
HEADER_ROW = 4  # rows 1-3: title, subtitle, blank


def _f(**kw):
    return Font(name=FONT, size=kw.pop("size", 10), color=kw.pop("color", INK), **kw)


def _title(ws, title, subtitle):
    ws.sheet_view.showGridLines = False
    ws["A1"] = f"{COMPANY} · {title}"
    ws["A1"].font = _f(size=14, bold=True)
    ws["A2"] = subtitle
    ws["A2"].font = _f(color=MUTED)
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.print_title_rows = f"{HEADER_ROW}:{HEADER_ROW}"
    ws.oddFooter.left.text = f"{COMPANY} · {title}"
    ws.oddFooter.right.text = "Page &P of &N"


def _header_row(ws, labels, numeric):
    for i, (label, is_num) in enumerate(zip(labels, numeric), 1):
        c = ws.cell(HEADER_ROW, i, label)
        c.font, c.fill = _f(bold=True, color="FFFFFF"), HEAD_FILL
        c.alignment = Alignment(horizontal="right" if is_num else "left", vertical="center", wrap_text=True)
    ws.row_dimensions[HEADER_ROW].height = 30


def _fit(ws, min_w=9, max_w=46, first=None):
    widths = {}
    for row in ws.iter_rows(min_row=HEADER_ROW):
        for c in row:
            if c.value is None:
                continue
            v = c.value
            if isinstance(v, (int, float)):
                text = f"{v:,.0f}" if abs(v) >= 1 or v == 0 else f"{v:.1%}"
            else:
                text = str(v)
            indent = (c.alignment.indent or 0) * 1.5 if c.alignment else 0
            # header labels wrap onto two lines, so they count for about half their length
            weight = 0.6 if c.row == HEADER_ROW else 1.1
            widths[c.column] = max(widths.get(c.column, 0), len(text) * weight + indent + 2)
    for col, w in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = max(min_w, min(max_w, w))
    if first:
        ws.column_dimensions["A"].width = first


def _statement(ws, sheet, rows, periods, subtitle):
    _title(ws, sheet, f"{subtitle} · USD")
    _header_row(ws, ["", *periods], [False, *[True] * len(periods)])
    r_i = HEADER_ROW
    for r in (r for r in rows if r["sheet"] == sheet):
        r_i += 1
        style = r["style"]
        a = ws.cell(r_i, 1, r["line"])
        a.alignment = Alignment(indent=2 if style == "item" else 0)
        for j, p in enumerate(periods, 2):
            c = ws.cell(r_i, j, r[p])
            c.number_format = PCT if r["unit"] == "ratio" else USD
            c.alignment = Alignment(horizontal="right")
        cells = [ws.cell(r_i, j) for j in range(1, len(periods) + 2)]
        for c in cells:
            c.font = _f()
        if style == "header":
            for c in cells:
                c.fill, c.font = SECTION_FILL, _f(bold=True)
        elif style == "subtotal":
            for c in cells:
                c.font, c.border = _f(bold=True), TOP
        elif style == "total":
            for c in cells:
                c.font, c.border = _f(bold=True), TOTAL
        elif style in ("ratio", "check"):
            for c in cells:
                c.font = _f(italic=True, color=MUTED)
    ws.freeze_panes = ws.cell(HEADER_ROW + 1, 2)
    ws.page_setup.fitToHeight = 1  # a statement prints on one page
    _fit(ws, min_w=12, first=40)


def _table(ws, title, subtitle, rows, columns, totals=()):
    """columns: [(key, label, number format or None)]; totals: keys to sum in a total row."""
    _title(ws, title, subtitle)
    numeric = [fmt is not None for _, _, fmt in columns]
    _header_row(ws, [l for _, l, _ in columns], numeric)
    r_i = HEADER_ROW
    for n, row in enumerate(rows):
        r_i += 1
        for j, (key, _, fmt) in enumerate(columns, 1):
            v = row.get(key)
            if isinstance(v, (list, tuple)):
                v = ", ".join(map(str, v))
            c = ws.cell(r_i, j, v)
            c.font = _f()
            if fmt:
                c.number_format, c.alignment = fmt, Alignment(horizontal="right")
            if n % 2:
                c.fill = BAND_FILL
    if rows:
        ws.auto_filter.ref = f"A{HEADER_ROW}:{get_column_letter(len(columns))}{r_i}"
    if totals and rows:
        t = r_i + 1
        ws.cell(t, 1, "Total").font = _f(bold=True)
        for j, (key, _, fmt) in enumerate(columns, 1):
            c = ws.cell(t, j)
            if key in totals:
                col = get_column_letter(j)
                c.value = f"=SUBTOTAL(9,{col}{HEADER_ROW + 1}:{col}{r_i})"  # respects the filter, like Excel's own totals
                c.number_format, c.alignment = fmt, Alignment(horizontal="right")
            c.font, c.border = _f(bold=True), TOTAL
    ws.freeze_panes = ws.cell(HEADER_ROW + 1, 2)
    _fit(ws)


def _summary(wb, sheets, kpis, end):
    ws = wb.create_sheet("Summary", 0)
    _title(ws, "Finance workbook", f"Books closed through {end} · generated {date.today():%d %b %Y} · USD")
    ws["A4"], ws["A4"].font = "Headline", _f(size=12, bold=True)
    money = '"$"#,##0;[Red]("$"#,##0);"–"'
    labels = [("revenue", "Revenue (month)", money), ("gross_margin_pct", "Gross margin", PCT), ("net_burn", "Net burn (month)", money),
              ("closing_cash", "Cash (month end)", money), ("runway_months", "Runway (months)", NUM1), ("arr", "ARR", money),
              ("nrr", "Net revenue retention", PCT), ("dso_days", "DSO (days)", NUM1)]
    for i, (k, label, fmt) in enumerate(labels):
        r = 5 + i
        ws.cell(r, 1, label).font = _f()
        c = ws.cell(r, 2, kpis.get(k))
        c.number_format, c.font, c.alignment = fmt, _f(bold=True), Alignment(horizontal="right")
        for col in (1, 2):
            ws.cell(r, col).border = Border(bottom=Side(style="hair", color=RULE))
    start = 5 + len(labels) + 2
    ws.cell(start, 1, "Contents").font = _f(size=12, bold=True)
    for i, (name, desc) in enumerate(sheets):
        r = start + 1 + i
        c = ws.cell(r, 1, name)
        c.hyperlink, c.font = f"#'{name}'!A1", _f(color="1F5FBF", underline="single")
        ws.cell(r, 2, desc).font = _f(color=MUTED)
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 30, 70


def build(wh, period="month", periods=12):
    fs = tools.get_financial_statements(wh, period=period, periods=periods)
    end = fs["end_month"][:7]
    sub = {"month": "Monthly", "quarter": "Quarterly", "year": "Annual"}[period] + f" through {end}"
    wb = Workbook()
    wb.remove(wb.active)
    contents = []

    for sheet, desc in (("Income statement", "Revenue, cost of revenue, opex, EBITDA, depreciation, operating income"),
                        ("Balance sheet", "Assets, liabilities and equity at each period end; the check row must be zero"),
                        ("Cash flow", "Indirect method: operations, investing (capex), financing, free cash flow")):
        _statement(wb.create_sheet(sheet), sheet, fs["rows"], fs["periods"], sub)
        contents.append((sheet, desc))

    kpi = wh.query("""select strftime(month, '%Y-%m') as month, metric_name, value from marts.fct_kpi_monthly
                      where month <= ?::date order by month""", [fs["end_month"]])
    months = sorted({r["month"] for r in kpi})[-12:]
    by = {(r["metric_name"], r["month"]): r["value"] for r in kpi}
    latest = {k: v for (k, m), v in by.items() if m == months[-1]}
    ratio = {"gross_margin_pct", "nrr", "grr", "logo_churn_rate", "gross_mrr_churn_rate", "cei"}
    one_dp = {"runway_months", "dso_days"}
    counts = {"headcount", "active_customers", "new_customers", "churned_customers"}
    catalog = {r["metric_name"]: r for r in wh.query("select metric_name, label from seeds.metric_catalog")}
    ws = wb.create_sheet("KPIs")
    _title(ws, "KPIs", f"Monthly through {end}")
    _header_row(ws, ["Metric", "Unit", *months], [False, False, *[True] * len(months)])
    r_i = HEADER_ROW
    for n, name in enumerate(dict.fromkeys(r["metric_name"] for r in kpi)):
        r_i += 1
        unit = "%" if name in ratio else "days" if name == "dso_days" else "months" if name == "runway_months" else "#" if name in counts else "USD"
        ws.cell(r_i, 1, (catalog.get(name) or {}).get("label") or name.replace("_", " ").capitalize()).font = _f()
        ws.cell(r_i, 2, unit).font = _f(color=MUTED)
        for j, m in enumerate(months, 3):
            c = ws.cell(r_i, j, by.get((name, m)))
            c.number_format = PCT if name in ratio else NUM1 if name in one_dp else INT if name in counts else USD
            c.font, c.alignment = _f(), Alignment(horizontal="right")
        if n % 2:
            for j in range(1, len(months) + 3):
                ws.cell(r_i, j).fill = BAND_FILL
    ws.freeze_panes = ws.cell(HEADER_ROW + 1, 3)
    _fit(ws, min_w=11)
    contents.append(("KPIs", "Every headline metric, last 12 closed months"))

    bva = tools.get_budget_dashboard(wh)
    for r in bva["rows"]:
        r["department"] = "Company" if r["department_id"] == "NONE" else r["department"]
        r["fav_pct"] = r["fav_variance"] / abs(r["budget"]) if r["budget"] else None  # signed like the variance
    _table(wb.create_sheet("Budget vs actual"), "Budget vs actual", f"{bva['month']} · variance signed so favorable is positive · USD",
           bva["rows"], [("department", "Department", None), ("owner", "Owner", None), ("account_name", "Account", None),
                         ("actual", "Actual", USD), ("budget", "Budget", USD), ("fav_variance", "Variance (fav +)", USD),
                         ("fav_pct", "Variance % (fav +)", PCT), ("ytd_fav_variance", "YTD variance (fav +)", USD),
                         ("fy_fav_variance", "Full year vs budget (fav +)", USD), ("direction", "Direction", None)],
           totals=("actual", "budget", "fav_variance", "ytd_fav_variance", "fy_fav_variance"))
    contents.append(("Budget vs actual", "Last closed month by department and account, with year to date and full year"))

    ar = tools.get_receivables_dashboard(wh)
    _table(wb.create_sheet("AR aging"), "Open receivables", "Every open invoice today · USD", ar["rows"],
           [("invoice_ref", "Invoice", None), ("customer_id", "Customer", None), ("segment", "Segment", None),
            ("invoice_date", "Invoice date", None), ("due_date", "Due", None), ("balance", "Balance", USD2),
            ("days_past_due", "Days late", INT), ("aging_bucket", "Age", None), ("recommended_action", "Action", None)],
           totals=("balance",))
    contents.append(("AR aging", "Open invoices with age, due date and the recommended action"))

    fc = wh.query("""select scenario, strftime(month, '%Y-%m') as month, revenue, cogs, opex, ebitda, closing_cash,
                            closing_cash_with_raise
                     from marts.fct_forecast_monthly where is_latest order by scenario, month""")
    _table(wb.create_sheet("Forecast"), "18-month forecast", "By scenario · USD", fc,
           [("scenario", "Scenario", None), ("month", "Month", None), ("revenue", "Revenue", USD), ("cogs", "COGS", USD),
            ("opex", "Opex", USD), ("ebitda", "EBITDA", USD), ("closing_cash", "Cash, no new money", USD),
            ("closing_cash_with_raise", "Cash with planned raise", USD)])
    contents.append(("Forecast", "Driver-based forecast for base, upside and downside"))

    saas = tools.get_saas_metrics(wh, 12)["rows"]
    _table(wb.create_sheet("Unit economics"), "SaaS unit economics", "CAC on trailing 3 months · USD", saas,
           [("month", "Month", None), ("arr", "ARR", USD), ("new_customers", "New customers", INT), ("sm_spend", "S&M spend", USD),
            ("cac", "CAC", USD), ("arpa", "ARPA", USD), ("ltv", "LTV", USD), ("ltv_to_cac", "LTV:CAC", XMULT),
            ("cac_payback_months", "CAC payback (mo)", NUM1), ("revenue_growth_yoy", "Growth YoY", PCT),
            ("ebitda_margin", "EBITDA margin", PCT), ("rule_of_40", "Rule of 40", PCT), ("free_cash_flow", "Free cash flow", USD)])
    contents.append(("Unit economics", "CAC, LTV, payback, Rule of 40, free cash flow"))

    cost = tools.get_cost_behavior(wh, 12)["rows"]
    _table(wb.create_sheet("Cost structure"), "Cost structure and breakeven", "Fixed vs variable costs · USD", cost,
           [("month", "Month", None), ("revenue", "Revenue", USD), ("variable_costs", "Variable costs", USD),
            ("fixed_costs", "Fixed costs", USD), ("contribution_margin", "Contribution margin", USD), ("cm_ratio", "CM %", PCT),
            ("breakeven_revenue", "Breakeven revenue", USD), ("margin_of_safety", "Margin of safety", PCT),
            ("operating_leverage", "Operating leverage", '0.00;[Red](0.00);"–"')])
    contents.append(("Cost structure", "Contribution margin, breakeven revenue and operating leverage"))

    pvm = tools.get_revenue_pvm(wh)
    _table(wb.create_sheet("Price volume mix"), "Revenue bridge: price, volume, mix", f"Usage revenue, {str(pvm['month'])[:7]} vs prior month · USD",
           pvm["rows"], [("product_id", "Product", None), ("revenue_prev", "Prior revenue", USD), ("revenue", "Revenue", USD),
                         ("price_effect", "Price", USD), ("volume_effect", "Volume", USD), ("mix_effect", "Mix", USD), ("revenue_change", "Change", USD)],
           totals=("revenue_prev", "revenue", "price_effect", "volume_effect", "mix_effect", "revenue_change"))
    contents.append(("Price volume mix", "Why usage revenue changed month over month"))

    sens = tools.get_runway_sensitivity(wh)
    cols = list(sens["rows"][0])
    _table(wb.create_sheet("Runway sensitivity"), "Runway sensitivity", "Months until cash runs out with no new money · rows: revenue growth per month, columns: opex change",
           sens["rows"], [(c, "Revenue growth / month" if c == "revenue_growth_monthly" else c.replace("opex", "Opex"),
                           PCT if c == "revenue_growth_monthly" else INT) for c in cols])
    contents.append(("Runway sensitivity", "Runway under different growth and cost scenarios"))

    lrp = tools.get_long_range_plan(wh)["rows"]
    _table(wb.create_sheet("Five-year plan"), "Five-year plan", "From the trailing 12 months · base-case raise included · USD", lrp,
           [("year", "Year", "0"), ("revenue", "Revenue", USD), ("revenue_growth", "Growth", PCT), ("gross_margin_pct", "GM %", PCT),
            ("sales_marketing", "S&M", USD), ("research_development", "R&D", USD), ("general_admin", "G&A", USD),
            ("ebitda", "EBITDA", USD), ("ebitda_margin", "EBITDA %", PCT), ("capex", "Capex", USD),
            ("free_cash_flow", "Free cash flow", USD), ("financing", "Financing", USD), ("closing_cash", "Closing cash", USD)])
    contents.append(("Five-year plan", "Long-range plan: revenue, margins, opex by function, cash"))

    _summary(wb, contents, latest, end)
    for ws in wb.worksheets:
        ws.sheet_view.zoomScale = 100
    wb.active = 0
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--period", choices=["month", "quarter", "year"], default="month")
    p.add_argument("--periods", type=int, default=12)
    a = p.parse_args()
    out = ROOT / "reports" / "finance_workbook.xlsx"
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(build(tools.Warehouse(), a.period, a.periods))
    print(out)


if __name__ == "__main__":
    main()
