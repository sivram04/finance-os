"""One-page board KPI summary for a month (FR-4.4), as Markdown, from fct_kpi_monthly + the metric catalog.

    python scripts/board_pack.py [--month 2026-09] [--db data/finance_os.duckdb] [--out reports]

Every figure comes from the warehouse; nothing is computed here except month-over-month and year-over-year change.
"""
import argparse
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb

FORMATS = {
    "usd": lambda v: f"${v:,.0f}",
    "ratio": lambda v: f"{v * 100:.1f}%",
    "months": lambda v: f"{v:.1f}",
    "count": lambda v: f"{v:,.0f}",
}
SECTIONS = [
    ("Growth", ["revenue", "arr", "nrr", "grr"]),
    ("Margin", ["gross_margin_pct", "cogs"]),
    ("Cash", ["closing_cash", "net_burn", "gross_burn", "runway_months"]),
    ("Team and efficiency", ["headcount", "opex", "arr_per_employee"]),
]


def change(now, then, unit):
    if now is None or then is None or then == 0:
        return "–"
    if unit == "ratio":
        return f"{(now - then) * 100:+.1f} pts"
    return f"{(now - then) / abs(then) * 100:+.1f}%"


def build(con, month: date):
    catalog = {r[0]: r[1:] for r in con.execute(
        "select metric_name, label, unit, formula from seeds.metric_catalog").fetchall()}
    rows = con.execute("""
        select metric_name,
               max(value) filter (where month = $m) as now_,
               max(value) filter (where month = $m - interval 1 month) as prior_month,
               max(value) filter (where month = $m - interval 12 month) as prior_year
        from marts.fct_kpi_monthly
        group by metric_name
    """, {"m": month}).fetchall()
    values = {r[0]: r[1:] for r in rows}
    failing = con.execute("select count(*) from recon.recon_status where status <> 'pass'").fetchone()[0]

    out = [f"# Echo Labs — board KPI summary, {month:%B %Y}", "",
           "Source: `marts.fct_kpi_monthly`. Definitions: `docs/METRIC_CATALOG.md`.",
           f"Reconciliation checks failing: **{failing}**" + (" — figures below are unverified." if failing else "."), ""]
    for title, names in SECTIONS:
        out += [f"## {title}", "", "| Metric | Value | vs. prior month | vs. prior year |", "|---|---:|---:|---:|"]
        for n in names:
            label, unit, _ = catalog[n]
            now, pm, py = values.get(n, (None, None, None))
            shown = FORMATS[unit](Decimal(now)) if now is not None else "n/a"
            out.append(f"| {label} | {shown} | {change(now, pm, unit)} | {change(now, py, unit)} |")
        out.append("")
    return "\n".join(out)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--month", help="YYYY-MM; defaults to the latest month in the warehouse")
    p.add_argument("--db", default="data/finance_os.duckdb")
    p.add_argument("--out", default="reports")
    a = p.parse_args()
    con = duckdb.connect(a.db, read_only=True)
    month = (date.fromisoformat(a.month + "-01") if a.month
             else con.execute("select max(month) from marts.fct_kpi_monthly").fetchone()[0])
    path = Path(a.out) / f"board_pack_{month:%Y-%m}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build(con, month), encoding="utf-8", newline="\n")
    print(path)


if __name__ == "__main__":
    main()
