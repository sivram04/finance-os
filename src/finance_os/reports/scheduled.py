"""Recurring reports (seeds/report_schedule.csv): built from the warehouse, delivered like alerts, kept in reports/.

    python -m finance_os.reports.scheduled            # send whatever is due today (the morning job runs this)
    python -m finance_os.reports.scheduled --report weekly_ar --force   # build and send one now

Cadence: daily; weekly:mon (… weekly:fri); monthly:on_close, sent the first morning a new month has closed in the
books (a month closes when it is billed, on the 1st). Each report goes out once per period: data/reports_log.json
records what was sent. Delivery uses the alert channels (Slack / email / Telegram from .env); with none configured,
the report is only saved to reports/<period>/<report_id>.md (and listed on the Reports page).
"""
import argparse
import csv
import json
from datetime import date, datetime
from pathlib import Path

import duckdb

from finance_os.paths import ROOT, SEEDS

WAREHOUSE = ROOT / "data" / "finance_os.duckdb"
OUT = ROOT / "reports"
LOG = ROOT / "data" / "reports_log.json"
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _usd(v):
    if v is None:
        return "n/a"
    v = float(v)
    return f"−${abs(v):,.0f}" if v < 0 else f"${v:,.0f}"


def _table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join("" if c is None else str(c) for c in r) + " |" for r in rows]
    return out


# ---- the reports ------------------------------------------------------------------------------------------

def daily_cash(con, today):
    q = lambda s: con.execute(s).fetchall()  # noqa: E731
    cash = q("select sum(amount) from staging.stg_erp__journal_lines where account_id = '1000'")[0][0]
    low, week = q("select min(closing_cash), min(case when is_below_min_cash then week end) from marts.fct_cash_forecast_13w")[0]
    cov = q("""select rule_id, description, bool_or(not is_forecast) from marts.fct_treasury_covenants
               where status = 'breach' and month >= (select max(month) from marts.fct_kpi_monthly) group by 1, 2""")
    alerts = q("select severity, message from marts.fct_alerts order by case severity when 'high' then 0 else 1 end limit 8")
    out = [f"# Daily cash and alerts — {today:%a %d %b %Y}", "",
           f"- **Cash today:** {_usd(cash)}",
           f"- **Lowest in the 13-week forecast:** {_usd(low)}" + (f" (below the $3M minimum from week {week})" if week else ""),
           ""]
    out += [f"- Covenant {r}: {d} — " + ("**breached now**" if now else "forecast breach") for r, d, now in cov] or ["- All covenants pass."]
    out += ["", "## Open alerts (top 8)", ""] + [f"- [{s.upper()}] {m}" for s, m in alerts]
    return "\n".join(out)


def weekly_ar(con, today):
    q = lambda s: con.execute(s).fetchall()  # noqa: E731
    aging = q("""select aging_bucket, count(*), sum(balance) from marts.fct_ar_aging_snapshot
                 where snapshot_date = (select max(snapshot_date) from marts.fct_ar_aging_snapshot) group by 1
                 order by case aging_bucket when 'current' then 0 when '1-30' then 1 when '31-60' then 2 when '61-90' then 3 else 4 end""")
    ar = q("select ending_ar, dso_days, cei from marts.fct_ar_monthly where month <= (select max(month) from marts.fct_kpi_monthly) order by month desc limit 1")
    routes = q("select route, count(*), sum(balance) from marts.fct_collections_queue group by 1 order by 3 desc")
    queue = q("""select queue_rank, invoice_ref, customer_id, balance, days_past_due, recommended_action
                 from marts.fct_collections_queue where route = 'manual' order by queue_rank limit 10""")
    disputes = q("select customer_id, invoice_ref, disputed_amount, days_open, note from marts.fct_disputes where status = 'open'")
    e = ar[0] if ar else (None, None, None)
    out = [f"# Weekly AR and collections — week of {today:%d %b %Y}", "",
           f"Last closed month: ending AR {_usd(e[0])}, DSO {e[1]} days, CEI {float(e[2]) * 100:.1f}%." if e[0] is not None else "",
           "", "## Aging today", ""] + _table(["Bucket", "Invoices", "Balance"], [(b, n, _usd(v)) for b, n, v in aging])
    out += ["", "## Who does what", ""] + [f"- {r.replace('_', ' ')}: {n} invoices, {_usd(v)}" for r, n, v in routes]
    out += ["", "## Collections queue (a person follows up)", ""]
    out += _table(["#", "Invoice", "Customer", "Balance", "Days late", "Action"],
                  [(r, i, c, _usd(b), d, a) for r, i, c, b, d, a in queue]) if queue else ["No invoice needs a person to chase."]
    out += ["", "## Open disputes", ""] + ([f"- {c} {i} ({_usd(a)}, open {d} days): {n}" for c, i, a, d, n in disputes] or ["None."])
    return "\n".join(out)


def weekly_flash(con, today):
    q = lambda s, p=None: con.execute(s, p or []).fetchall()  # noqa: E731
    m0 = today.replace(day=1)
    mtd = q("""select sum(u.audio_hours), count(distinct u.customer_id) from staging.stg_synthetic__usage_daily u
               where u.usage_date >= ?""", [m0])[0]
    prev = q("""select sum(audio_hours) from staging.stg_synthetic__usage_daily
                where usage_date >= ? and usage_date < ?""", [date(m0.year - (m0.month == 1), (m0.month - 2) % 12 + 1, 1), m0])[0][0]
    days_in = (today - m0).days or 1
    kpi = dict(q("""select metric_name, value from marts.fct_kpi_monthly
                    where month = (select max(month) from marts.fct_kpi_monthly)"""))
    movers = q("""select customer_id, movement, revenue_change from marts.fct_customer_revenue_monthly
                  where month = (select max(month) from marts.fct_kpi_monthly) and movement in ('new','expansion','contraction','churn')
                  order by abs(revenue_change) desc limit 6""")
    out = [f"# Weekly flash — {today:%d %b %Y}", "",
           f"- **Usage month to date:** {float(mtd[0] or 0):,.0f} audio hours across {mtd[1]} customers "
           f"({float(mtd[0] or 0) / days_in:,.0f}/day vs {float(prev or 0) / 30:,.0f}/day last month)",
           f"- **Last closed month:** revenue {_usd(kpi.get('revenue'))}, ARR {_usd(kpi.get('arr'))}, "
           f"gross margin {float(kpi.get('gross_margin_pct') or 0) * 100:.1f}%, net burn {_usd(kpi.get('net_burn'))}",
           f"- **Cash:** {_usd(kpi.get('closing_cash'))} at month end; runway {float(kpi.get('runway_months') or 0):.1f} months",
           "", "## Biggest revenue movers (last closed month)", ""]
    out += _table(["Customer", "Movement", "Change"], [(c, m, _usd(v)) for c, m, v in movers])
    return "\n".join(out)


def monthly_close(con, today):
    q = lambda s: con.execute(s).fetchall()  # noqa: E731
    month = q("select max(month) from marts.fct_kpi_monthly")[0][0]
    tasks = q(f"select task_id, task, owner, status, open_items from marts.fct_close_status where month = date '{month}' order by due_date, task_id")
    recon = q(f"select check_name, status from recon.recon_status where period = date '{month}' order by check_name")
    rr = q(f"select revenue_adjustment, contract_asset, contract_liability from marts.fct_revenue_rollforward_monthly where month = date '{month}'")
    acc = q(f"select sum(accrued_amount) from marts.fct_accruals_monthly where month = date '{month}'")[0][0]
    bva = q(f"select department_id, account_name, variance, variance_pct from marts.fct_bva_monthly where month = date '{month}' and is_alert")
    out = [f"# Month-end close — {month:%B %Y}", "", "## Checklist", ""]
    out += _table(["#", "Task", "Owner", "Status", "Open items"], tasks)
    out += ["", f"Reconciliations: {sum(s == 'pass' for _, s in recon)} of {len(recon)} pass."]
    out += [f"- {c}: **{s}**" for c, s in recon if s != "pass"]
    if rr:
        out += ["", f"ASC 606 adjustment to book: {_usd(rr[0][0])} (contract asset {_usd(rr[0][1])}, liability {_usd(rr[0][2])})."]
    out += [f"Costs accrued before their invoice arrived: {_usd(acc)}.", "", "## Budget variances to explain", ""]
    out += [f"- {d} {a}: {_usd(v)} ({float(p) * 100:+.1f}%)" for d, a, v, p in bva] or ["None."]
    return "\n".join(out)


def monthly_board(con, today):
    from finance_os.reports.board_pack import build
    return build(con, con.execute("select max(month) from marts.fct_kpi_monthly").fetchone()[0])


REPORTS = {"daily_cash": daily_cash, "weekly_ar": weekly_ar, "weekly_flash": weekly_flash,
           "monthly_close": monthly_close, "monthly_board": monthly_board}


# ---- schedule ---------------------------------------------------------------------------------------------

def schedule():
    with open(SEEDS / "report_schedule.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def period_key(cadence, today, closed_month):
    """The period a report covers; it is sent once per period. None = not due today."""
    if cadence == "daily":
        return today.isoformat()
    if cadence.startswith("weekly:"):
        return f"{today:%G-W%V}" if DAYS[today.weekday()] == cadence.split(":")[1] else None
    if cadence == "monthly:on_close":
        return f"{closed_month:%Y-%m}"
    raise ValueError(cadence)


def run(today=None, only=None, force=False, log=print):
    from finance_os.alerts import send
    from finance_os.ingestion.ap_intake.__main__ import load_dotenv
    load_dotenv(ROOT / ".env")
    today = today or date.today()
    sent = json.loads(LOG.read_text(encoding="utf-8")) if LOG.exists() else {}
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    done = []
    try:
        closed = con.execute("select max(month) from marts.fct_kpi_monthly").fetchone()[0]
        for r in schedule():
            if only and r["report_id"] != only:
                continue
            period = period_key(r["cadence"], today, closed) or (today.isoformat() if force else None)
            if period is None or (not force and sent.get(r["report_id"]) == period):
                continue
            text = REPORTS[r["report_id"]](con, today)
            path = OUT / period / f"{r['report_id']}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"<!-- {r['name']} · for {r['recipients']} -->\n{text}\n", encoding="utf-8")
            channels = send(f"{r['name']} ({period})\n\n{text}")
            sent[r["report_id"]] = period
            done.append(r["report_id"])
            log(f"reports: {r['report_id']} for {period} -> {', '.join(channels) or 'saved only'} ({path.relative_to(ROOT)})")
    finally:
        con.close()
    LOG.write_text(json.dumps(sent, indent=1), encoding="utf-8")
    if not done:
        log("reports: nothing due")
    return done


def list_reports():
    """Every saved report, newest first: [{period, report_id, name, path, saved_at}]."""
    names = {r["report_id"]: r["name"] for r in schedule()}
    out = []
    for path in OUT.glob("*/*.md"):
        if path.stem in names:
            out.append({"period": path.parent.name, "report_id": path.stem, "name": names[path.stem],
                        "saved_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="minutes")})
    return sorted(out, key=lambda r: r["saved_at"], reverse=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--report", choices=sorted(REPORTS))
    p.add_argument("--force", action="store_true", help="build and send even if not due / already sent")
    a = p.parse_args()
    run(only=a.report, force=a.force)


if __name__ == "__main__":
    main()
