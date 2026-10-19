"""Diligence data room: everything an investor, lender or auditor asks for first, packaged as one zip.

    python -m finance_os.reports.dataroom          # → reports/echo_labs_data_room_<month>.zip

The workbook and board pack in the formats people read; every table behind them as CSV, so numbers can be re-cut;
a README that says what each file is, its source and the as-of date. All of it comes from the warehouse, so it
matches the workspace and the assistant to the cent.
"""
import argparse
import csv
import io
import zipfile
from datetime import date

from finance_os.app import tools
from finance_os.paths import ROOT
from finance_os.reports import workbook


def _csv(rows):
    buf = io.StringIO()
    if rows:
        cols = list(dict.fromkeys(k for r in rows for k in r))
        w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: (", ".join(map(str, v)) if isinstance(v, (list, tuple)) else v) for k, v in r.items()})
    return buf.getvalue().encode("utf-8")


def build(wh):
    month = str(wh.latest_month())[:7]
    q = wh.query
    files = []  # (path, bytes, description)

    files.append(("01_financials/finance_workbook_monthly.xlsx", workbook.build(wh, "month", 12),
                  "Income statement, balance sheet, cash flow (monthly, 12 months), KPIs, budget vs actual, AR, forecast, unit economics, plan"))
    files.append(("01_financials/finance_workbook_quarterly.xlsx", workbook.build(wh, "quarter", 8),
                  "The same workbook by quarter (8 quarters)"))
    fs = tools.get_financial_statements(wh, period="month", periods=24)
    files.append(("01_financials/statements_monthly.csv", _csv(fs["rows"]), "Three statements, 24 months, one column per month"))
    files.append(("01_financials/general_ledger_by_account_month.csv",
                  _csv(q("select strftime(month, '%Y-%m') as month, account_id, account_name, account_type, department_id, debit, credit, natural_amount from marts.fct_gl_monthly order by month, account_id")),
                  "General ledger summarized by account, department and month"))

    board = sorted((ROOT / "reports").glob("*/monthly_board.md"))
    if board:
        files.append(("02_board/board_pack_latest.md", board[-1].read_bytes(), f"Latest board pack ({board[-1].parent.name})"))

    files.append(("03_metrics/kpis_monthly.csv", _csv(q("select strftime(month, '%Y-%m') as month, metric_name, value from marts.fct_kpi_monthly order by month, metric_name")),
                  "Every headline KPI by month (definitions in metric_definitions.csv)"))
    files.append(("03_metrics/metric_definitions.csv", _csv(q("select metric_name, label, unit, formula, owner from seeds.metric_catalog")),
                  "One definition, formula and owner per metric"))
    files.append(("03_metrics/saas_unit_economics.csv", _csv(q("select * from marts.fct_saas_metrics_monthly order by month")),
                  "CAC (S&M and fully burdened), LTV, LTV:CAC, payback, Rule of 40, free cash flow"))
    files.append(("03_metrics/arr_waterfall.csv", _csv(q("select * from marts.fct_growth_efficiency_monthly order by month")),
                  "ARR bridge (new, expansion, reactivation, contraction, churn), quick ratio, burn multiple"))
    files.append(("03_metrics/cohort_retention.csv", _csv(q("select * from marts.fct_cohort_retention order by cohort_month, months_since")),
                  "Logo, net revenue and gross revenue retention by signup cohort"))

    files.append(("04_customers/revenue_by_customer_month.csv",
                  _csv(q("select strftime(month, '%Y-%m') as month, customer_id, revenue, movement from marts.fct_customer_revenue_monthly where month <= (select max(month) from marts.fct_kpi_monthly) order by month, customer_id")),
                  "Recognized revenue by customer and month, with the movement type"))
    files.append(("04_customers/concentration_and_health.csv", _csv(q("select * from marts.fct_customer_health order by revenue_rank")),
                  "Revenue share and rank, usage trend and health per customer"))
    files.append(("04_customers/margin_by_customer.csv", _csv(q("select * from marts.fct_customer_margin_monthly where month = (select max(month) from marts.fct_kpi_monthly)")),
                  "Gross and contribution margin by customer, last closed month"))

    files.append(("05_sales/pipeline.csv", _csv(q("select * from marts.fct_pipeline order by close_date")), "Open pipeline with stage, weighted ARR, close quarter"))
    files.append(("05_sales/bookings.csv", _csv(q("select * from marts.fct_bookings_monthly order by month")), "Won and lost ARR, win rate and sales cycle by month"))

    files.append(("06_capital/cap_table.csv", _csv(q("select * from marts.fct_cap_table order by shares desc")), "Fully diluted cap table"))
    files.append(("06_capital/fundraise_scenarios.csv", _csv(q("select * from marts.fct_fundraise_scenarios")), "Round scenarios: price, dilution, pool top-up, runway"))
    files.append(("06_capital/forecast_by_scenario.csv", _csv(q("select * from marts.fct_forecast_monthly where is_latest order by scenario, month")),
                  "18-month forecast, base / upside / downside, with and without the planned raise"))

    files.append(("07_tax/tax_and_fx_monthly.csv", _csv(q("select * from marts.fct_tax_fx_monthly order by month, currency")),
                  "Billings, tax collected and remittance date, realized and unrealized FX, by currency and regime"))

    files.append(("08_controls/reconciliations.csv", _csv(q("select * from recon.recon_status order by period, check_name")),
                  "Every reconciliation by check and period, with expected vs actual"))
    review = tools.get_close_review(wh)
    files.append(("08_controls/close_flux_analysis.csv", _csv(review["rows"]), f"Flux analysis for the {review['month']} close"))
    files.append(("08_controls/balance_sheet_reconciliations.csv", _csv(review["reconciliations"]), "Balance sheet accounts against their support"))

    files.append(("09_contracts/vendor_contracts.csv", _csv(q("select * from seeds.vendor_contracts")), "Vendor contracts and GPU commitments"))

    lines = [f"# Echo Labs, Inc. · data room", "", f"Books closed through {month}. Generated {date.today():%d %B %Y}.",
             "All figures in USD, from the Finance OS warehouse (the same numbers as the workspace and the board pack).", "",
             "| File | What it is |", "|---|---|"]
    lines += [f"| `{path}` | {desc} |" for path, _, desc in files]
    readme = "\n".join(lines) + "\n"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("00_README.md", readme)
        for path, data, _ in files:
            z.writestr(path, data)
    return buf.getvalue(), month


def main():
    argparse.ArgumentParser().parse_args()
    data, month = build(tools.Warehouse())
    out = ROOT / "reports" / f"echo_labs_data_room_{month}.zip"
    out.write_bytes(data)
    print(out)


if __name__ == "__main__":
    main()
