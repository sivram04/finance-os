"""One-page board KPI summary for a month (FR-4.4), as Markdown, from fct_kpi_monthly + the metric catalog.

    python -m finance_os.reports.board_pack [--month 2026-09] [--db data/finance_os.duckdb] [--out reports]

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
    "days": lambda v: f"{v:.1f}",
}
SECTIONS = [
    ("Growth", ["revenue", "arr", "nrr", "grr"]),
    ("Customers", ["active_customers", "new_customers", "churned_customers", "logo_churn_rate", "gross_mrr_churn_rate"]),
    ("Margin", ["gross_margin_pct", "cogs"]),
    ("Cash", ["closing_cash", "net_burn", "gross_burn", "runway_months"]),
    ("Receivables", ["dso_days", "cei", "ar_over_60"]),
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
    return "\n".join(out + outlook(con))


def _usd(v):
    return "n/a" if v is None else (f"−${abs(v):,.0f}" if v < 0 else f"${v:,.0f}")


def outlook(con):
    q = lambda sql: con.execute(sql).fetchall()  # noqa: E731
    out = ["## Outlook (driver-based forecast, next 12 months)", "",
           "| Scenario | Revenue | Gross margin | EBITDA | Cash in 12 months | Runway | Cash runs out |",
           "|---|---:|---:|---:|---:|---:|---|"]
    for sc, rev, gm, ebitda, cash12, runway, out_m in q("""
            select scenario, revenue_next_12m, gross_margin_pct_next_12m, ebitda_next_12m, cash_in_12m, runway_months,
                   cash_out_month from marts.fct_scenario_summary
            order by case scenario when 'upside' then 0 when 'base' then 1 else 2 end"""):
        rw = "n/a" if runway is None else f"{runway:.1f} mo"
        out.append(f"| {sc} | {_usd(rev)} | {gm * 100:.1f}% | {_usd(ebitda)} | {_usd(cash12)} | {rw} | "
                   + (f"{out_m:%b %Y} |" if out_m else "not within 18 months |"))
    low = q("select min(closing_cash), min(case when is_below_min_cash then week end) from marts.fct_cash_forecast_13w")[0]
    cov = q("""select rule_id, description, min(month), bool_or(not is_forecast) from marts.fct_treasury_covenants
               where status = 'breach' and month >= (select max(month) from marts.fct_kpi_monthly) group by 1, 2 order by 3""")
    out += ["", "## Cash and liquidity", "",
            f"- Lowest cash in the 13-week forecast: **{_usd(low[0])}**"
            + (f", below the $3M minimum from week {low[1]}." if low[1] else ".")]
    out += [f"- Covenant {r} ({d}): " + ("**breached now**" if now else f"forecast breach from {m:%b %Y}")
            for r, d, m, now in cov] or ["- All covenants and treasury policies pass."]
    out += ["", "## Fundraising scenarios", "",
            "| Scenario | Round | Close | Pre-money | Raise | Price / share | New investors | Founders after | Cash lasts to close |",
            "|---|---|---|---:|---:|---:|---:|---:|---|"]
    for sc, rnd, close, pre, raise_, price, inv, fnd, late in q("""
            select scenario, round_name, close_month, pre_money, raise_amount, price_per_share, new_investor_pct,
                   founders_pct_after, runs_out_before_close from marts.fct_fundraise_scenarios order by scenario"""):
        out.append(f"| {sc} | {rnd} | {close:%b %Y} | {_usd(pre)} | {_usd(raise_)} | ${price:.2f} | {inv * 100:.1f}% | "
                   f"{fnd * 100:.1f}% | " + ("**no: bridge needed**" if late else "yes") + " |")
    alerts = q("select message, recipients from marts.fct_alerts where severity = 'high' order by rule_id")
    out += ["", "## Needs the board's attention", ""]
    out += [f"- {m} *(owner: {r})*" for m, r in alerts[:10]] or ["- Nothing high-severity is open."]
    if len(alerts) > 10:
        out.append(f"- …and {len(alerts) - 10} more (see the Alerts page).")
    return out + [""]


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
