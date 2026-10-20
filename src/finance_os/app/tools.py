"""Read-only tools the assistant can call (design §9.2, FR-11.1). No free-form SQL: each tool is a fixed,
parameterised query over the marts, recon tables or metric catalog, and every result names its source.

Results are JSON-ready: decimals become floats, dates ISO strings. Long results are cut to MAX_ROWS with a
note, so the model is told it is seeing part of the data rather than guessing.
"""
import contextvars
import datetime as dt
from decimal import Decimal
from pathlib import Path

import duckdb

from finance_os.paths import ROOT

WAREHOUSE = ROOT / "data" / "finance_os.duckdb"
MAX_ROWS = 40


class Warehouse:
    def __init__(self, path: Path = WAREHOUSE):
        self.path = path

    def query(self, sql, params=None):
        con = duckdb.connect(str(self.path), read_only=True)
        try:
            cur = con.execute(sql, params or [])
            cols = [d[0] for d in cur.description]
            return [{c: _jsonable(v) for c, v in zip(cols, row)} for row in cur.fetchall()]
        finally:
            con.close()

    def latest_month(self):
        return self.query("select max(month) as m from marts.fct_kpi_monthly")[0]["m"]


def _jsonable(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    return v


def _month(m, wh):
    """'2026-09' or '2026-09-01' → '2026-09-01'; None → latest closed month. A month that hasn't closed yet (it is
    billed and closed on the 1st of the next month) also gives the latest closed month: monthly views are only
    complete for closed months."""
    latest = str(wh.latest_month())[:10]
    if not m:
        return latest
    m = m if len(m) == 10 else f"{m}-01"
    return min(m, latest)


FULL_ROWS = contextvars.ContextVar("full_rows", default=False)  # set by the workspace API, not the assistant


def _result(rows, source, note=None, **extra):
    cap = len(rows) if FULL_ROWS.get() else MAX_ROWS
    out = {"source": source, "row_count": len(rows), "rows": rows[:cap], **extra}
    if len(rows) > cap:
        out["note"] = f"Showing {MAX_ROWS} of {len(rows)} rows; narrow the filters to see the rest."
    if note:
        out["note"] = (out.get("note", "") + " " + note).strip()
    return out


# ---- tool implementations -------------------------------------------------------------------------

def get_kpis(wh, month=None, metrics=None):
    m = _month(month, wh)
    rows = wh.query("""
        select k.metric_name, c.label, c.unit, k.value, c.version
        from marts.fct_metric_values_monthly k join seeds.metric_catalog c using (metric_name)
        where k.month = ?::date and (? is null or list_contains(?::varchar[], k.metric_name))
        order by k.metric_name""", [m, metrics, metrics])
    unknown = sorted(set(metrics or []) - {r["metric_name"] for r in rows})
    note = f"Unknown metric names: {', '.join(unknown)}. Valid names: {', '.join(METRIC_NAMES)}." if unknown else None
    return _result(rows, "marts.fct_metric_values_monthly (governed metric layer) + seeds.metric_catalog", note=note, month=m)


def get_kpi_trend(wh, metric, start_month=None, end_month=None):
    rows = wh.query("""
        select strftime(month, '%Y-%m') as month, value, source_model from marts.fct_metric_values_monthly
        where metric_name = ? and month >= coalesce(?::date, date '1900-01-01')
          and month <= coalesce(?::date, date '2999-01-01')
        order by month""", [metric, start_month and _month(start_month, wh), end_month and _month(end_month, wh)])
    note = None if rows else f"No data for metric '{metric}'. Valid names: {', '.join(METRIC_NAMES)}."
    return _result(rows, "marts.fct_metric_values_monthly (governed metric layer)", note=note, metric=metric)


def get_metric_definition(wh, metric):
    """The metric's contract: definition, numerator / denominator, inclusions and exclusions, currency treatment,
    period logic, refresh, owner, version, effective date, restatement policy, and its change history."""
    rows = wh.query("select * from seeds.metric_catalog where metric_name = ?", [metric])
    if not rows:
        names = [r["metric_name"] for r in wh.query("select metric_name from seeds.metric_catalog order by 1")]
        return _result([], "seeds.metric_catalog", note=f"Unknown metric. Available: {', '.join(names)}")
    changes = wh.query("select * from seeds.metric_changelog where metric_name = ? order by version", [metric])
    latest = wh.query("""select strftime(max(month), '%Y-%m') as m from marts.fct_metric_values_monthly where metric_name = ?""", [metric])
    return _result(rows, "seeds.metric_catalog, seeds.metric_changelog (docs/METRIC_CATALOG.md)", changelog=changes,
                   latest_value_month=latest[0]["m"] if latest else None)


METRIC_ACCOUNT_TYPE = {"revenue": "revenue", "arr": "revenue", "cogs": "cogs", "gross_margin_pct": "cogs", "opex": "opex",
                       "gross_burn": "opex", "net_burn": "opex"}


def _evidence_drill(wh, low, calls, metrics):
    """Links from an answer to the journal lines behind it: explore_ledger filters for each month, customer, vendor,
    department or metric the answer used. The page opens Explore with these filters."""
    latest = str(wh.latest_month())[:7]
    out, seen = [], set()

    def add(label, args):
        key = tuple(sorted(args.items()))
        if key not in seen and len(out) < 4:
            seen.add(key)
            out.append({"label": label, "args": args})

    for name, args, _ in calls:
        a = args or {}
        if name == "explore_ledger":
            add("Your ledger query", {k: v for k, v in a.items() if v})
            continue
        month = (a.get("month") or "")[:7] or None
        start, end = (a.get("start_month") or "")[:7] or month, (a.get("end_month") or "")[:7] or month
        rng = {"start_month": start or latest, "end_month": end or latest}
        if a.get("customer_id"):
            add(f"Revenue lines for {a['customer_id']}", {"customer_id": a["customer_id"], "account_type": "revenue", "group_by": "month", **({"start_month": start, "end_month": end} if start else {})})
        if a.get("vendor_id"):
            add(f"Ledger lines for {a['vendor_id']}", {"vendor_id": a["vendor_id"], "group_by": "month"})
        if a.get("department"):
            add(f"{a['department']} spend, {rng['start_month']}", {"department": a["department"], "account_type": "opex", "group_by": "account", **rng})
    for m in metrics:
        t = METRIC_ACCOUNT_TYPE.get(m["metric"])
        if t:
            add(f"{t.capitalize()} lines behind {m['label']}, {latest}", {"account_type": t, "start_month": latest, "end_month": latest, "group_by": "account"})
    return out


def answer_evidence(wh, text, calls, unverified):
    """The evidence block under every assistant answer: what was read (sources and filters), which governed metrics
    the answer uses (version, effective date, owner), how fresh the data is, and whether the books reconcile."""
    import json
    low = (text or "").lower()
    catalog = wh.query("select metric_name, label, version, effective_from, owner from seeds.metric_catalog")
    metrics = [{"metric": c["metric_name"], "label": c["label"], "version": c["version"],
                "effective_from": str(c["effective_from"])[:10], "owner": c["owner"]}
               for c in catalog
               if (c["label"] and c["label"].lower() in low) or c["metric_name"].replace("_", " ") in low]
    world = Path(__file__).resolve().parents[3] / "data" / "live" / "world.json"
    live = json.loads(world.read_text(encoding="utf-8")).get("as_of") if world.exists() else None
    recon = wh.query("select count(*) as n from recon.recon_status where status <> 'pass'")[0]["n"]
    return {
        "drill": _evidence_drill(wh, low, calls, metrics),
        "sources": sorted({r.get("source") for _, _, r in calls if isinstance(r, dict) and r.get("source")}),
        "filters": [{"tool": n, "args": a} for n, a, _ in calls if a],
        "metrics": metrics[:12],
        "freshness": {"closed_through": str(wh.latest_month())[:7], "live_through": live},
        "reconciliation": {"failing_checks": recon, "status": "all passing" if not recon else f"{recon} failing period(s)"},
        "numbers_verified": not unverified,
    }


def get_pnl(wh, start_month=None, end_month=None, group_by="rollup"):
    col = {"account": "account_id || ' ' || account_name", "rollup": "rollup", "department": "department_id"}[group_by]
    s, e = _month(start_month, wh), _month(end_month, wh)
    rows = wh.query(f"""
        select account_type, {col} as line, sum(natural_amount) as amount
        from marts.fct_gl_monthly
        where account_type in ('revenue', 'cogs', 'opex') and month between ?::date and ?::date
        group by 1, 2 order by case account_type when 'revenue' then 1 when 'cogs' then 2 else 3 end, amount desc""",
                    [s, e])
    return _result(rows, "marts.fct_gl_monthly", start_month=s, end_month=e, group_by=group_by)


def get_financial_statements(wh, period="month", periods=12, end_month=None):
    """Income statement, balance sheet and cash flow (indirect) from the GL, one column per period. Flows are summed
    over the period; balances are taken at its end. Equity = preferred stock + retained earnings (cumulative net
    income); the balance check is assets − liabilities − equity and must be 0."""
    e = _month(end_month, wh)
    gl = wh.query("""select strftime(month, '%Y-%m') as m, account_id, account_name, account_type, rollup,
                            sum(natural_amount) as amt
                     from marts.fct_gl_monthly where month <= ?::date group by all order by m""", [e])
    months = sorted({r["m"] for r in gl})
    key = {"month": lambda m: m, "quarter": lambda m: f"{m[:4]}-Q{(int(m[5:]) - 1) // 3 + 1}", "year": lambda m: m[:4]}[period]
    accounts = {r["account_id"]: (r["account_name"], r["account_type"], r["rollup"]) for r in gl}
    flow = {}  # (account, month) -> amount
    for r in gl:
        flow[(r["account_id"], r["m"])] = flow.get((r["account_id"], r["m"]), 0) + float(r["amt"] or 0)
    cols = []
    for m in months:
        if not cols or cols[-1][0] != key(m):
            cols.append((key(m), []))
        cols[-1][1].append(m)
    cols = cols[-int(periods):]
    # a quarter or year that isn't over yet is labelled to-date, so a 9-month 2026 isn't read as a full year
    full = {"month": 1, "quarter": 3, "year": 12}[period]
    to_date = {"year": "YTD", "quarter": "QTD"}.get(period)
    cols = [(f"{label} {to_date}" if to_date and len(ms) < full else label, ms) for label, ms in cols]
    first = cols[0][1][0] if cols else None

    def f(acct, ms):  # flow over months
        return sum(flow.get((acct, m), 0) for m in ms)

    def bal(acct, through):  # balance at the end of a month
        return sum(v for (a, m), v in flow.items() if a == acct and m <= through)

    def ni(ms):
        return sum(f(a, ms) * (1 if t == "revenue" else -1) for a, (_, t, _) in accounts.items() if t in ("revenue", "cogs", "opex"))

    def cum_ni(through):
        return sum(ni([m]) for m in months if m <= through)

    by_type = lambda t: sorted(a for a, (_, tt, _) in accounts.items() if tt == t)  # noqa: E731
    rows = []

    def add(sheet, line, style, fn, unit="usd"):
        r = {"sheet": sheet, "line": line, "style": style, "unit": unit}
        for label, ms in cols:
            v = fn(ms)
            r[label] = None if v is None else round(v, 4 if unit == "ratio" else 2)
        rows.append(r)

    IS, BS, CF = "Income statement", "Balance sheet", "Cash flow"
    rev = lambda ms: sum(f(a, ms) for a in by_type("revenue"))  # noqa: E731
    cogs = lambda ms: sum(f(a, ms) for a in by_type("cogs"))  # noqa: E731
    DA = "6600"  # depreciation: below EBITDA, added back in the cash flow
    opex = lambda ms: sum(f(a, ms) for a in by_type("opex") if a != DA)  # noqa: E731
    ebitda = lambda ms: rev(ms) - cogs(ms) - opex(ms)  # noqa: E731
    add(IS, "Revenue", "header", lambda ms: None)
    for a in by_type("revenue"):
        add(IS, accounts[a][0], "item", lambda ms, a=a: f(a, ms))
    add(IS, "Total revenue", "subtotal", rev)
    add(IS, "Cost of revenue", "header", lambda ms: None)
    for a in by_type("cogs"):
        add(IS, accounts[a][0], "item", lambda ms, a=a: f(a, ms))
    add(IS, "Total cost of revenue", "subtotal", cogs)
    add(IS, "Gross profit", "total", lambda ms: rev(ms) - cogs(ms))
    add(IS, "Gross margin", "ratio", lambda ms: (rev(ms) - cogs(ms)) / rev(ms) if rev(ms) else None, "ratio")
    add(IS, "Operating expenses", "header", lambda ms: None)
    for a in by_type("opex"):
        if a != DA:
            add(IS, accounts[a][0], "item", lambda ms, a=a: f(a, ms))
    add(IS, "Total operating expenses", "subtotal", opex)
    add(IS, "EBITDA", "total", ebitda)
    add(IS, "EBITDA margin", "ratio", lambda ms: ebitda(ms) / rev(ms) if rev(ms) else None, "ratio")
    add(IS, "Depreciation", "item", lambda ms: f(DA, ms))
    add(IS, "Operating income (EBIT)", "subtotal", ni)
    add(IS, "Operating margin", "ratio", lambda ms: ni(ms) / rev(ms) if rev(ms) else None, "ratio")
    add(IS, "Net income", "total", ni)

    add(BS, "Assets", "header", lambda ms: None)
    for a in by_type("asset"):
        add(BS, accounts[a][0], "item", lambda ms, a=a: bal(a, ms[-1]))
    assets = lambda ms: sum(bal(a, ms[-1]) for a in by_type("asset"))  # noqa: E731
    add(BS, "Total assets", "total", assets)
    add(BS, "Liabilities", "header", lambda ms: None)
    for a in by_type("liability"):
        add(BS, accounts[a][0], "item", lambda ms, a=a: bal(a, ms[-1]))
    liab = lambda ms: sum(bal(a, ms[-1]) for a in by_type("liability"))  # noqa: E731
    add(BS, "Total liabilities", "subtotal", liab)
    add(BS, "Equity", "header", lambda ms: None)
    for a in by_type("equity"):
        add(BS, accounts[a][0], "item", lambda ms, a=a: bal(a, ms[-1]))
    add(BS, "Retained earnings", "item", lambda ms: cum_ni(ms[-1]))
    equity = lambda ms: sum(bal(a, ms[-1]) for a in by_type("equity")) + cum_ni(ms[-1])  # noqa: E731
    add(BS, "Total equity", "subtotal", equity)
    add(BS, "Total liabilities and equity", "total", lambda ms: liab(ms) + equity(ms))
    add(BS, "Check (should be 0)", "check", lambda ms: assets(ms) - liab(ms) - equity(ms))

    def delta(acct, ms):
        prev = [m for m in months if m < ms[0]]
        return bal(acct, ms[-1]) - (bal(acct, prev[-1]) if prev else 0)

    FIXED = {"1500", "1510"}
    wc_assets = [a for a in by_type("asset") if a != "1000" and a not in FIXED]
    add(CF, "Operating activities", "header", lambda ms: None)
    add(CF, "Net income", "item", ni)
    add(CF, "Depreciation (non-cash, added back)", "item", lambda ms: -delta("1510", ms))
    for a in wc_assets:
        add(CF, f"Change in {accounts[a][0].lower()}", "item", lambda ms, a=a: -delta(a, ms))
    for a in by_type("liability"):
        add(CF, f"Change in {accounts[a][0].lower()}", "item", lambda ms, a=a: delta(a, ms))
    cfo = lambda ms: ni(ms) - delta("1510", ms) - sum(delta(a, ms) for a in wc_assets) + sum(delta(a, ms) for a in by_type("liability"))  # noqa: E731
    add(CF, "Cash from operations", "subtotal", cfo)
    add(CF, "Investing activities", "header", lambda ms: None)
    capex = lambda ms: -delta("1500", ms)  # noqa: E731
    add(CF, "Capital expenditure", "item", capex)
    add(CF, "Cash from investing", "subtotal", capex)
    add(CF, "Free cash flow (operations + capex)", "ratio", lambda ms: cfo(ms) + capex(ms))
    add(CF, "Financing activities", "header", lambda ms: None)
    cff = lambda ms: sum(delta(a, ms) for a in by_type("equity"))  # noqa: E731
    add(CF, "Equity raised", "item", cff)
    add(CF, "Cash from financing", "subtotal", cff)
    add(CF, "Net change in cash", "total", lambda ms: cfo(ms) + capex(ms) + cff(ms))
    add(CF, "Opening cash", "item", lambda ms: bal("1000", [m for m in months if m < ms[0]][-1]) if ms[0] != months[0] else 0)
    add(CF, "Closing cash", "total", lambda ms: bal("1000", ms[-1]))
    # all three statements in full (not capped at MAX_ROWS): a statement missing lines would not add up
    return {"source": "marts.fct_gl_monthly", "row_count": len(rows), "rows": rows, "periods": [c[0] for c in cols],
            "period": period, "end_month": e, "note": f"Closed months through {e[:7]}; first column starts {first}."}


def get_budget_vs_actual(wh, month=None, department=None, alerts_only=False):
    m = _month(month, wh)
    rows = wh.query("""
        select department_id, account_id, account_name, actual, budget, variance, variance_pct,
               ytd_actual, ytd_budget, fy_budget, fy_forecast, fy_forecast_variance, is_alert
        from marts.fct_bva_monthly
        where month = ?::date and (? is null or department_id = ?) and (not ? or is_alert)
        order by abs(variance) desc""", [m, department, department, alerts_only])
    alerts = wh.query("""select alert_id, department_id, account_id, message, route_to
                         from marts.fct_bva_alerts where month = ?::date""", [m])
    return _result(rows, "marts.fct_bva_monthly, marts.fct_bva_alerts", month=m, alerts=alerts)


def get_variance_drivers(wh, alert_id):
    rows = wh.query("""select driver_rank, entry_date, entry_type, memo, customer_id, vendor_id, amount, share_of_actual
                       from marts.fct_bva_drivers where alert_id = ? order by driver_rank""", [alert_id])
    return _result(rows, "marts.fct_bva_drivers", alert_id=alert_id)



PNL_RECON_CHECKS = {  # which reconciliation checks prove the source system ties to this GL account
    "4000": ["gl_revenue_vs_rated_usage", "stripe_invoices_vs_gl_revenue", "usage_events_vs_drivers"],
    "4100": ["project_billing_vs_gl"], "5000": ["vendor_invoice_vs_modeled", "vendor_bill_vs_gl_ap"],
    "5010": ["gcp_export_vs_bill", "vendor_bill_vs_gl_ap"], "5200": ["project_billing_vs_gl"],
    "6000": ["payroll_register_vs_gl", "project_labor_within_payroll"], "6010": ["payroll_register_vs_gl"],
    "6020": ["payroll_register_vs_gl"], "6100": ["gcp_export_vs_bill"],
}
SOURCE_SYSTEM = {"4000": "Stripe invoices (rated usage)", "4100": "Project billing", "5000": "GPU vendor bills (Nimbus)",
                 "5010": "GCP billing export", "6000": "Payroll register", "6010": "Payroll register", "6020": "Payroll register",
                 "6600": "Fixed-asset register (depreciation run)"}


def get_variance_case(wh, alert_id=None, account=None, month=None):
    """The full case file for one budget variance, from source data to the decision the CFO must make:
      1 what happened   actual vs budget for the month, year to date and the full-year forecast
      2 source data     the journal lines behind the actual and the source system they came from
      3 reconciliation  source system → GL → reported actual, with the reconciliation checks for that account
      4 root cause      decomposed into drivers (for usage revenue: the budget's growth assumption vs the MRR
                        bridge - new, expansion, contraction, churn - and the customers behind each; otherwise run
                        rate vs budget, one-offs and concentration), classified as timing, one-off, run-rate or
                        planning gap
      5 owner           the accountable owner and the commentary status (recommendations come from the assistant,
                        reasoned from this evidence, not from templates)
      6 decision        the standard choices for the CFO with their full-year effect"""
    if not alert_id:  # find it: by account (id or name) in the month, else the month's largest variance
        mm = _month(month, wh)
        found = wh.query("""select alert_id from marts.fct_bva_alerts where month = ?::date
                            and (? is null or account_id = ? or lower(account_name) like lower(?))
                            order by abs(variance) desc limit 1""", [mm, account, account, f"%{account}%" if account else None])
        alert_id = found[0]["alert_id"] if found else None
    a = wh.query("select * from marts.fct_bva_alerts where alert_id = ?", [alert_id]) if alert_id else []
    if not a:
        return _result([], "marts.fct_bva_alerts", note=f"Unknown alert {alert_id}. List alerts with get_budget_vs_actual.")
    a = a[0]
    m, acct, dept = str(a["month"])[:10], a["account_id"], a["department_id"]
    line = wh.query("""select * from marts.fct_bva_monthly where month = ?::date and account_id = ? and department_id = ?""", [m, acct, dept])[0]
    is_rev = a["account_type"] == "revenue"
    sign = -1 if is_rev else 1  # journal amounts are debit - credit
    fav = float(a["variance"]) * (1 if is_rev else -1)  # favorable is positive

    # 2 source data: the journal lines behind the actual
    dept_filter = "l.department_id is null" if dept == "NONE" else "l.department_id = ?"
    args = [m, acct] + ([] if dept == "NONE" else [dept])
    lines = wh.query(f"""select e.entry_id, strftime(e.entry_date, '%Y-%m-%d') as entry_date, e.entry_type, e.memo, e.source_ref,
                                l.customer_id, l.vendor_id, l.entity_id, {sign} * l.amount as amount
                         from staging.stg_erp__journal_lines l join staging.stg_erp__journal_entries e using (entry_id)
                         where e.entry_month = ?::date and l.account_id = ? and {dept_filter}
                         order by abs(l.amount) desc""", args)
    gl_total = round(sum(float(x["amount"]) for x in lines), 2)
    by_type = {}
    for x in lines:
        by_type[x["entry_type"]] = by_type.get(x["entry_type"], 0.0) + float(x["amount"])

    # 3 reconciliation chain
    checks = PNL_RECON_CHECKS.get(acct, [])
    recon = wh.query(f"""select check_name, strftime(period, '%Y-%m') as period, entity_id, expected, actual, variance, status, explanation
                         from recon.recon_status where period = ?::date and check_name in ({', '.join('?' * len(checks)) or "''"})
                         order by check_name""", [m] + checks) if checks else []
    budget_src = wh.query("""select sum(amount) as v from staging.stg_erp__budgets where month = ?::date and account_id = ?
                             and coalesce(department_id, 'NONE') = ?""", [m, acct, dept]) if True else []
    chain = [
        {"step": "Source system", "system": SOURCE_SYSTEM.get(acct, "Sub-ledger postings"),
         "amount": next((float(r["expected"]) for r in recon if r["check_name"] != "usage_events_vs_drivers"), None), "status": "pass" if recon and all(r["status"] == "pass" for r in recon) else ("no check" if not recon else "fail"),
         "detail": f"{len(recon)} reconciliation check(s) for this account and period" if recon else "No automated sub-ledger check for this account"},
        {"step": "General ledger", "system": f"{len(lines)} journal line(s) on {acct} {a['account_name']}", "amount": gl_total,
         "status": "pass" if abs(gl_total - float(a["actual"])) < 0.01 else "fail", "detail": "Sum of the journal lines"},
        {"step": "Reported actual", "system": "Budget vs actual (fct_bva_monthly)", "amount": float(a["actual"]),
         "status": "pass" if abs(gl_total - float(a["actual"])) < 0.01 else "fail", "detail": "Ties to the GL to the cent" if abs(gl_total - float(a["actual"])) < 0.01 else f"Off by {gl_total - float(a['actual']):,.2f}"},
        {"step": "Budget", "system": "Approved FY budget (raw_erp.budgets)", "amount": float(budget_src[0]["v"] or 0) if budget_src else None,
         "status": "pass" if budget_src and abs(float(budget_src[0]["v"] or 0) - float(a["budget"])) < 0.01 else "fail", "detail": "Budget as approved, unchanged"},
    ]

    # 4 root cause
    trend = wh.query("""select strftime(month, '%Y-%m') as month, actual, budget from marts.fct_bva_monthly
                        where account_id = ? and department_id = ? and fiscal_year = ? and month <= ?::date order by month""",
                     [acct, dept, line["fiscal_year"], m])
    root, components, customers = {}, [], []
    if acct == "4000":
        fy0 = f"{line['fiscal_year']}-01-01"
        base = wh.query("""select closing_mrr from marts.fct_mrr_bridge_monthly where month = ?::date - interval 1 month""", [fy0])[0]["closing_mrr"]
        b = wh.query("""select sum(new_mrr) as new, sum(expansion_mrr) as expansion, sum(contraction_mrr) as contraction,
                               sum(churned_mrr) as churn, sum(reactivation_mrr) as reactivation
                        from marts.fct_mrr_bridge_monthly where month between ?::date and ?::date""", [fy0, m])[0]
        base, actual = float(base), float(a["actual"])
        budget_growth = float(a["budget"]) - base
        months = int(m[5:7])
        implied = (float(a["budget"]) / base) ** (1 / months) - 1 if base else None
        achieved = (actual / base) ** (1 / months) - 1 if base else None
        components = [{"driver": "Budget assumed growth since the December base", "amount": round(budget_growth, 2)},
                      {"driver": "New customers", "amount": round(float(b["new"] or 0), 2)},
                      {"driver": "Expansion", "amount": round(float(b["expansion"] or 0), 2)},
                      {"driver": "Contraction", "amount": round(float(b["contraction"] or 0), 2)},
                      {"driver": "Churn", "amount": round(float(b["churn"] or 0), 2)},
                      {"driver": "Reactivation", "amount": round(float(b["reactivation"] or 0), 2)}]
        delivered = sum(c["amount"] for c in components[1:])
        other = round(actual - base - delivered, 2)
        if abs(other) >= 0.01:
            components.append({"driver": "Refunds, credits and timing", "amount": other})
        customers = wh.query("""
            with base as (select customer_id, revenue from marts.fct_customer_revenue_monthly where month = ?::date - interval 1 month),
                 now as (select customer_id, revenue from marts.fct_customer_revenue_monthly where month = ?::date)
            select coalesce(n.customer_id, b.customer_id) as customer_id, coalesce(b.revenue, 0) as december, coalesce(n.revenue, 0) as this_month,
                   coalesce(n.revenue, 0) - coalesce(b.revenue, 0) as change,
                   (select string_agg(distinct event_type, ', ') from staging.stg_synthetic__lifecycle_events le
                     where le.customer_id = coalesce(n.customer_id, b.customer_id) and le.event_date between ?::date and last_day(?::date)) as events
            from now n full join base b using (customer_id)
            order by abs(coalesce(n.revenue, 0) - coalesce(b.revenue, 0)) desc limit 8""", [fy0, m, fy0, m]) if wh.query(
            "select 1 from information_schema.tables where table_name = 'stg_synthetic__lifecycle_events'") else []
        biggest_drag = min(components[3:5], key=lambda c: c["amount"])
        root = {"classification": "Planning gap plus customer losses (run-rate, not timing)",
                "summary": (f"The budget grew revenue {implied:.1%} a month from the December base of {_usd_text(base)}; actual grew "
                            f"{achieved:.1%} a month. Customers added {_usd_text(delivered)} since December against "
                            f"{_usd_text(budget_growth)} budgeted: expansion {_usd_text(components[2]['amount'])} and new "
                            f"{_usd_text(components[1]['amount'])} were offset by contraction {_usd_text(components[3]['amount'])} "
                            f"and churn {_usd_text(components[4]['amount'])}. The gap has widened every month since February, "
                            f"so it is run-rate, not timing."),
                "budget_growth_monthly": round(implied, 4) if implied is not None else None,
                "actual_growth_monthly": round(achieved, 4) if achieved is not None else None,
                "biggest_drag": biggest_drag["driver"], "december_base": round(base, 2),
                "budget_growth": round(budget_growth, 2), "delivered_growth": round(delivered, 2),
                "growth_shortfall": round(delivered - budget_growth, 2)}
    else:
        prior = wh.query("""select avg(actual) as v from marts.fct_bva_monthly where account_id = ? and department_id = ?
                            and month between ?::date - interval 3 month and ?::date - interval 1 month""", [acct, dept, m, m])[0]["v"]
        prior = float(prior or 0)
        bud = float(a["budget"])
        act = float(a["actual"])
        top_share = max((abs(float(x["amount"])) for x in lines), default=0) / abs(act) if act else 0
        if bud == 0:
            cls = "Planning gap: no budget for a recurring cost"
        elif prior and abs(act - prior) / abs(prior) < 0.1:
            cls = "Run-rate: the cost has run at this level for three months; the budget is too low"
        elif top_share > 0.5:
            cls = "One-off: one entry is most of the month"
        else:
            cls = "Volume or rate change this month"
        components = [{"driver": "Budget", "amount": round(bud, 2)}, {"driver": "Trailing 3-month average actual", "amount": round(prior, 2)},
                      {"driver": "This month actual", "amount": round(act, 2)}]
        components += [{"driver": f"By entry type: {k}", "amount": round(v, 2)} for k, v in sorted(by_type.items(), key=lambda kv: -abs(kv[1]))]
        root = {"classification": cls,
                "summary": (f"Actual {_usd_text(act)} vs budget {_usd_text(bud)}; the last three months averaged {_usd_text(prior)}. "
                            f"Largest single entry is {top_share:.0%} of the month."),
                "biggest_drag": None}

    # 5 owner (recommended actions are not templated: the assistant reasons them from the evidence on request)
    owner = a["route_to"]
    fy_var = float(a["fy_forecast_variance"] or 0)

    # 6 decision options and any recorded decision
    options = [
        {"option": "Accept and re-forecast", "effect": f"Full-year forecast moves to the run rate ({_usd_text(fy_var)} vs budget); no budget change.",
         "fy_impact": round(fy_var, 2)},
        {"option": "Hold the budget and fund a corrective plan", "effect": "Keep the target; owners commit to actions and dates; re-test next close.",
         "fy_impact": 0.0},
        {"option": "Re-budget (board approval)", "effect": "Reset the budget to a new approved number; variance reporting restarts from it.",
         "fy_impact": round(fy_var, 2)},
    ]
    if acct == "4000":
        options.append({"option": "Cut spend to protect EBITDA", "effect": "Offset part of the revenue gap with a hiring slowdown or opex cut (see Scenarios: hiring freeze).",
                        "fy_impact": None})
    case = {"alert_id": alert_id, "month": m[:7], "department": a["department_name"], "account": f"{acct} {a['account_name']}",
            "account_type": a["account_type"], "actual": float(a["actual"]), "budget": float(a["budget"]),
            "variance_favorable": round(fav, 2), "variance_pct": a["variance_pct"], "ytd_actual": line["ytd_actual"],
            "ytd_budget": line["ytd_budget"], "fy_budget": line["fy_budget"], "fy_forecast": line["fy_forecast"],
            "fy_forecast_variance": fy_var, "message": a["message"], "owner": owner,
            "commentary_status": a["commentary_status"], "commentary_draft": a["commentary_draft"]}
    return _result(lines[:40], "marts.fct_bva_alerts, fct_bva_monthly, stg_erp__journal_lines, recon.recon_status, "
                   "stg_erp__budgets, fct_mrr_bridge_monthly, fct_customer_revenue_monthly",
                   case=case, trend=trend, source_lines_total=gl_total, source_line_count=len(lines),
                   by_entry_type=[{"entry_type": k, "amount": round(v, 2)} for k, v in by_type.items()],
                   reconciliation_chain=chain, reconciliation_checks=recon, root_cause=root, root_cause_components=components,
                   customers=customers, owner=owner, decision_options=options,
                   note="Favorable variance is positive for revenue and costs alike.")

def get_unit_economics(wh, month=None, customer_id=None, below_floor_only=False):
    m = _month(month, wh)
    rows = wh.query("""
        select customer_id, segment, revenue, cogs, gross_margin, gross_margin_pct, gross_margin_floor_pct,
               contribution_margin, contribution_margin_pct, is_below_floor, margin_rank_asc
        from marts.fct_customer_margin_monthly
        where month = ?::date and (? is null or customer_id = ?) and (not ? or is_below_floor)
        order by margin_rank_asc""", [m, customer_id, customer_id, below_floor_only])
    by_product = wh.query("""
        select product_id, sum(revenue) as revenue, sum(cogs) as cogs,
               round(sum(gross_margin) / nullif(sum(revenue), 0), 4) as gross_margin_pct,
               round(sum(cogs) / nullif(sum(audio_hours), 0), 4) as cost_to_serve_per_hour
        from marts.fct_unit_economics_monthly where month = ?::date group by 1 order by 1""", [m])
    return _result(rows, "marts.fct_customer_margin_monthly, marts.fct_unit_economics_monthly", month=m,
                   by_product=by_product)


def get_revenue_movements(wh, month=None, customer_id=None):
    m = _month(month, wh)
    if customer_id:
        rows = wh.query("""select strftime(month, '%Y-%m') as month, revenue, revenue_change, movement, is_usage_spike
                           from marts.fct_customer_revenue_monthly where customer_id = ? order by month""", [customer_id])
        return _result(rows, "marts.fct_customer_revenue_monthly", customer_id=customer_id)
    bridge = wh.query("select * from marts.fct_mrr_bridge_monthly where month = ?::date", [m])
    movers = wh.query("""select customer_id, revenue, prior_revenue, revenue_change, movement
                         from marts.fct_customer_revenue_monthly
                         where month = ?::date and movement in ('churn', 'new', 'reactivation', 'expansion', 'contraction')
                         order by abs(revenue_change) desc limit 15""", [m])
    return _result(bridge, "marts.fct_mrr_bridge_monthly, marts.fct_customer_revenue_monthly", month=m,
                   biggest_movers=movers)


def get_tech_spend(wh, month=None, group_by="vendor"):
    m = _month(month, wh)
    col = {"vendor": "vendor_id", "team": "team", "category": "category", "model": "coalesce(model, '(none)')"}[group_by]
    rows = wh.query(f"""select {col} as {group_by}, sum(cost) as cost from marts.fct_tech_spend_daily
                        where spend_month = ?::date group by 1 order by cost desc""", [m])
    tagging = wh.query("select * from marts.fct_tagging_coverage_monthly where month = ?::date", [m])
    return _result(rows, "marts.fct_tech_spend_daily, marts.fct_tagging_coverage_monthly", month=m, tagging=tagging)


def get_gpu_capacity_and_forecast(wh):
    capacity = wh.query("""select strftime(month, '%Y-%m') as month, vendor_id, gpu_type, used_hours, committed_hours,
                                  commit_utilization_pct, shortfall_cost
                           from marts.fct_gpu_capacity_monthly where committed_hours is not null order by month""")
    forecast = wh.query("""select strftime(forecast_month, '%Y-%m') as month, vendor_id, line_type, gpu_type,
                                  monthly_growth, forecast_amount from marts.fct_spend_forecast order by 1, 2, 3""")
    contracts = wh.query("select * from marts.fct_vendor_contracts")
    return _result(capacity, "marts.fct_gpu_capacity_monthly, marts.fct_spend_forecast, marts.fct_vendor_contracts",
                   forecast=forecast, vendor_contracts=contracts)


def get_projects(wh, project_id=None):
    rows = wh.query("""
        select project_id, project_name, project_type, customer_id, contract_value, budget, actual_to_date,
               open_commitments, etc, eac, variance_at_completion, eac_pct_of_budget, pct_complete,
               earned_to_date, billed_to_date, unbilled, deferred, cap_used_pct, is_cap_alert, is_over_budget
        from marts.fct_project_financials
        where month = (select max(month) from marts.fct_kpi_monthly) and (? is null or project_id = ?)
        order by project_id""", [project_id, project_id])
    exceptions = wh.query("""select exception_type, project_id, reference_id, amount, detail from marts.fct_project_exceptions
                             where ? is null or project_id = ?""", [project_id, project_id])
    return _result(rows, "marts.fct_project_financials, marts.fct_project_exceptions", exceptions=exceptions)


def get_contract_funding(wh, contract_id=None, project_id=None):
    rows = wh.query("""select f.contract_id, p.project_id, p.project_name, k.contract_type, f.clin_id, f.ceiling, f.funded,
                              f.billed_to_date, f.unbilled, f.funding_remaining, f.funding_used_pct,
                              f.is_funding_alert_75, f.is_funding_alert_90
                       from marts.fct_contract_funding f
                       join staging.stg_projects__contracts k using (contract_id)
                       join staging.stg_projects__projects p using (contract_id)
                       where f.month = (select max(month) from marts.fct_kpi_monthly)
                         and (? is null or f.contract_id = ?) and (? is null or p.project_id = ?)
                       order by f.contract_id, f.clin_id""", [contract_id, contract_id, project_id, project_id])
    note = "Latest month only. clin_id 'TOTAL' is the whole contract."
    if not rows:
        ids = wh.query("""select contract_id, project_id, contract_type from staging.stg_projects__projects
                          join staging.stg_projects__contracts using (contract_id) order by 1""")
        note += " Nothing matched; valid contracts: " + ", ".join(
            f"{r['contract_id']} ({r['project_id']}, {r['contract_type']})" for r in ids)
    return _result(rows, "marts.fct_contract_funding", note=note)


def get_billing_status(wh):
    status = wh.query("select * from marts.fct_project_billing_status order by project_id")
    run = wh.query("select * from marts.fct_billing_run order by project_id, item_type")
    exceptions = wh.query("select * from marts.fct_billing_exceptions")
    return _result(status, "marts.fct_project_billing_status, marts.fct_billing_run, marts.fct_billing_exceptions",
                   next_billing_run=run, validation_exceptions=exceptions)


def get_ar_aging(wh, customer_id=None):
    rows = wh.query("""
        select aging_bucket, count(*) as invoices, sum(balance) as balance
        from marts.fct_ar_aging_snapshot
        where snapshot_date = (select max(snapshot_date) from marts.fct_ar_aging_snapshot)
          and (? is null or customer_id = ?)
        group by 1 order by case aging_bucket when 'current' then 0 when '1-30' then 1 when '31-60' then 2
                                              when '61-90' then 3 else 4 end""", [customer_id, customer_id])
    monthly = wh.query("""select strftime(month, '%Y-%m') as month, ending_ar, ar_over_60, dso_days, cei
                          from marts.fct_ar_monthly where month <= (select max(month) from marts.fct_kpi_monthly)
                          order by month desc limit 6""")
    late = wh.query("select * from marts.fct_customer_payment_behavior where is_chronic_late")
    return _result(rows, "marts.fct_ar_aging_snapshot, marts.fct_ar_monthly, marts.fct_customer_payment_behavior",
                   customer_id=customer_id, recent_months=monthly, chronic_late_payers=late)


def get_collections_queue(wh, limit=10):
    """The manual work queue (worth a person's time), invoices on hold, and what is handled without anyone:
    card dunning and balances under the chase threshold."""
    rows = wh.query("""select queue_rank, invoice_ref, customer_id, segment, balance, days_past_due, recommended_action,
                              reminder_tone
                       from marts.fct_collections_queue where route = 'manual' order by queue_rank limit ?""", [limit])
    holds = wh.query("""select invoice_ref, customer_id, balance, recommended_action from marts.fct_collections_queue
                        where route = 'on_hold'""")
    routes = wh.query("""select route, count(*) as invoices, sum(balance) as balance from marts.fct_collections_queue
                         group by route order by balance desc""")
    return _result(rows, "marts.fct_collections_queue, seeds.ar_policy", on_hold=holds, by_route=routes,
                   note="Card (self-serve) invoices are retried automatically (dunning); balances under the segment's "
                        "chase threshold roll into the next statement. Neither is a task for a person.")


def get_ar_exceptions(wh):
    cash = wh.query("select * from marts.fct_cash_application_exceptions")
    disputes = wh.query("select * from marts.fct_disputes")
    return _result(cash, "marts.fct_cash_application_exceptions, marts.fct_disputes", disputes=disputes)


def get_ap_review_queue(wh):
    rows = wh.query("""select doc_file, any_value(vendor_id) as vendor_id, any_value(vendor_invoice_number) as invoice_number,
                              any_value(total) as total, list(reason order by reason) as reasons,
                              list(detail order by reason) as details
                       from marts.fct_ap_review_queue group by doc_file order by doc_file""")
    summary = wh.query("select route, count(*) as documents from marts.fct_ap_documents group by 1")
    return _result(rows, "marts.fct_ap_review_queue, marts.fct_ap_documents", documents_needing_review=len(rows),
                   routing=summary, note="One row per document; a document can have several reasons.")


def get_reconciliation_status(wh, failing_only=False):
    rows = wh.query("""select check_name, count(*) as periods, count(*) filter (where status = 'pass') as passing,
                              count(*) filter (where status <> 'pass') as failing
                       from recon.recon_status group by 1 order by 1""")
    failures = wh.query("select * from recon.recon_status where status <> 'pass' order by check_name, period")
    if failing_only:
        rows = [r for r in rows if r["failing"]]
    return _result(rows, "recon.recon_status", failures=failures, all_passing=not failures)


def get_attention_items(wh):
    """Everything currently flagged, across all modules, as one list (for "what needs attention?" and the
    workspace's Needs-you cards). Each item says which page it belongs to."""
    q = wh.query
    m = wh.latest_month()
    items = []

    def add(area, page, severity, title, detail, entity=None):
        items.append({"area": area, "page": page, "severity": severity, "title": title, "detail": detail, "entity": entity})

    for r in q("""select * from marts.fct_project_financials
                  where month = (select max(month) from marts.fct_kpi_monthly)
                    and (is_over_budget or is_cap_alert or unbilled > 0)"""):
        if r["is_over_budget"]:
            add("Projects", "projects", "high", f"{r['project_id']} over budget",
                f"EAC is {r['eac_pct_of_budget']:.1%} of budget ({r['variance_at_completion']:,.2f} at completion)", r["project_id"])
        if r["is_cap_alert"]:
            add("Projects", "projects", "medium", f"{r['project_id']} near its T&M cap",
                f"{r['cap_used_pct']:.1%} of cap used", r["project_id"])
    for r in q("""select contract_id, funding_used_pct, is_funding_alert_90 from marts.fct_contract_funding
                  where month = (select max(month) from marts.fct_kpi_monthly) and clin_id = 'TOTAL'
                    and is_funding_alert_75"""):
        add("Projects", "projects", "high" if r["is_funding_alert_90"] else "medium", f"{r['contract_id']} funding notice",
            f"{r['funding_used_pct']:.1%} of funded amount used (Limitation of Funds threshold 75%)", r["contract_id"])
    for r in q("select * from marts.fct_project_exceptions"):
        add("Projects", "projects", "medium", f"{r['project_id']}: {r['exception_type'].replace('_', ' ')}", r["detail"], r["reference_id"])
    for r in q("select * from marts.fct_billing_exceptions"):
        add("Billing", "billing", "high", f"{r['project_id']}: {r['exception_type'].replace('_', ' ')}", r["detail"], r["invoice_id"])
    for r in q("select * from marts.fct_billing_run where is_unbilled_alert"):
        add("Billing", "billing", "high", f"{r['project_id']}: unbilled {r['days_unbilled']} days",
            f"{r['item_type']} {r['reference']} for {r['amount']:,.2f} not invoiced", r["project_id"])
    for r in q("select * from marts.fct_bva_alerts where month = ?::date", [m]):
        who = r["account_name"] if r["department_id"] == "NONE" else f"{r['department_name']} {r['account_name']}"
        add("Budget", "budget", "medium", f"{who} vs. budget", r["message"], r["alert_id"])
    for r in q("select * from marts.fct_customer_margin_monthly where month = ?::date and is_below_floor", [m]):
        add("Unit economics", "revenue", "medium", f"{r['customer_id']} below margin floor",
            f"gross margin {r['gross_margin_pct']:.1%} vs. floor {r['gross_margin_floor_pct']:.1%}", r["customer_id"])
    for r in q("select * from marts.fct_cash_application_exceptions"):
        add("AR", "ar", "high", f"{r['customer_id']}: {r['exception_type'].replace('_', ' ')}", r["detail"], r["reference_id"])
    for r in q("select * from marts.fct_disputes where status = 'open'"):
        add("AR", "ar", "medium", f"{r['customer_id']} dispute open {r['days_open']} days", r["note"], r["invoice_ref"])
    for r in q("""select doc_file, any_value(vendor_invoice_number) as number, list(reason order by reason) as reasons,
                         string_agg(detail, '; ' order by reason) as details
                  from marts.fct_ap_review_queue group by doc_file order by doc_file"""):
        add("AP", "ap", "medium", f"Vendor bill {r['number'] or r['doc_file']}: "
            + ", ".join(x.replace('_', ' ') for x in r["reasons"]), r["details"], r["doc_file"])
    for r in q("select * from marts.fct_vendor_contracts where is_renewal_due"):
        add("Tech spend", "spend", "medium", f"{r['vendor_name']} contract renewal",
            f"ends {r['end_date']} ({r['days_to_end']} days); notice period {r['renewal_notice_days']} days", r["contract_id"])
    for r in q("""select rule_id, description, min(month) as first_month, bool_or(not is_forecast) as now
                  from marts.fct_treasury_covenants where status = 'breach'
                    and month >= (select max(month) from marts.fct_treasury_covenants where not is_forecast)
                  group by 1, 2"""):
        add("Treasury", "treasury", "high",
            f"Covenant {r['rule_id']} " + ("breached now" if r["now"] else f"breaches from {str(r['first_month'])[:7]}"),
            r["description"], r["rule_id"])
    for r in q("""select min(week) as week, min(closing_cash) as low from marts.fct_cash_forecast_13w
                  where is_below_min_cash having count(*) > 0"""):
        add("Treasury", "treasury", "high", f"Cash falls below the minimum in week {r['week']}",
            f"lowest point in 13 weeks: {r['low']:,.2f}", "MIN-CASH")
    for r in q("select scenario, forecast_cash_before_close from marts.fct_fundraise_scenarios where runs_out_before_close"):
        add("Capital", "capital", "high", f"Cash runs out before the {r['scenario']} round closes",
            f"forecast cash before close {r['forecast_cash_before_close']:,.2f}", r["scenario"])
    for r in q("select * from recon.recon_status where status <> 'pass'"):
        add("Trust", "trust", "high", f"Reconciliation failing: {r['check_name']}", r["explanation"], r["entity_id"])
    order = {"high": 0, "medium": 1}
    # within a severity, business urgency: running out of cash first, then trust in the numbers, then money owed
    urgency = {"Treasury": 0, "Capital": 1, "Trust": 2, "Billing": 3, "AR": 4, "Projects": 5, "Budget": 6,
               "Unit economics": 7, "AP": 8, "Tech spend": 9}
    items.sort(key=lambda i: (order[i["severity"]], urgency.get(i["area"], 99)))
    counts = {}
    for i in items:
        counts[i["area"]] = counts.get(i["area"], 0) + 1
    return _result(items, "all marts (projects, billing, BvA, margins, AR, AP, vendors, treasury, capital, recon)", month=m, counts_by_area=counts)


# ---- FP&A, treasury, close, pricing, capital, tax/FX ----------------------------------------------

def get_forecast(wh, scenario="base"):
    """The rolling forecast for a scenario from the driver engine (the same engine behind the stress test, runway
    sensitivity and forecast snapshots), with every scenario's summary."""
    base = _stress_base(wh)
    out = _engine_scenario(wh, scenario, base)
    rows = [{"month": r["month"], "revenue": r["revenue"], "cogs": r["cogs"],
             "gross_margin_pct": round(1 - r["cogs"] / r["revenue"], 4) if r["revenue"] else None,
             "payroll": r["payroll"], "other_opex": r["other_opex"], "opex": round(r["payroll"] + r["other_opex"], 2),
             "ebitda": r["ebitda"], "arr": r["arr"], "new_arr_booked": r["new_arr_booked"], "closing_cash": r["cash_no_raise"],
             "financing_to_date": round(r["cash"] - r["cash_no_raise"], 2), "closing_cash_with_raise": r["cash"]} for r in out["rows"]]
    return _result(rows, "finance_os.fpa.project (driver engine) from fct_gl_monthly, fct_cash_monthly, fct_mrr_bridge_monthly, "
                         "fct_pipeline, fct_bookings_monthly, hiring plan; levers in seeds/scenario_levers.csv",
                   scenario=scenario, scenarios=scenario_summaries(wh, base), levers=out["levers"],
                   note="One engine for every forward-looking number. Runway = months until projected cash goes below "
                        f"zero (looked for over {out['summary']['runway_horizon']} months; null = not within it).")


SNAPSHOTS = Path(__file__).resolve().parents[3] / "data" / "live" / "forecast_snapshots.jsonl"


def save_forecast_snapshot(wh, path=SNAPSHOTS):
    """Append today's scenario forecasts (one line per scenario and month) to the snapshot log; run by the daily job."""
    import json
    base = _stress_base(wh)
    today = dt.date.today().isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if f'"snapshot_date": "{today}"' in existing:
        return 0
    n = 0
    with open(path, "a", encoding="utf-8") as f:
        for sc in SCENARIO_ORDER:
            out = _engine_scenario(wh, sc, base)
            sm = _scenario_summary(sc, out)
            for r in out["rows"]:
                f.write(json.dumps({"snapshot_date": today, "as_of_month": base["start_month"], "scenario": sc, "month": r["month"],
                                    "revenue": r["revenue"], "ebitda": r["ebitda"], "cash": r["cash_no_raise"],
                                    "runway_months": sm["runway_months"]}) + "\n")
                n += 1
    return n


def get_forecast_changes(wh, scenario="base"):
    """How the forecast moved: this close's forecast vs the forecast re-run as of the previous close (same engine,
    same levers, only the data changed), month by month, with the change explained by starting point. Plus the
    stored daily snapshots, if any, for intra-month drift."""
    import json
    cur_base = _stress_base(wh)
    prev_month = str(wh.query("select max(month) as m from marts.fct_kpi_monthly where month < ?::date",
                              [_month(None, wh)])[0]["m"])[:10]
    prev_base = _stress_base(wh, prev_month)
    cur, prev = _engine_scenario(wh, scenario, cur_base), _engine_scenario(wh, scenario, prev_base)
    pm = {r["month"]: r for r in prev["rows"]}
    rows = [{"month": r["month"], "revenue": r["revenue"], "prior_revenue": pm.get(r["month"], {}).get("revenue"),
             "revenue_change": round(r["revenue"] - pm[r["month"]]["revenue"], 2) if r["month"] in pm else None,
             "cash": r["cash_no_raise"], "prior_cash": pm.get(r["month"], {}).get("cash_no_raise"),
             "cash_change": round(r["cash_no_raise"] - pm[r["month"]]["cash_no_raise"], 2) if r["month"] in pm else None}
            for r in cur["rows"]]
    c, p = _scenario_summary(scenario, cur), _scenario_summary(scenario, prev)
    starting = [{"driver": k, "now": round(cur_base[k], 4), "prior_close": round(prev_base[k], 4), "change": round(cur_base[k] - prev_base[k], 4)}
                for k in ("cash", "mrr", "services", "cogs_pct", "existing_net_monthly", "self_serve_new_mrr", "bookings_arr_monthly", "payroll_now")]
    snaps = []
    if SNAPSHOTS.exists():
        for line in SNAPSHOTS.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r["scenario"] == scenario:
                snaps.append(r)
    by_date = {}
    for r in snaps:
        d = by_date.setdefault(r["snapshot_date"], {"snapshot_date": r["snapshot_date"], "as_of_month": r["as_of_month"],
                                                     "runway_months": r["runway_months"], "revenue_next_12m": 0.0, "n": 0})
        if d["n"] < 12:
            d["revenue_next_12m"] += r["revenue"]
            d["n"] += 1
    return _result(rows, "finance_os.fpa.project as of this close and the previous close; data/live/forecast_snapshots.jsonl",
                   scenario=scenario, as_of=cur_base["start_month"], prior_as_of=prev_base["start_month"],
                   summary={"now": c, "prior_close": p,
                            "revenue_next_12m_change": round(c["revenue_next_12m"] - p["revenue_next_12m"], 2),
                            "changes": {k: round(c[k] - p[k], 4) for k in c
                                        if isinstance(c.get(k), (int, float)) and isinstance(p.get(k), (int, float))}},
                   starting_point=starting, snapshots=[{k: v for k, v in d.items() if k != "n"} for d in sorted(by_date.values(), key=lambda x: x["snapshot_date"])],
                   note="Same engine and levers at both closes, so every change comes from the data: the starting point "
                        "table shows what moved.")


def get_forecast_error_by_driver(wh, versions=5, horizon=3):
    """Forecast error explained by driver, not hidden in totals. For each of the last `versions` closes, the driver
    engine is re-run as of that close (base levers, no new money) and each of the next `horizon` months is compared
    with what actually closed, split into:
      revenue    existing customers (retention / expansion driver), new customers (pipeline and bookings driver), services
      cost       cost-of-revenue volume (forecast cost rate x revenue miss) and rate (cost per revenue dollar moved)
      opex       payroll (hiring plan) and other opex
    Error = forecast - actual (positive = forecast too high); EBITDA error = revenue error - cost errors."""
    from finance_os import fpa
    closes = [str(r["m"])[:10] for r in wh.query("""select distinct month as m from marts.fct_kpi_monthly
                                                   where month <= ?::date order by 1 desc""", [_month(None, wh)])]
    latest = closes[0]
    rows = []
    for as_of in closes[1:int(versions) + 1]:
        base = _stress_base(wh, as_of)
        out = fpa.project(base, {"opex_growth_monthly": _scenario_levers(wh, "base", with_raise=False).get("opex_growth_monthly")}, int(horizon))
        for k, f in enumerate(out["rows"], 1):
            m = f"{f['month']}-01"
            if m > latest:
                break
            a = wh.query("""
                with known as (select distinct customer_id from marts.fct_customer_revenue_monthly where month <= ?::date and revenue > 0),
                usage as (
                    select sum(case when k.customer_id is not null then r.revenue else 0 end) as existing_usage,
                           sum(case when k.customer_id is null then r.revenue else 0 end) as new_usage
                    from marts.fct_customer_revenue_monthly r left join known k using (customer_id) where r.month = ?::date),
                gl as (
                    select sum(case when account_id = '4100' then natural_amount else 0 end) as services,
                           sum(case when account_type = 'revenue' then natural_amount else 0 end) as revenue,
                           sum(case when account_type = 'cogs' then natural_amount else 0 end) as cogs,
                           sum(case when account_id in ('6000', '6010', '6020') then natural_amount else 0 end) as payroll,
                           sum(case when account_type = 'opex' and account_id not in ('6000', '6010', '6020', '6600') then natural_amount else 0 end) as other_opex
                    from marts.fct_gl_monthly where month = ?::date)
                select * from usage cross join gl""", [as_of, m, m])[0]
            a = {k2: float(v or 0) for k2, v in a.items()}
            # usage actuals tie to GL usage revenue; anything not on a customer (timing, refunds) goes to existing
            a["existing_usage"] += (a["revenue"] - a["services"]) - (a["existing_usage"] + a["new_usage"])
            f_rate = f["cogs"] / f["revenue"] if f["revenue"] else 0
            a_rate = a["cogs"] / a["revenue"] if a["revenue"] else 0
            rev_err = f["revenue"] - a["revenue"]
            row = {"as_of": as_of[:7], "month": f["month"], "months_ahead": k,
                   "existing_customers": round(f["existing_usage"] - a["existing_usage"], 2),
                   "new_customers": round(f["new_usage"] - a["new_usage"], 2),
                   "services": round(f["services"] - a["services"], 2),
                   "revenue": round(rev_err, 2),
                   "cost_volume": round(f_rate * rev_err, 2),
                   "cost_rate": round((f_rate - a_rate) * a["revenue"], 2),
                   "payroll": round(f["payroll"] - a["payroll"], 2),
                   "other_opex": round(f["other_opex"] - a["other_opex"], 2),
                   "actual_revenue": round(a["revenue"], 2)}
            row["ebitda"] = round(row["revenue"] - row["cost_volume"] - row["cost_rate"] - row["payroll"] - row["other_opex"], 2)
            row["revenue_error_pct"] = round(rev_err / a["revenue"], 4) if a["revenue"] else None
            rows.append(row)
    drivers = ["existing_customers", "new_customers", "services", "cost_volume", "cost_rate", "payroll", "other_opex"]
    summary = []
    for d in drivers + ["revenue", "ebitda"]:
        vals = [r[d] for r in rows]
        if vals:
            summary.append({"driver": d, "bias": round(sum(vals) / len(vals), 2), "avg_abs_error": round(sum(abs(v) for v in vals) / len(vals), 2),
                            "share_of_abs_ebitda_error": None})
    tot = sum(x["avg_abs_error"] for x in summary if x["driver"] in drivers) or 1
    for x in summary:
        if x["driver"] in drivers:
            x["share_of_abs_ebitda_error"] = round(x["avg_abs_error"] / tot, 4)
    biggest = max((x for x in summary if x["driver"] in drivers), key=lambda x: x["avg_abs_error"], default=None)
    return _result(rows, "finance_os.fpa.project re-run as of each close vs fct_customer_revenue_monthly and fct_gl_monthly",
                   summary=summary, biggest_driver=biggest["driver"] if biggest else None, versions=int(versions), horizon=int(horizon),
                   note="Error = forecast - actual (positive = forecast too high). Pipeline as of an earlier close is rebuilt "
                        "approximately (deals that closed later counted at even odds).")

def get_forecast_accuracy(wh):
    rows = wh.query("""select line, months_ahead, count(*) as n, avg(error_pct) as avg_error_pct,
                              avg(abs(error_pct)) as avg_abs_error_pct
                       from marts.fct_forecast_accuracy group by 1, 2 order by 1, 2""")
    return _result(rows, "marts.fct_forecast_accuracy", note="error = forecast - actual; positive means the forecast was too high.")


def get_headcount_plan(wh, scenario="base"):
    rows = wh.query("""select strftime(month, '%Y-%m') as month, sum(headcount) as headcount, sum(hires_in_month) as hires,
                              sum(payroll_cost) as payroll_cost
                       from marts.fct_headcount_plan_monthly where scenario = ? group by month order by month""", [scenario])
    roles = wh.query("""select role_id, department_id, title, status, strftime(start_month, '%Y-%m') as start_month,
                               annual_salary, monthly_loaded_cost
                        from intermediate.int_planned_hires where scenario = ? order by start_month""", [scenario])
    wf = wh.query("""select strftime(month, '%Y-%m') as month, sum(plan_headcount) as plan_headcount,
                            sum(expected_headcount) as expected_headcount, sum(backfill_hires) as backfill_hires,
                            sum(plan_payroll) as plan_payroll, sum(expected_payroll) as expected_payroll,
                            sum(merit_uplift) as merit_uplift, sum(recruiting_cost) as recruiting_cost,
                            sum(equipment_cost) as equipment_cost, sum(expected_people_cost) as expected_people_cost,
                            sum(variance_to_plan) as variance_to_plan
                     from marts.fct_workforce_plan_monthly group by month order by month""")
    depts = wh.query("""select department_id, attrition_rate, measured_attrition, plan_headcount, expected_headcount,
                               plan_payroll, expected_people_cost, variance_to_plan
                        from marts.fct_workforce_plan_monthly
                        where month = (select max(month) from marts.fct_workforce_plan_monthly where month <= (
                            select min(month) + interval 11 month from marts.fct_workforce_plan_monthly))
                        order by department_id""")
    twelve = wf[:12]
    summary = {k: round(sum(float(r[k] or 0) for r in twelve), 2) for k in
               ("plan_payroll", "expected_people_cost", "merit_uplift", "recruiting_cost", "equipment_cost", "variance_to_plan")}
    extra = wh.query("""select sum(promotion_cost) as promotion_cost, sum(equity_employer_cost) as equity_employer_cost
                        from marts.fct_workforce_employee_monthly
                        where month < (select min(month) from marts.fct_workforce_employee_monthly) + interval 12 month""")[0]
    summary["promotion_cost"] = round(float(extra["promotion_cost"] or 0), 2)
    summary["equity_employer_cost"] = round(float(extra["equity_employer_cost"] or 0), 2)
    summary["expected_people_cost_all_in"] = round(summary["expected_people_cost"] + summary["promotion_cost"] + summary["equity_employer_cost"], 2)
    employees = wh.query("""with yr as (select * from marts.fct_workforce_employee_monthly
                                        where month < (select min(month) from marts.fct_workforce_employee_monthly) + interval 12 month)
                            select employee_id, employee_name, department_id, title, kind,
                                   min(probability) as stay_or_fill_probability, max(annual_salary) as salary_after_review,
                                   sum(expected_loaded_cost) as expected_cost_12m, sum(promotion_cost) as promotion_cost_12m,
                                   sum(equity_employer_cost) as equity_employer_cost_12m
                            from yr group by 1, 2, 3, 4, 5 order by department_id, kind, expected_cost_12m desc""")
    return _result(rows, "marts.fct_headcount_plan_monthly, fct_workforce_plan_monthly, seeds.hiring_plan, "
                         "seeds.workforce_policy, seeds.hire_probability", scenario=scenario, planned_roles=roles,
                   workforce=wf, workforce_by_department=depts, workforce_next_12m=summary, employees=employees,
                   note="Workforce = the base plan adjusted for hiring probability and slippage by req status, attrition "
                        "(measured or benchmark, whichever is higher) with backfill lag, merit at the April review, and "
                        "recruiting and equipment cost per hire. Employees: each person and open role with retention or fill "
                        "probability, merit plus expected promotion raises, and employer tax on vesting equity.")


def get_budget_build(wh):
    rows = wh.query("select * from marts.fct_budget_build order by line desc, department_id")
    totals = wh.query("""select line, sum(bottom_up) as bottom_up, sum(top_down) as top_down, sum(gap) as gap
                         from marts.fct_budget_build group by line order by line desc""")
    return _result(rows, "marts.fct_budget_build, seeds.planning_targets", totals_by_line=totals,
                   note="bottom_up = department plans; top_down = board targets; positive opex gap = asks exceed the ceiling.")


def get_shared_cost_allocation(wh, month=None):
    m = _month(month, wh)
    rows = wh.query("""select department_id, headcount, headcount_share, pool, allocated_amount
                       from marts.fct_shared_cost_allocation_monthly where month = ?::date order by pool, department_id""", [m])
    return _result(rows, "marts.fct_shared_cost_allocation_monthly", month=m)


def get_working_capital(wh):
    rows = wh.query("""select strftime(month, '%Y-%m') as month, ar_balance, ap_balance, net_working_capital, dso_days,
                              dpo_days, cash_conversion_cycle_days
                       from marts.fct_working_capital_monthly order by month desc limit 12""")
    return _result(rows, "marts.fct_working_capital_monthly")


def get_revenue_recognition(wh, month=None):
    m = _month(month, wh)
    roll = wh.query("""select strftime(month, '%Y-%m') as month, opening_net_deferred, billings, asc606_revenue,
                              closing_net_deferred, contract_asset, contract_liability, gl_revenue, revenue_adjustment
                       from marts.fct_revenue_rollforward_monthly order by month desc limit 6""")
    detail = wh.query("""select obligation, project_id, customer_id, billed, asc606_revenue, adjustment_needed,
                                contract_asset, contract_liability
                         from marts.fct_revenue_schedule_monthly where month = ?::date and obligation <> 'usage'
                         order by abs(adjustment_needed) desc""", [m])
    return _result(roll, "marts.fct_revenue_rollforward_monthly, marts.fct_revenue_schedule_monthly", month=m,
                   project_detail=detail, note="Usage revenue is recognized as billed; projects follow ASC 606 progress.")


def get_cash_forecast(wh):
    weeks = wh.query("select * from marts.fct_cash_forecast_13w order by week")
    position = wh.query("select * from marts.fct_cash_position")
    covenants = wh.query("""select rule_id, description, strftime(min(month), '%Y-%m') as first_breach_month,
                                   bool_or(not is_forecast) as breached_in_actuals
                            from marts.fct_treasury_covenants where status = 'breach' group by 1, 2 order by 3""")
    low = min(weeks, key=lambda w: w["closing_cash"]) if weeks else None
    return _result(weeks, "marts.fct_cash_forecast_13w, marts.fct_cash_position, marts.fct_treasury_covenants",
                   cash_by_account=position, covenant_breaches=covenants,
                   lowest_point=low and {"week": low["week"], "week_start": low["week_start"], "closing_cash": low["closing_cash"]})


def get_payment_runs(wh):
    rows = wh.query("select * from marts.fct_payment_run_proposal order by payment_run_date, priority, bill_ref")
    runs = wh.query("""select payment_run_date, count(*) as bills, sum(amount) as amount_due,
                              sum(discount_captured) as discount_captured, sum(amount_to_pay) as amount_to_pay
                       from marts.fct_payment_run_proposal group by 1 order by 1""")
    return _result(rows, "marts.fct_payment_run_proposal", totals_by_run=runs, note="Proposal only; nothing is paid.")


def get_close_status(wh, month=None):
    m = _month(month, wh)
    rows = wh.query("""select task_id, workday, due_date, owner, task, status, open_items
                       from marts.fct_close_status where month = ?::date order by due_date, task_id""", [m])
    accruals = wh.query("select vendor_id, bill_id, accrued_amount, true_up from marts.fct_accruals_monthly where month = ?::date", [m])
    prepaids = wh.query("""select prepaid_id, vendor, amortization, closing_balance
                           from marts.fct_prepaid_schedule where month = ?::date""", [m])
    return _result(rows, "marts.fct_close_status, marts.fct_accruals_monthly, marts.fct_prepaid_schedule", month=m,
                   accruals=accruals, prepaid_amortization=prepaids)


def get_pricing_analysis(wh):
    sims = wh.query("select * from marts.fct_price_simulation order by delta_gross_margin desc")
    leakage = wh.query("""select segment, sum(discount_amount) as discount_amount, sum(list_revenue) as list_revenue,
                                 count(*) filter (where is_over_policy) as over_policy,
                                 count(*) filter (where is_near_tier_cliff) as near_tier_cliff
                          from marts.fct_discount_leakage
                          where month > (select max(month) from marts.fct_kpi_monthly) - interval 12 month
                          group by 1 order by 2 desc""")
    return _result(sims, "marts.fct_price_simulation, marts.fct_discount_leakage", discounts_last_12m=leakage)


def get_cap_table_and_fundraise(wh):
    cap = wh.query("select * from marts.fct_cap_table order by shares desc")
    rounds = wh.query("select * from marts.fct_fundraise_scenarios order by scenario")
    return _result(cap, "marts.fct_cap_table, marts.fct_fundraise_scenarios", fundraise_scenarios=rounds)


def get_tax_and_fx(wh, month=None):
    m = _month(month, wh)
    rows = wh.query("select * from marts.fct_tax_fx_monthly where month = ?::date order by billings_usd desc", [m])
    totals = wh.query("""select currency, sum(billings_usd) as billings_usd, sum(tax_collected_usd) as tax_collected_usd,
                                sum(realized_fx) as realized_fx, sum(unrealized_fx_on_open_ar) as unrealized_fx
                         from marts.fct_tax_fx_monthly group by 1 order by 2 desc""")
    grand = wh.query("""select sum(billings_usd) as billings_usd, sum(tax_collected_usd) as tax_collected_usd,
                               sum(realized_fx) as realized_fx, sum(unrealized_fx_on_open_ar) as unrealized_fx
                        from marts.fct_tax_fx_monthly""")
    return _result(rows, "marts.fct_tax_fx_monthly, marts.fct_invoice_tax_fx", month=m, all_time_by_currency=totals,
                   all_time_total=grand)


def get_commissions(wh, rep_id=None, month=None):
    m = _month(month, wh)
    rows = wh.query("""select * from marts.fct_commission_statement_monthly
                       where month = ?::date and (? is null or rep_id = ?) order by rep_id""", [m, rep_id, rep_id])
    ytd = wh.query("""select rep_id, rep_name, sum(commission_total) as commission_ytd, max(quota_attainment_pct) as attainment
                      from marts.fct_commission_statement_monthly
                      where extract(year from month) = extract(year from ?::date) and month <= ?::date
                      group by 1, 2 order by 1""", [m, m])
    credits = wh.query("""select rep_id, customer_id, credit_type, billed_revenue, credited_arr from marts.int_sales_credits
                          where month = ?::date and (? is null or rep_id = ?) order by abs(credited_arr) desc""", [m, rep_id, rep_id])
    return _result(rows, "marts.fct_commission_statement_monthly, marts.int_sales_credits", month=m,
                   year_to_date=ytd, credits=credits,
                   note="Credits come from billed revenue above each account's previous peak month (x12 = ARR).")


def price_deal(wh, customer, lines, discount_pct=0, term_months=12, monthly_commit=0, payment_terms_days=30, sla="standard",
               unlimited_usage=False, prepaid_credits=False, free_months=0, custom_terms=None):
    from finance_os import dealdesk
    ev = dealdesk.evaluate(wh, {"customer": customer, "lines": lines, "discount_pct": discount_pct,
                                "term_months": term_months, "monthly_commit": monthly_commit, "payment_terms_days": payment_terms_days,
                                "sla": sla, "unlimited_usage": unlimited_usage, "prepaid_credits": prepaid_credits,
                                "free_months": free_months, "custom_terms": custom_terms})
    if ev.get("error"):
        return _result([], "deal desk", note=ev["error"])
    return _result(ev["lines"], "deal desk (seeds.deal_guardrails, seeds.deal_policy, seeds.margin_floors, "
                   "marts.fct_unit_economics_monthly)", **{k: v for k, v in ev.items() if k != "lines"},
                   note="Read-only pricing check; submit_deal records it and routes it for approval.")


# ---- drill-downs: one customer, vendor or project in full -----------------------------------------------

def get_customer_detail(wh, customer_id):
    c = wh.query("select * from marts.dim_customer where customer_id = ?", [customer_id])
    if not c:
        return _result([], "marts.dim_customer", note=f"No customer {customer_id}.")
    revenue = wh.query("""select strftime(m.month, '%Y-%m') as month, m.revenue, m.gross_margin_pct, m.is_below_floor, r.movement
                          from marts.fct_customer_margin_monthly m
                          left join marts.fct_customer_revenue_monthly r using (month, customer_id)
                          where m.customer_id = ? order by m.month""", [customer_id])
    invoices = wh.query("""select invoice_ref, invoice_type, invoice_date, due_date, amount, balance, status, days_past_due,
                                  days_paid_late, is_disputed
                           from marts.fct_ar_invoices where customer_id = ? order by invoice_date desc""", [customer_id])
    payments = wh.query("""select payment_id, received_date, amount, remittance_ref, applied_ref
                           from staging.stg_erp__customer_payments where customer_id = ? order by received_date desc""",
                        [customer_id])
    events = wh.query("""select event_date, event_type, multiplier, reason, source from staging.stg_synthetic__lifecycle_events
                         where customer_id = ? order by event_date desc""", [customer_id])
    projects = wh.query("select project_id, project_name, project_type, contract_value from marts.dim_project where customer_id = ?",
                        [customer_id])
    alerts = wh.query("select rule_id, severity, message from marts.fct_alerts where entity_id = ? or message like ?",
                      [customer_id, f"%{customer_id}%"])
    totals = wh.query("""select sum(amount) as billed, sum(balance) filter (where status = 'open') as open_balance,
                                avg(days_to_pay) filter (where status = 'paid') as avg_days_to_pay
                         from marts.fct_ar_invoices where customer_id = ?""", [customer_id])
    return _result(revenue, "marts.dim_customer, fct_customer_margin_monthly, fct_ar_invoices, customer payments, lifecycle",
                   customer=c[0], totals=totals[0], invoices=invoices, payments=payments, lifecycle=events,
                   projects=projects, alerts=alerts)


def get_vendor_detail(wh, vendor_id):
    bills = wh.query("""select bill_id, service_month, bill_date, total_amount, vendor_invoice_number
                        from staging.stg_erp__vendor_bills where vendor_id = ? order by bill_date desc""", [vendor_id])
    gl = wh.query("""select e.entry_date, e.entry_type, e.memo, e.source_ref, sum(l.debit) as debit, sum(l.credit) as credit
                     from staging.stg_erp__journal_lines l join staging.stg_erp__journal_entries e using (entry_id)
                     where l.vendor_id = ? and l.account_id = '2000' group by all order by e.entry_date desc""", [vendor_id])
    docs = wh.query("""select doc_file, vendor_invoice_number, invoice_date, total, route, issues
                       from marts.fct_ap_documents where vendor_id = ? or lower(vendor_name) like ? order by invoice_date desc""",
                    [vendor_id, f"%{vendor_id.lower()}%"])
    contract = wh.query("select * from marts.fct_vendor_contracts where vendor_id = ?", [vendor_id])
    open_ap = wh.query("""select sum(-l.amount) as open_ap from staging.stg_erp__journal_lines l
                          where l.vendor_id = ? and l.account_id = '2000'""", [vendor_id])
    return _result(bills, "staging.stg_erp__vendor_bills, journal lines (AP 2000), marts.fct_ap_documents, fct_vendor_contracts",
                   vendor_id=vendor_id, open_ap=open_ap[0]["open_ap"], ap_activity=gl, documents=docs, contract=contract)


def get_project_detail(wh, project_id):
    p = wh.query("select * from marts.dim_project where project_id = ?", [project_id])
    if not p:
        hint = " That looks like a customer ID: use get_customer_detail." if project_id[:3] in ("SS-", "MM-", "EN-", "FD-") else ""
        return _result([], "marts.dim_project", note=f"No project {project_id}.{hint}")
    monthly = wh.query("""select strftime(month, '%Y-%m') as month, budget, actual_to_date, eac, pct_complete, earned_to_date,
                                 billed_to_date, unbilled, deferred
                          from marts.fct_project_financials where project_id = ? and month <= ?::date
                          order by month""", [project_id, str(wh.latest_month())[:10]])  # closed months only
    invoices = wh.query("""select invoice_ref, invoice_date, amount, balance, status, is_disputed from marts.fct_ar_invoices
                           where project_id = ? order by invoice_date desc""", [project_id])
    exceptions = wh.query("select * from marts.fct_project_exceptions where project_id = ?", [project_id])
    return _result(monthly, "marts.dim_project, fct_project_financials, fct_ar_invoices, fct_project_exceptions",
                   project=p[0], invoices=invoices, exceptions=exceptions)


# ---- registry: name → (function, description, JSON-schema parameters) -----------------------------

# ---- FP&A: unit economics, cost behaviour, price/volume/mix, long-range plan, sensitivity, business cases --------

def get_saas_metrics(wh, months=12):
    rows = wh.query("""select strftime(month, '%Y-%m') as month, revenue, arr, sm_spend, new_customers, cac, cac_burdened, arpa,
                              monthly_logo_churn, ltv, ltv_to_cac, ltv_to_cac_burdened, cac_payback_months, cac_payback_burdened_months, revenue_growth_yoy, ebitda_margin,
                              rule_of_40, free_cash_flow, fcf_margin
                       from marts.fct_saas_metrics_monthly order by month desc limit ?""", [int(months)])
    return _result(rows[::-1], "marts.fct_saas_metrics_monthly",
                   note="CAC = S&M spend / new customers (trailing 3 months); burdened CAC adds Sales' share of G&A "
                        "overhead by headcount; LTV = ARPA × gross margin / monthly churn; "
                        "Rule of 40 = YoY revenue growth + EBITDA margin.")


def get_cost_behavior(wh, months=12):
    rows = wh.query("""select strftime(month, '%Y-%m') as month, revenue, variable_costs, fixed_costs, contribution_margin,
                              cm_ratio, operating_income, breakeven_revenue, margin_of_safety, operating_leverage
                       from marts.fct_cost_behavior_monthly order by month desc limit ?""", [int(months)])
    accounts = wh.query("""select b.account_id, a.account_name, b.behavior, b.variable_share, b.note
                           from seeds.cost_behavior b join seeds.gl_accounts a using (account_id) order by 1""")
    return _result(rows[::-1], "marts.fct_cost_behavior_monthly, seeds.cost_behavior", accounts=accounts)


def get_revenue_pvm(wh, month=None):
    m = _month(month, wh)
    rows = wh.query("""select product_id, audio_hours_prev, audio_hours, revenue_prev, revenue, revenue_change,
                              price_effect, volume_effect, mix_effect
                       from marts.fct_revenue_pvm_monthly where month = ?::date order by revenue desc""", [m])
    total = {k: sum(float(r[k] or 0) for r in rows) for k in ("revenue_change", "price_effect", "volume_effect", "mix_effect")}
    return _result(rows, "marts.fct_revenue_pvm_monthly", month=m, total=total,
                   note="Usage revenue vs the month before. price + volume + mix = change.")


def get_long_range_plan(wh):
    rows = wh.query("select * from marts.fct_long_range_plan order by year")
    return _result(rows, "marts.fct_long_range_plan, seeds.lrp_assumptions",
                   note="Starts from the trailing 12 closed months; assumptions in seeds/lrp_assumptions.csv.")


def _latest_unit_economics(wh):
    r = wh.query("""select arpa, monthly_logo_churn from marts.fct_saas_metrics_monthly
                    where arpa is not null order by month desc limit 1""")[0]
    k = {x["metric_name"]: x["value"] for x in wh.query(
        "select metric_name, value from marts.fct_kpi_monthly where month = (select max(month) from marts.fct_kpi_monthly)")}
    return float(r["arpa"]), float(r["monthly_logo_churn"] or 0.02), k


def get_runway_sensitivity(wh):
    """Months of runway (no new money) by NRR change (rows) and other-opex change (columns), from the driver engine
    on the base scenario: the same runway definition as the forecast and the stress test."""
    from finance_os import fpa
    base = _stress_base(wh)
    lv0 = _scenario_levers(wh, "base", with_raise=False)
    table = []
    for nrr in [-0.40, -0.30, -0.20, -0.10, 0.0]:
        row = {"nrr_change": nrr}
        for o in [0.0, 0.25, 0.50, 1.00]:
            sm = fpa.project(base, {**lv0, "nrr_pts": nrr, "opex_pct": o}, 24)["summary"]
            row[f"opex {o:+.0%}"] = sm["runway_months"] if sm["runway_months"] is not None else f"{fpa.RUNWAY_HORIZON}+"
        table.append(row)
    return _result(table, "finance_os.fpa.project (driver engine), base scenario levers",
                   base={"cash": base["cash"], "mrr": round(base["mrr"], 2), "cogs_pct": round(base["cogs_pct"], 4),
                         "existing_net_monthly": round(base["existing_net_monthly"], 4)},
                   note="Months until cash runs out with no new funding, by NRR change (rows, annual points) and "
                        f"other-opex change (columns). '{fpa.RUNWAY_HORIZON}+' = not within five years.")


def evaluate_business_case(wh, investment, annual_inflows, discount_rate=None, annual_costs=None, name="Business case"):
    from finance_os import fpa
    out = fpa.business_case(investment, annual_inflows, discount_rate or company_wacc(wh), annual_costs, name)
    return {"source": "finance_os.fpa.business_case", **out}


def _new_customer_arpa(wh):
    """What a newly won customer actually pays: average monthly revenue in months 2-4 after signup, for customers
    won in the last 18 months (month 1 is partial). The company-wide ARPA is dominated by a few enterprise accounts
    and would overstate what a campaign brings in."""
    r = wh.query("""with n as (select customer_id, month as m0 from marts.fct_customer_revenue_monthly
                               where movement = 'new' and month > (select max(month) from marts.fct_kpi_monthly) - interval 18 month)
                    select avg(r.revenue) as arpa from n join marts.fct_customer_revenue_monthly r
                      on r.customer_id = n.customer_id and r.month between n.m0 + interval 1 month and n.m0 + interval 3 month""")
    return float(r[0]["arpa"]) if r and r[0]["arpa"] is not None else None


def evaluate_marketing_campaign(wh, spend, new_customers, years=3, discount_rate=None):
    from finance_os import fpa
    arpa_all, churn, k = _latest_unit_economics(wh)
    arpa = _new_customer_arpa(wh) or arpa_all
    out = fpa.campaign_case(spend, new_customers, arpa, float(k["gross_margin_pct"]), churn, years,
                            discount_rate or company_wacc(wh))
    out["assumptions"]["arpa_basis"] = "new customers' average monthly revenue in months 2-4 after signup (last 18 months)"
    return {"source": "finance_os.fpa.campaign_case + marts.fct_customer_revenue_monthly, fct_saas_metrics_monthly", **out}


# ---- Executive view: scorecard with context, what changed and why, growth efficiency, cohorts, health, pipeline ----

# (metric, label, unit, higher_is_better, source): the scorecard a VP reads first
SCORECARD = [
    ("revenue", "Revenue (month)", "usd", True, "kpi"), ("arr", "ARR", "usd", True, "kpi"),
    ("net_new_arr", "Net new ARR", "usd", True, "growth"), ("gross_margin_pct", "Gross margin", "ratio", True, "kpi"),
    ("nrr", "Net revenue retention", "ratio", True, "kpi"), ("logo_churn_rate", "Logo churn (month)", "ratio", False, "kpi"),
    ("net_burn", "Net burn", "usd", False, "kpi"), ("burn_multiple", "Burn multiple", "ratio", False, "growth"),
    ("closing_cash", "Cash (month end)", "usd", True, "kpi"), ("runway_months", "Runway (months)", "months", True, "kpi"),
    ("rule_of_40", "Rule of 40", "ratio", True, "saas"), ("cac_payback_months", "CAC payback", "months", False, "saas"),
]


def _series(wh):
    """{metric: {month: value}} for every scorecard metric, from the three marts that hold them."""
    out = {}
    for r in wh.query("select strftime(month, '%Y-%m') as m, metric_name, value from marts.fct_kpi_monthly"):
        out.setdefault(r["metric_name"], {})[r["m"]] = r["value"]
    for r in wh.query("select strftime(month, '%Y-%m') as m, net_new_arr, burn_multiple, quick_ratio from marts.fct_growth_efficiency_monthly"):
        for k in ("net_new_arr", "burn_multiple", "quick_ratio"):
            out.setdefault(k, {})[r["m"]] = r[k]
    for r in wh.query("select strftime(month, '%Y-%m') as m, rule_of_40, cac_payback_months, ltv_to_cac from marts.fct_saas_metrics_monthly"):
        for k in ("rule_of_40", "cac_payback_months", "ltv_to_cac"):
            out.setdefault(k, {})[r["m"]] = r[k]
    return out


def _budget(wh, m):
    rows = wh.query("""select a.account_type, sum(b.budget) as budget from marts.fct_bva_monthly b
                       join seeds.gl_accounts a using (account_id) where b.month = ?::date group by 1""", [m])
    by = {r["account_type"]: float(r["budget"] or 0) for r in rows}
    rev, cogs = by.get("revenue"), by.get("cogs")
    return {"revenue": rev, "gross_margin_pct": (rev - cogs) / rev if rev and cogs is not None else None}


def _shift(month, n):
    y, mo = int(month[:4]), int(month[5:7]) - 1 + n
    return f"{y + mo // 12:04d}-{mo % 12 + 1:02d}"


def get_kpi_scorecard(wh, month=None):
    m = _month(month, wh)[:7]
    series = _series(wh)
    bench = {r["metric_name"]: r for r in wh.query("select * from seeds.metric_benchmarks")}
    budget = _budget(wh, m + "-01")
    rows = []
    for key, label, unit, higher, _src in SCORECARD:
        s = series.get(key, {})
        v, prev, ly = s.get(m), s.get(_shift(m, -1)), s.get(_shift(m, -12))
        f = lambda x: None if x is None else float(x)  # noqa: E731
        v, prev, ly = f(v), f(prev), f(ly)
        b = bench.get(key)
        status = None
        if v is not None and b:
            good, med = float(b["good"]), float(b["median"])
            better = (lambda a, c: a >= c) if higher else (lambda a, c: a <= c)
            status = "good" if better(v, good) else "ok" if better(v, med) else "bad"
        rows.append({
            "metric": key, "label": label, "unit": unit, "higher_is_better": higher, "value": v,
            "prior": prev, "change": None if v is None or prev is None else v - prev,
            "change_pct": None if v is None or not prev else (v - prev) / abs(prev),
            "last_year": ly, "yoy_pct": None if v is None or not ly else (v - ly) / abs(ly),
            "budget": budget.get(key), "vs_budget_pct": None if v is None or not budget.get(key) else (v - budget[key]) / abs(budget[key]),
            "benchmark_good": b and float(b["good"]), "benchmark_median": b and float(b["median"]),
            "benchmark_source": b and b["source"], "status": status,
            "spark": [f(s.get(_shift(m, -i))) for i in range(11, -1, -1)],
        })
    return _result(rows, "marts.fct_kpi_monthly, fct_growth_efficiency_monthly, fct_saas_metrics_monthly, fct_bva_monthly, "
                         "seeds.metric_benchmarks", month=m,
                   note="status compares to the benchmark: good = at or past 'good', ok = past the median, bad = below it.")


def _usd_text(v):
    v = float(v or 0)
    return ("-" if v < 0 else "") + (f"${abs(v) / 1e6:,.2f}M" if abs(v) >= 1e6 else f"${abs(v) / 1e3:,.1f}K" if abs(v) >= 1e3 else f"${abs(v):,.0f}")


def _pct_text(v, signed=True):
    return "n/a" if v is None else (f"{v * 100:+.1f}%" if signed else f"{v * 100:.1f}%")


def get_month_summary(wh, month=None):
    """What changed this month and why, in sentences built from the warehouse (no model writes these numbers)."""
    m = _month(month, wh)
    mm, prev = m[:7], _shift(m[:7], -1) + "-01"
    card = {r["metric"]: r for r in get_kpi_scorecard(wh, m)["rows"]}
    figures = []  # every number the sentences quote, raw, so the assistant's number check can verify them

    def _usd(v):
        figures.append(float(v or 0))
        return _usd_text(v)

    def _pct(v, signed=True):
        if v is not None:
            figures.append(float(v))
        return _pct_text(v, signed)
    sections = []

    rev = card["revenue"]
    pvm = get_revenue_pvm(wh, m)["total"]
    movers = wh.query("""select customer_id, movement, revenue_change from marts.fct_customer_revenue_monthly
                         where month = ?::date order by abs(revenue_change) desc limit 3""", [m])
    b = [f"Revenue {_usd(rev['value'])}, {_pct(rev['change_pct'])} vs last month"
         + (f" and {_pct(rev['vs_budget_pct'])} vs budget" if rev["vs_budget_pct"] is not None else "")
         + (f"; {_pct(rev['yoy_pct'])} year on year." if rev["yoy_pct"] is not None else "."),
         f"Usage revenue moved {_usd(pvm['revenue_change'])}: volume {_usd(pvm['volume_effect'])}, price {_usd(pvm['price_effect'])}, "
         f"mix {_usd(pvm['mix_effect'])}.",
         "Biggest customer moves: " + "; ".join(f"{r['customer_id']} {r['movement']} {_usd(r['revenue_change'])}" for r in movers) + "."]
    behind_plan = rev["vs_budget_pct"] is not None and rev["vs_budget_pct"] < -0.10
    sections.append({"title": "Revenue", "status": "bad" if behind_plan or (rev["change"] or 0) < 0 else "good", "bullets": b})

    gm = card["gross_margin_pct"]
    unit = wh.query("""select product_id, sum(cogs) / nullif(sum(audio_hours), 0) as cph, month from marts.fct_unit_economics_monthly
                       where month in (?::date, ?::date) group by 1, 3""", [m, prev])
    cph = {(r["product_id"], str(r["month"])[:7]): float(r["cph"] or 0) for r in unit}
    moves = sorted(((p, cph.get((p, mm)), cph.get((p, prev[:7]))) for p in {k[0] for k in cph}),
                   key=lambda x: -abs((x[1] or 0) - (x[2] or 0)))
    b = [f"Gross margin {_pct(gm['value'], False)}, {(gm['change'] or 0) * 100:+.1f} points vs last month"
         + (f" (benchmark for usage-priced SaaS: {_pct(gm['benchmark_median'], False)} median)." if gm["benchmark_median"] else ".")]
    if moves and moves[0][1] is not None and moves[0][2]:
        p, now, before = moves[0]
        b.append(f"Largest cost-to-serve move: {p} at ${now:.4f}/audio hour vs ${before:.4f} last month ({_pct(now / before - 1)}).")
    sections.append({"title": "Margin", "status": card["gross_margin_pct"]["status"], "bullets": b})

    costs = wh.query("""select account_name, sum(case when month = ?::date then natural_amount else 0 end) as now,
                               sum(case when month = ?::date then natural_amount else 0 end) as before
                        from marts.fct_gl_monthly where account_type in ('cogs', 'opex') and month in (?::date, ?::date)
                        group by 1 order by abs(sum(case when month = ?::date then natural_amount else -natural_amount end)) desc limit 3""",
                     [m, prev, m, prev, m])
    bva = wh.query("""select department_id, account_name, variance, variance_pct from marts.fct_bva_monthly
                      where month = ?::date and is_alert order by abs(variance) desc limit 3""", [m])
    b = ["Biggest cost changes vs last month: " + "; ".join(f"{r['account_name']} {_usd(float(r['now']) - float(r['before']))}" for r in costs) + "."]
    if bva:
        b.append("Budget variances to explain: " + "; ".join(
            f"{'' if r['department_id'] == 'NONE' else r['department_id'] + ' '}{r['account_name']} {_usd(r['variance'])}" + (f" ({_pct(float(r['variance_pct']))})" if r["variance_pct"] is not None else "")
            for r in bva) + ".")
    sections.append({"title": "Costs", "status": "bad" if bva else "good", "bullets": b})

    g = wh.query("select * from marts.fct_growth_efficiency_monthly where month = ?::date", [m])
    g = g[0] if g else {}
    cash, burn, run, bm = card["closing_cash"], card["net_burn"], card["runway_months"], card["burn_multiple"]
    runway = "60+ months" if (run["value"] or 0) > 60 else f"{run['value'] or 0:.0f} months"
    b = [f"Cash {_usd(cash['value'])} at month end; net burn {_usd(burn['value'])}; runway {runway}.",
         f"Net new ARR {_usd(g.get('net_new_arr'))} this month (new {_usd(g.get('new_arr'))}, expansion {_usd(g.get('expansion_arr'))}, "
         f"contraction {_usd(g.get('contraction_arr'))}, churn {_usd(g.get('churned_arr'))})."
         + (f" Burn multiple {bm['value']:.2f}x over 3 months." if bm["value"] is not None else
            " Burn multiple not meaningful: net new ARR over the last 3 months is not positive.")]
    sections.append({"title": "Cash and efficiency", "status": bm["status"] or ("good" if (burn["value"] or 0) <= 0 else "ok"), "bullets": b})

    h = wh.query("""select health, count(*) as n, sum(arr) as arr from marts.fct_customer_health group by 1""")
    hh = {r["health"]: r for r in h}
    top = wh.query("select sum(revenue_share) as s from marts.fct_customer_health where revenue_rank <= 10")[0]["s"]
    risky = wh.query("""select customer_id, reasons, arr from marts.fct_customer_health where health = 'at_risk'
                        order by arr desc limit 3""")
    b = [f"Net revenue retention {_pct(card['nrr']['value'], False)}; logo churn {_pct(card['logo_churn_rate']['value'], False)} this month.",
         f"{(hh.get('at_risk') or {}).get('n', 0)} customers at risk ({_usd((hh.get('at_risk') or {}).get('arr'))} ARR), "
         f"{(hh.get('watch') or {}).get('n', 0)} to watch. Top 10 customers are {_pct(float(top or 0), False)} of revenue."]
    if risky:
        b.append("Largest at risk: " + "; ".join(f"{r['customer_id']} ({_usd(r['arr'])} ARR: {r['reasons'].rstrip(';')})" for r in risky) + ".")
    sections.append({"title": "Customers", "status": "bad" if risky else "good", "bullets": b})

    pipe = get_pipeline(wh)
    q = pipe["next_quarter"]
    b = [f"Open pipeline {_usd(pipe['total_arr'])} ({_usd(pipe['weighted_arr'])} weighted). Next quarter ({q['quarter']}): "
         f"{_usd(q['pipeline_arr'])} against a {_usd(q['quota'])} quota = {q['coverage']:.1f}x coverage"
         + (" (healthy is 3x+)." if q["coverage"] >= 3 else " (below the 3x a team usually needs).")]
    if pipe["slipped"]:
        b.append(f"{pipe['slipped']} {'deal is' if pipe['slipped'] == 1 else 'deals are'} ({_usd(pipe['slipped_arr'])}) past the close date and still open: update or close them.")
    sections.append({"title": "Pipeline", "status": "good" if q["coverage"] >= 3 else "bad", "bullets": b})

    bad = [s["title"] for s in sections if s["status"] == "bad"]
    headline = (f"{mm}: revenue {_usd(rev['value'])} ({_pct(rev['change_pct'])} m/m), net new ARR {_usd(g.get('net_new_arr'))}, "
                f"cash {_usd(cash['value'])}. " + (f"Needs attention: {', '.join(bad)}." if bad else "Nothing off track."))
    return {"source": "get_kpi_scorecard, fct_revenue_pvm_monthly, fct_customer_revenue_monthly, fct_gl_monthly, fct_bva_monthly, "
                      "fct_growth_efficiency_monthly, fct_customer_health, fct_pipeline",
            "month": mm, "headline": headline, "sections": sections, "row_count": len(sections), "rows": sections,
            "figures": figures, "pipeline_coverage": q["coverage"], "runway_months": run["value"]}


def get_growth_efficiency(wh, months=12):
    rows = wh.query("""select strftime(month, '%Y-%m') as month, opening_arr, new_arr, expansion_arr, reactivation_arr,
                              contraction_arr, churned_arr, closing_arr, net_new_arr, net_burn, quick_ratio, burn_multiple
                       from marts.fct_growth_efficiency_monthly order by month desc limit ?""", [int(months)])
    return _result(rows[::-1], "marts.fct_growth_efficiency_monthly",
                   note="ARR = monthly usage revenue × 12. Quick ratio and burn multiple use trailing 3 months.")


def get_cohort_retention(wh, kind="revenue", max_months=12):
    col = {"revenue": "revenue_retention", "logo": "logo_retention", "gross": "gross_revenue_retention"}[kind]
    rows = wh.query(f"""select strftime(cohort_month, '%Y-%m') as cohort, cohort_size, months_since, {col} as retention
                        from marts.fct_cohort_retention where months_since <= ? order by cohort, months_since""", [int(max_months)])
    grid = {}
    for r in rows:
        g = grid.setdefault(r["cohort"], {"cohort": r["cohort"], "customers": r["cohort_size"]})
        g[f"m{r['months_since']}"] = r["retention"]
    return _result(list(grid.values()), "marts.fct_cohort_retention", kind=kind,
                   note="Revenue (net) retention is vs the cohort's first full month (m1); gross retention caps each customer "
                        "at its m1 revenue, so expansion can't hide churn; logo retention is vs cohort size.")


def get_customer_health(wh, health=None):
    rows = wh.query("""select customer_id, segment, health, reasons, arr, revenue_share, revenue_rank, usage_trend,
                              hours_per_day_30d, days_since_usage, overdue_balance, disputed_amount
                       from marts.fct_customer_health where (? is null or health = ?)
                       order by case health when 'at_risk' then 0 when 'watch' then 1 else 2 end, arr desc""", [health, health])
    summary = wh.query("select health, count(*) as customers, sum(arr) as arr from marts.fct_customer_health group by 1")
    conc = wh.query("""select sum(case when revenue_rank = 1 then revenue_share end) as top1,
                              sum(case when revenue_rank <= 5 then revenue_share end) as top5,
                              sum(case when revenue_rank <= 10 then revenue_share end) as top10,
                              sum(revenue_share * revenue_share) as hhi from marts.fct_customer_health""")[0]
    return _result(rows, "marts.fct_customer_health", summary=summary, concentration=conc,
                   note="at_risk: usage down 40%+, no usage 14+ days, or open dispute. watch: usage down 20-40%, "
                        "30+ days late, or margin below floor.")


def get_pipeline(wh):
    rows = wh.query("""select opportunity_id, account_name, segment, rep_id, stage, probability, amount_arr, weighted_arr,
                              close_date, close_quarter, is_slipped, age_days, median_won_cycle_days
                       from marts.fct_pipeline order by close_date""")
    as_of = str(wh.query("select max(entry_date) as d from staging.stg_erp__journal_entries")[0]["d"])
    y, mo = int(as_of[:4]), int(as_of[5:7])
    qn = (mo - 1) // 3 + 1
    nq = (y + 1, 1) if qn == 4 else (y, qn + 1)
    next_q = f"{nq[0]}-Q{nq[1]}"
    quota = float(wh.query("select sum(annual_quota_arr) as q from seeds.sales_reps")[0]["q"]) / 4
    in_q = [r for r in rows if r["close_quarter"] == next_q and not r["is_slipped"]]
    q_arr = sum(float(r["amount_arr"]) for r in in_q)
    by_stage = {}
    for r in rows:
        s = by_stage.setdefault(r["stage"], {"stage": r["stage"], "deals": 0, "arr": 0.0, "weighted_arr": 0.0})
        s["deals"] += 1
        s["arr"] += float(r["amount_arr"])
        s["weighted_arr"] += float(r["weighted_arr"])
    slipped = [r for r in rows if r["is_slipped"]]
    bookings = wh.query("""select strftime(month, '%Y-%m') as month, sum(bookings_arr) as bookings_arr, sum(won_deals) as won,
                                  sum(lost_deals) as lost from marts.fct_bookings_monthly group by 1 order by 1""")
    rates = wh.query("""select segment, sum(won_deals) as won, sum(lost_deals) as lost,
                               sum(won_deals) * 1.0 / nullif(sum(won_deals + lost_deals), 0) as win_rate,
                               avg(avg_cycle_days) as avg_cycle_days
                        from marts.fct_bookings_monthly group by 1""")
    order = ["discovery", "evaluation", "proposal", "negotiation"]
    capacity = wh.query("""select strftime(month, '%Y-%m') as month, is_forecast, account_executives, ramped_aes, planned_aes,
                                  capacity_arr, bookings_arr, credited_arr from marts.fct_sales_capacity_monthly order by month""")
    return {"source": "marts.fct_pipeline, marts.fct_bookings_monthly, fct_sales_capacity_monthly, seeds.sales_reps",
            "row_count": len(rows), "rows": rows, "capacity": capacity,
            "total_arr": sum(float(r["amount_arr"]) for r in rows), "weighted_arr": sum(float(r["weighted_arr"]) for r in rows),
            "by_stage": sorted(by_stage.values(), key=lambda s: order.index(s["stage"])),
            "next_quarter": {"quarter": next_q, "pipeline_arr": q_arr, "quota": quota,
                             "coverage": q_arr / quota if quota else 0, "deals": len(in_q)},
            "slipped": len(slipped), "slipped_arr": sum(float(r["amount_arr"]) for r in slipped),
            "bookings": bookings, "win_rates": rates,
            "note": "Coverage = open pipeline expected to close next quarter / quarterly quota (sum of AE quotas / 4)."}


def get_product_unit_economics(wh, months=12):
    rows = wh.query("""select strftime(month, '%Y-%m') as month, product_id, sum(audio_hours) as audio_hours,
                              sum(revenue) as revenue, sum(cogs) as cogs,
                              sum(revenue) / nullif(sum(audio_hours), 0) as revenue_per_hour,
                              sum(cogs) / nullif(sum(audio_hours), 0) as cost_per_hour,
                              (sum(revenue) - sum(cogs)) / nullif(sum(revenue), 0) as gross_margin_pct
                       from marts.fct_unit_economics_monthly
                       where month > (select max(month) from marts.fct_unit_economics_monthly) - interval (?) month
                       group by 1, 2 order by 1, 2""", [int(months)])
    return _result(rows, "marts.fct_unit_economics_monthly",
                   note="Revenue and cost to serve per audio hour by product (COGS = GPU + shared GPU + unused commit + cloud).")


def get_receivables_dashboard(wh):
    """Everything the Receivables page cross-filters: every open invoice (with segment, bucket, route and the
    recommended action), the 12-month DSO / CEI / days-delinquent trend, and expected receipts by week."""
    invoices = wh.query("""
        select a.invoice_ref, a.customer_id, a.segment, a.invoice_type, i.invoice_date, i.due_date, a.balance,
               a.days_past_due, a.aging_bucket, coalesce(i.is_disputed, false) as is_disputed,
               coalesce(q.is_on_hold, false) as is_on_hold,
               coalesce(q.route, case when a.days_past_due = 0 then 'not_due' end) as route,
               coalesce(q.recommended_action, case when a.days_past_due = 0 then 'Not due yet' end) as recommended_action
        from marts.fct_ar_aging_snapshot a
        left join marts.fct_ar_invoices i on i.invoice_ref = a.invoice_ref
        left join marts.fct_collections_queue q on q.invoice_ref = a.invoice_ref
        where a.snapshot_date = (select max(snapshot_date) from marts.fct_ar_aging_snapshot)
        order by a.balance desc""")
    behaviour = {(r["customer_id"], r["invoice_type"]): r for r in wh.query("select * from marts.fct_customer_payment_behavior")}
    by_segment = {r["segment"]: float(r["d"] or 0) for r in wh.query(
        "select segment, avg(avg_days_late) as d from marts.fct_customer_payment_behavior group by 1")}
    today = dt.date.fromisoformat(str(wh.query("select max(entry_date) as d from staging.stg_erp__journal_entries")[0]["d"]))
    for r in invoices:
        b = behaviour.get((r["customer_id"], r["invoice_type"]))
        late = float(b["avg_days_late"]) if b else by_segment.get(r["segment"], 0.0)
        due = dt.date.fromisoformat(str(r["due_date"])) if r["due_date"] else today
        if r["is_disputed"] or r["is_on_hold"]:
            r["predicted_pay_date"], r["prediction_basis"] = None, "on hold: not until the dispute is resolved"
        else:
            pred = max(due + dt.timedelta(days=round(late)), today + dt.timedelta(days=1))
            r["predicted_pay_date"] = pred.isoformat()
            r["predicted_days_late"] = max(0, (pred - due).days)
            r["prediction_basis"] = (f"{r['customer_id']} pays {late:.0f} days late on average ({b['invoices_paid']} invoices)" if b
                                     else f"{r['segment'].replace('_', ' ')} average, {late:.0f} days late")
    predicted = {}
    for r in invoices:
        if r["predicted_pay_date"]:
            d0 = dt.date.fromisoformat(r["predicted_pay_date"])
            wk = (d0 - dt.timedelta(days=d0.weekday())).isoformat()
            predicted[wk] = predicted.get(wk, 0.0) + float(r["balance"])
    trend = wh.query("""
        select strftime(month, '%Y-%m') as month, ending_ar, ending_current_ar, ar_over_60, sales, dso_days, cei,
               -- best possible DSO: what DSO would be if nothing were late; the gap is average days delinquent
               round(ending_current_ar / nullif(sales, 0) * day(last_day(month)), 1) as best_possible_dso,
               round(dso_days - ending_current_ar / nullif(sales, 0) * day(last_day(month)), 1) as avg_days_delinquent
        from marts.fct_ar_monthly where month <= (select max(month) from marts.fct_kpi_monthly)
        order by month desc limit 12""")[::-1]
    receipts = wh.query("""select week, strftime(week_start, '%Y-%m-%d') as week_start, inflows
                           from marts.fct_cash_forecast_13w order by week""")
    terms = {r["segment"]: r for r in wh.query("select * from seeds.ar_policy")}
    return {"source": "marts.fct_collections_queue, fct_ar_aging_snapshot, fct_ar_monthly, fct_cash_forecast_13w, seeds.ar_policy",
            "row_count": len(invoices), "rows": invoices, "trend": trend, "receipts": receipts,
            "predicted_receipts": [{"week_start": k, "amount": round(v, 2)} for k, v in sorted(predicted.items())],
            "terms_days": {k: v.get("payment_terms_days") for k, v in terms.items()},
            "note": "Open invoices today; DSO and CEI by closed month; receipts are the 13-week forecast's customer inflows."}


# ---- Dashboard tools (docs/dashboard_spec.md): detail rows to cross-filter + trends, one call per page ----------

def get_budget_dashboard(wh, month=None):
    """Budget vs actual for a closed month. fav_variance is signed so positive is always good (revenue above budget,
    costs below budget). Also the 12-month actual vs budget trend and the budget-to-actual EBITDA bridge."""
    m = _month(month, wh)
    rows = wh.query("""
        select b.department_id, case when b.department_id = 'NONE' then 'Company' else coalesce(d.department_name, 'Company') end as department,
               coalesce(d.owner_title, 'VP Finance') as owner,
               b.account_id, b.account_name, a.account_type, a.rollup, b.actual, b.budget,
               case when a.account_type = 'revenue' then b.actual - b.budget else b.budget - b.actual end as fav_variance,
               b.variance_pct, b.ytd_actual, b.ytd_budget,
               case when a.account_type = 'revenue' then b.ytd_actual - b.ytd_budget else b.ytd_budget - b.ytd_actual end as ytd_fav_variance,
               b.fy_budget, b.fy_forecast,
               case when a.account_type = 'revenue' then b.fy_forecast - b.fy_budget else b.fy_budget - b.fy_forecast end as fy_fav_variance,
               b.is_alert, al.alert_id, al.commentary_draft, al.commentary_status
        from marts.fct_bva_monthly b
        join seeds.gl_accounts a using (account_id)
        left join seeds.departments d on d.department_id = b.department_id
        left join marts.fct_bva_alerts al on al.month = b.month and al.department_id = b.department_id and al.account_id = b.account_id
        where b.month = ?::date
        order by abs(case when a.account_type = 'revenue' then b.actual - b.budget else b.budget - b.actual end) desc""", [m])
    for r in rows:
        r["direction"] = "favorable" if (r["fav_variance"] or 0) >= 0 else "unfavorable"
    trend = wh.query("""
        select strftime(b.month, '%Y-%m') as month,
               sum(case when a.account_type = 'revenue' then b.actual end) as revenue_actual,
               sum(case when a.account_type = 'revenue' then b.budget end) as revenue_budget,
               sum(case when a.account_type in ('cogs', 'opex') then b.actual end) as cost_actual,
               sum(case when a.account_type in ('cogs', 'opex') then b.budget end) as cost_budget,
               sum(case when a.account_type = 'revenue' then b.actual else -b.actual end) as ebitda_actual,
               sum(case when a.account_type = 'revenue' then b.budget else -b.budget end) as ebitda_budget
        from marts.fct_bva_monthly b join seeds.gl_accounts a using (account_id)
        where b.month <= ?::date and b.month > ?::date - interval 12 month and b.account_id <> '6600'
        group by 1 order by 1""", [m, m])
    return {"source": "marts.fct_bva_monthly, fct_bva_alerts, seeds.gl_accounts, seeds.departments", "month": m[:7],
            "row_count": len(rows), "rows": rows, "trend": trend,
            "note": "fav_variance > 0 is favorable for every line (revenue above budget, costs below)."}


def get_spend_dashboard(wh, months=12):
    """Tech spend detail for the last closed month (vendor, team, category, model, tagged), the monthly trend with
    audio hours and cost per hour, GPU commit utilization, the forecast and contract renewals."""
    m = _month(None, wh)
    rows = wh.query("""
        select vendor_id, coalesce(team, 'untagged') as team, category, coalesce(model, 'none') as model,
               case when is_tagged then 'tagged' else 'untagged' end as tagging, sum(cost) as cost
        from marts.fct_tech_spend_daily where spend_month = ?::date group by all order by cost desc""", [m])
    trend = wh.query("""
        with s as (select spend_month as month, sum(cost) as cost,
                          sum(case when vendor_id = 'nimbus' then cost else 0 end) as gpu_cost,
                          sum(case when vendor_id <> 'nimbus' then cost else 0 end) as cloud_cost
                   from marts.fct_tech_spend_daily group by 1),
             u as (select usage_month as month, sum(audio_hours) as audio_hours from staging.stg_synthetic__usage_daily group by 1)
        select strftime(s.month, '%Y-%m') as month, s.cost, s.gpu_cost, s.cloud_cost, u.audio_hours,
               s.cost / nullif(u.audio_hours, 0) as cost_per_hour
        from s join u using (month) where s.month <= ?::date order by s.month desc limit ?""", [m, int(months)])[::-1]
    capacity = wh.query("""select strftime(month, '%Y-%m') as month, gpu_type, used_hours, committed_hours,
                                  commit_utilization_pct, shortfall_cost
                           from marts.fct_gpu_capacity_monthly where month <= ?::date order by month desc limit ?""", [m, int(months)])[::-1]
    forecast = wh.query("""select strftime(forecast_month, '%Y-%m') as month, sum(forecast_amount) as forecast
                           from marts.fct_spend_forecast group by 1 order by 1""")
    contracts = wh.query("select * from marts.fct_vendor_contracts order by end_date")
    return {"source": "marts.fct_tech_spend_daily, stg_synthetic__usage_daily, fct_gpu_capacity_monthly, fct_spend_forecast, fct_vendor_contracts",
            "month": m[:7], "row_count": len(rows), "rows": rows, "trend": trend, "capacity": capacity,
            "forecast": forecast, "contracts": contracts}


def get_ap_dashboard(wh):
    """AP: every bill document with its route and issues (one row per issue for the exception breakdown), open bills
    with due dates and discounts, and DPO by month."""
    docs = wh.query("""select doc_file, vendor_id, coalesce(vendor_name, vendor_id) as vendor, vendor_invoice_number, invoice_date,
                              total, route, issues, issue_count from marts.fct_ap_documents order by invoice_date desc""")
    issues = [{"doc_file": d["doc_file"], "vendor": d["vendor"], "issue": i, "total": d["total"]}
              for d in docs for i in (d["issues"] or [])]
    for d in docs:
        d["issues"] = ", ".join(d["issues"] or [])
    open_bills = wh.query("""select bill_ref, vendor_id, bill_date, due_date, amount, priority, payment_run_date,
                                    discount_captured, amount_to_pay, is_overdue,
                                    strftime(date_trunc('week', due_date), '%Y-%m-%d') as due_week
                             from marts.fct_payment_run_proposal order by due_date""")
    dpo = wh.query("""select strftime(month, '%Y-%m') as month, dpo_days, ap_balance from marts.fct_working_capital_monthly
                      where month <= (select max(month) from marts.fct_kpi_monthly) order by month desc limit 12""")[::-1]
    terms = wh.query("select avg(payment_terms_days) as d from seeds.vendor_payment_terms")[0]["d"]
    return {"source": "marts.fct_ap_documents, fct_payment_run_proposal, fct_working_capital_monthly, seeds.vendor_payment_terms",
            "row_count": len(docs), "rows": docs, "issues": issues, "open_bills": open_bills, "dpo": dpo,
            "avg_terms_days": float(terms or 30)}


def get_close_dashboard(wh, month=None):
    """The close checklist for the month being closed (status, owner, workday), reconciliation results for it, and
    how many workdays each past close took."""
    m = wh.query("select max(month) as m from marts.fct_close_status")[0]["m"]
    tasks = wh.query("""select task_id, workday, due_date, owner, task, evidence, status, open_items
                        from marts.fct_close_status where month = ? order by workday, task_id""", [m])
    as_of = str(wh.query("select max(entry_date) as d from staging.stg_erp__journal_entries")[0]["d"])
    for t in tasks:
        t["overdue"] = t["status"] != "complete" and str(t["due_date"]) < as_of
        t["state"] = "complete" if t["status"] == "complete" else ("overdue" if t["overdue"] else t["status"])
    recon = wh.query("""select check_name, status, count(*) as periods from recon.recon_status
                        where period = ? group by 1, 2 order by 1""", [m])
    history = wh.query("""select strftime(month, '%Y-%m') as month, max(case when status = 'complete' then workday end) as last_workday_done,
                                 count(*) as tasks, sum(case when status = 'complete' then 1 else 0 end) as done
                          from marts.fct_close_status group by 1 order by 1 desc limit 12""")[::-1]
    return {"source": "marts.fct_close_status, recon.recon_status", "month": str(m)[:7], "as_of": as_of,
            "row_count": len(tasks), "rows": tasks, "recon": recon, "history": history}


def get_projects_dashboard(wh):
    """Every project's economics (budget, EAC, earned, billed, margin) and contract funding by CLIN, plus exceptions."""
    projects = wh.query("""select project_id, project_name, project_type, customer_id, contract_value, budget, eac,
                                  eac_pct_of_budget, variance_at_completion, pct_complete, earned_to_date, billed_to_date,
                                  unbilled, deferred, cap_used_pct, is_over_budget, is_cap_alert,
                                  (contract_value - eac) / nullif(contract_value, 0) as forecast_margin_pct
                           from marts.fct_project_financials
                           where month = (select max(month) from marts.fct_project_financials where month <= (select max(month) from marts.fct_kpi_monthly))
                           order by project_id""")
    for r in projects:
        r["billing_position"] = ("underbilled" if (r["unbilled"] or 0) > 0 else "overbilled" if (r["deferred"] or 0) > 0 else "even")
    funding = wh.query("""select contract_id, clin_id, ceiling, funded, billed_to_date, unbilled, funding_remaining,
                                 funding_used_pct, is_federal, is_funding_alert_75, is_funding_alert_90
                          from marts.fct_contract_funding
                          where month = (select max(month) from marts.fct_contract_funding where month <= (select max(month) from marts.fct_kpi_monthly))
                          order by contract_id, clin_id""")
    exceptions = wh.query("select exception_type, project_id, reference_id, amount, detail from marts.fct_project_exceptions")
    return {"source": "marts.fct_project_financials, fct_contract_funding, fct_project_exceptions",
            "row_count": len(projects), "rows": projects, "funding": funding, "exceptions": exceptions}


def get_commissions_dashboard(wh):
    """Commission statements for every rep and closed month (attainment, credited ARR, commission, clawbacks) and
    this year's credits by customer. Effective rate = commission / credited ARR."""
    rows = wh.query("""select rep_id, rep_name, segment_focus, strftime(month, '%Y-%m') as month, new_arr, expansion_arr,
                              clawback_arr, ytd_credited_arr, annual_quota_arr, quota_attainment_pct, commission_base,
                              commission_accelerator, commission_clawback, commission_total
                       from marts.fct_commission_statement_monthly
                       where month <= (select max(month) from marts.fct_kpi_monthly) order by month, rep_id""")
    credits = wh.query("""select rep_id, customer_id, credit_type, max(split_pct) as split_pct, sum(billed_revenue) as billed_revenue,
                                 sum(credited_arr) as credited_arr, sum(comp_credit) as comp_credit
                          from marts.int_sales_credits
                          where extract(year from month) = (select extract(year from max(month)) from marts.fct_kpi_monthly)
                          group by 1, 2, 3 order by credited_arr desc""")
    deferred = wh.query("""select strftime(month, '%Y-%m') as month, sum(capitalized) as capitalized, sum(amortization) as amortization,
                                  sum(deferred_commission_balance) as deferred_commission_balance, sum(current_portion) as current_portion
                           from marts.fct_deferred_commissions_monthly
                           where month <= (select max(month) from marts.fct_kpi_monthly) group by 1 order by 1""")
    plans = wh.query("""select plan_id, rep_id, strftime(effective_from, '%Y-%m-%d') as effective_from, annual_quota_arr, base_rate,
                               accelerator_rate, expansion_multiplier, clawback_days, note from seeds.comp_plans order by effective_from, rep_id""")
    splits = wh.query("select * from seeds.credit_splits order by customer_id, rep_id")
    spiffs = wh.query("""select s.spiff_id, s.name, strftime(s.start_month, '%Y-%m') as start_month, strftime(s.end_month, '%Y-%m') as end_month,
                                s.amount_per_credit,
                                (select coalesce(sum(s.amount_per_credit * c.split_pct), 0) from marts.int_sales_credits c
                                 where c.segment = s.segment and c.credit_type = s.credit_type and not c.is_clawback
                                   and c.month between s.start_month and s.end_month) as paid
                         from seeds.spiffs s order by s.start_month""")
    last = deferred[-1] if deferred else {}
    return {"source": "marts.fct_commission_statement_monthly, marts.int_sales_credits, fct_deferred_commissions_monthly, "
                      "seeds.comp_plans, seeds.credit_splits, seeds.spiffs",
            "row_count": len(rows), "rows": rows, "credits": credits, "deferred": deferred, "plans": plans, "splits": splits,
            "spiffs": spiffs, "deferred_summary": {"balance": last.get("deferred_commission_balance"),
                                                   "current_portion": last.get("current_portion")},
            "note": "Comp plan versions by year (quota, rates, expansion credit, clawback); credit splits share an account's "
                    "credit; SPIFFs paid per qualifying credit; commissions capitalized and amortized under ASC 340-40."}


def get_tax_dashboard(wh):
    """Sales tax / VAT / GST and FX by month, currency and regime: billings, tax collected, tax due to each
    authority, realized FX and unrealized FX on open receivables."""
    rows = wh.query("""select strftime(month, '%Y-%m') as month, currency, tax_regime, invoices, billings_usd, billings_local,
                              tax_collected_usd, tax_remit_due, realized_fx, unrealized_fx_on_open_ar
                       from marts.fct_tax_fx_monthly where month <= (select max(month) from marts.fct_kpi_monthly)
                       order by month, currency""")
    return {"source": "marts.fct_tax_fx_monthly", "row_count": len(rows), "rows": rows}


def get_trust_dashboard(wh):
    """Every reconciliation result by check and period (pass/fail, expected vs actual), the pass rate by period, and
    the open failures. Data quality score = checks passing / checks run."""
    rows = wh.query("""select check_name, strftime(period, '%Y-%m') as period, entity_id, expected, actual, variance, status,
                              explanation from recon.recon_status order by period, check_name""")
    by_period = {}
    for r in rows:
        b = by_period.setdefault(r["period"], {"period": r["period"], "checks": 0, "passing": 0})
        b["checks"] += 1
        b["passing"] += r["status"] == "pass"
    trend = [{**b, "pass_rate": b["passing"] / b["checks"]} for b in sorted(by_period.values(), key=lambda b: b["period"])]
    return {"source": "recon.recon_status", "row_count": len(rows), "rows": rows, "trend": trend,
            "failures": [r for r in rows if r["status"] != "pass"]}


# Controller's close review: what is booked (accruals, prepaids, depreciation), does every balance sheet account tie to
# its support, and why did each line move (flux)? Materiality for flux: |change| >= $25K and >= 10% of the prior month.
FLUX_ABS, FLUX_PCT = 25000, 0.10
RECON_FOR_ACCOUNT = {  # balance sheet account -> the independent check that proves it, and what it is compared to
    "1000": ("stripe_balance_vs_gl_cash", "Stripe balance and payouts"),
    "1200": (None, "AR subledger (open invoices)"),
    "1500": (None, "Fixed asset register"),
    "1510": (None, "Depreciation schedule"),
    "2000": ("vendor_bill_vs_gl_ap", "Vendor bills"),
    "2100": ("payroll_register_vs_gl", "Payroll register"),
    "2110": ("payroll_register_vs_gl", "Payroll register"),
    "3000": (None, "Cap table (funding rounds)"),
}


def get_close_review(wh, month=None):
    m = str(wh.query("select max(month) as m from marts.fct_close_status")[0]["m"])[:10]
    prev = _shift(m[:7], -1) + "-01"
    accruals = wh.query("""select strftime(month, '%Y-%m') as month, vendor_id, bill_id, bill_date, accrued_amount, billed_amount,
                                  true_up, case when billed_amount is null then 'awaiting invoice'
                                                when abs(true_up) < 0.01 then 'matched' else 'trued up' end as status
                           from marts.fct_accruals_monthly where month in (?::date, ?::date) order by month desc, accrued_amount desc""",
                        [m, prev])
    prepaids = wh.query("""select prepaid_id, vendor, amortization, closing_balance from marts.fct_prepaid_schedule
                           where month = ?::date""", [m])

    # balance sheet: GL balance at month end vs its support
    gl = {r["account_id"]: r for r in wh.query("""
        select account_id, account_name, sum(natural_amount) as balance,
               sum(case when month = ?::date then natural_amount else 0 end) as movement
        from marts.fct_gl_monthly where account_type in ('asset', 'liability', 'equity') and month <= ?::date
        group by 1, 2""", [m, m])}
    checks = {r["check_name"]: r for r in wh.query("""select check_name, bool_and(status = 'pass') as passing, sum(abs(variance)) as variance
                                                      from recon.recon_status where period = ?::date group by 1""", [m])}
    ar_sub = wh.query("select ending_ar from marts.fct_ar_monthly where month = ?::date", [m])
    dep_posted = wh.query("""select count(*) as n from staging.stg_erp__journal_entries
                             where entry_type = 'depreciation' and entry_month = ?::date""", [m])[0]["n"]
    recs = []
    for acct, (check, support) in RECON_FOR_ACCOUNT.items():
        g = gl.get(acct)
        if not g:
            continue
        bal = float(g["balance"] or 0)
        row = {"account_id": acct, "account": g["account_name"], "gl_balance": bal, "movement": float(g["movement"] or 0),
               "support": support, "support_balance": None, "difference": None}
        if acct == "1200" and ar_sub:
            row["support_balance"] = float(ar_sub[0]["ending_ar"])
            row["difference"] = round(bal - row["support_balance"], 2)
            # a payment applied to the wrong invoice leaves the subledger over by exactly that amount while the GL,
            # which booked the cash, is right: the difference is explained by the open cash application exceptions
            misapplied = wh.query("""select sum(amount) as a, string_agg(detail, '; ') as d from marts.fct_cash_application_exceptions
                                     where exception_type = 'overapplied' and exception_date <= ?::date""", [_shift(m[:7], 1) + "-01"])[0]
            if abs(row["difference"]) < 1:
                row["status"] = "reconciled"
            elif misapplied["a"] and abs(row["difference"] + float(misapplied["a"])) < 1:
                row["status"], row["explanation"] = "explained", f"Cash applied to the wrong invoice: {misapplied['d']}. Reclass in the subledger; GL is right."
            else:
                row["status"] = "difference"
        elif check:
            c = checks.get(check)
            row["status"] = "no check this period" if not c else ("reconciled" if c["passing"] else "difference")
            row["difference"] = None if not c else float(c["variance"] or 0)
            row["check"] = check
        elif acct in ("1500", "1510"):
            row["status"] = "reconciled" if dep_posted else "depreciation not posted"
        else:
            row["status"] = "no activity" if abs(row["movement"]) < 0.01 else "review"
        recs.append(row)

    # flux: every P&L and balance sheet account, this month vs last month
    flux = wh.query("""
        select account_id, account_name, account_type,
               sum(case when month = ?::date then natural_amount else 0 end) as current,
               sum(case when month = ?::date then natural_amount else 0 end) as prior
        from marts.fct_gl_monthly where account_type in ('revenue', 'cogs', 'opex') and month in (?::date, ?::date)
        group by 1, 2, 3""", [m, prev, m, prev])
    bs_prev = {r["account_id"]: float(r["b"] or 0) for r in wh.query("""select account_id, sum(natural_amount) as b from marts.fct_gl_monthly
                                                                         where account_type in ('asset', 'liability', 'equity') and month <= ?::date group by 1""", [prev])}
    for acct, g in gl.items():
        if acct in bs_prev or g["balance"]:
            flux.append({"account_id": acct, "account_name": g["account_name"], "account_type": "balance sheet",
                         "current": float(g["balance"] or 0), "prior": bs_prev.get(acct, 0.0)})
    hours = {str(r["m"])[:7]: float(r["h"]) for r in wh.query("""select usage_month as m, sum(audio_hours) as h from staging.stg_synthetic__usage_daily
                                                                    where usage_month in (?::date, ?::date) group by 1""", [m, prev])}
    heads = {str(r["month"])[:7]: r["value"] for r in wh.query("""select month, value from marts.fct_kpi_monthly
                                                                    where metric_name = 'headcount' and month in (?::date, ?::date)""", [m, prev])}
    movers = wh.query("""select customer_id, revenue_change from marts.fct_customer_revenue_monthly
                         where month = ?::date order by abs(revenue_change) desc limit 2""", [m])
    hchg = (hours.get(m[:7], 0) / hours[prev[:7]] - 1) if hours.get(prev[:7]) else None
    for f in flux:
        cur, pri = float(f["current"] or 0), float(f["prior"] or 0)
        f["current"], f["prior"], f["change"] = cur, pri, cur - pri
        f["change_pct"] = (cur - pri) / abs(pri) if pri else None
        f["material"] = abs(cur - pri) >= FLUX_ABS and (pri == 0 or abs(cur - pri) / abs(pri) >= FLUX_PCT)
        a = f["account_id"]
        why = None
        if a == "4000" and hchg is not None:
            why = f"audio hours {hchg * 100:+.1f}%; biggest moves " + ", ".join(f"{r['customer_id']} {_usd_text(r['revenue_change'])}" for r in movers)
        elif a in ("5000", "5010") and hchg is not None:
            why = f"usage-driven: audio hours {hchg * 100:+.1f}%"
        elif a in ("6000", "6010", "6020") and heads.get(m[:7]) is not None and heads.get(prev[:7]) is not None:
            why = f"headcount {int(heads[prev[:7]])} to {int(heads[m[:7]])}"
        elif a == "6600":
            why = "new assets placed in service" if abs(cur - pri) > 1 else "straight-line, unchanged"
        elif a == "1200":
            why = "September usage invoiced on the 1st; enterprise terms 45 days"
        elif a == "1000":
            why = "net burn for the month"
        elif a == "2000":
            why = "GPU bill accrued at month end, paid the month after"
        f["explanation"] = why
        f["needs_explanation"] = f["material"] and not why
    flux.sort(key=lambda f: -abs(f["change"]))

    journals = wh.query("""
        select e.entry_type, count(distinct e.entry_id) as entries, sum(l.debit) as amount,
               e.entry_type in ('one_off', 'funding', 'capex') as is_manual
        from staging.stg_erp__journal_entries e join staging.stg_erp__journal_lines l using (entry_id)
        where e.entry_month = ?::date group by 1 order by amount desc""", [m])
    tasks = wh.query("""select task_id, workday, due_date, owner, task, evidence, status, open_items
                        from marts.fct_close_status where month = ?::date order by workday, task_id""", [m])
    rr = wh.query("select * from marts.fct_revenue_rollforward_monthly where month = ?::date", [m])
    return {"source": "marts.fct_accruals_monthly, fct_prepaid_schedule, fct_gl_monthly, recon.recon_status, fct_ar_monthly, "
                      "staging.stg_erp__journal_entries, fct_close_status, fct_revenue_rollforward_monthly",
            "month": m[:7], "prior_month": prev[:7], "row_count": len(flux), "rows": flux, "accruals": accruals,
            "prepaids": prepaids, "reconciliations": recs, "journals": journals, "tasks": tasks,
            "revenue_rollforward": rr[0] if rr else None,
            "materiality": {"abs": FLUX_ABS, "pct": FLUX_PCT},
            "note": "Flux is material at |change| >= $25K and >= 10%. History bills are booked at their final amount, "
                    "so true-ups appear only in live months."}


STRESS_PRESETS = {
    "downturn": {"label": "Downturn", "nrr_pts": -0.05, "cycle_days": 30, "win_rate_pct": -0.2},
    "price_war": {"label": "Price war", "price_pct": -0.10, "win_rate_pct": -0.15, "nrr_pts": -0.03},
    "gpu_squeeze": {"label": "GPU cost up", "cogs_pts": 0.06},
    "lean": {"label": "Hiring freeze", "hiring_pct": 0.0, "opex_pct": -0.10},
    "breakout": {"label": "Breakout", "nrr_pts": 0.05, "win_rate_pct": 0.25, "cycle_days": -15},
    "severe_downside": {"label": "Severe downside", "nrr_pts": -0.15, "win_rate_pct": -0.4, "cycle_days": 60, "price_pct": -0.05,
                        "cogs_pts": 0.04},
    "fundraise_delayed": {"label": "Fundraise delayed", "raise_delay_months": 6},
    "largest_customer_churn": {"label": "Largest customer leaves", "lose_largest": 1, "lose_in_months": 3},
    "gpu_price_shock": {"label": "GPU price shock", "cogs_pts": 0.12},
}
# what each preset means, for the page and the assistant
PRESET_NOTES = {
    "downturn": "NRR -5 pts, 20% fewer wins, deals a month slower.",
    "price_war": "Prices -10%, 15% fewer wins, NRR -3 pts.",
    "gpu_squeeze": "Cost to serve +6 points of revenue.",
    "lean": "Hiring freeze and other opex -10%.",
    "breakout": "NRR +5 pts, 25% more wins, deals two weeks faster.",
    "severe_downside": "NRR -15 pts, 40% fewer wins, deals two months slower, prices -5%, cost to serve +4 pts.",
    "fundraise_delayed": "The base plan's round closes six months late; compared with the round on time.",
    "largest_customer_churn": "The largest customer by MRR leaves in three months; nothing replaces it.",
    "gpu_price_shock": "GPU and cloud prices jump: cost to serve +12 points of revenue (about a third more).",
}


def _stress_base(wh, as_of=None):
    """The engine's starting point from the warehouse, as of a closed month (default the latest). For an earlier
    month (to re-run the forecast as it stood at that close) the pipeline is rebuilt as it was: deals created by then
    and not yet closed, with deals that closed later counted at even odds."""
    m = _month(as_of, wh)
    gl = {r["account_type"] + ("_svc" if r["account_id"] == "4100" else ""): r for r in wh.query("""
        select account_type, account_id, sum(natural_amount) as v from marts.fct_gl_monthly where month = ?::date
        group by 1, 2""", [m])}
    by = {}
    for r in wh.query("select account_id, account_type, sum(natural_amount) as v from marts.fct_gl_monthly where month = ?::date group by 1, 2", [m]):
        by[r["account_id"]] = float(r["v"] or 0)
    revenue = sum(v for a, v in by.items() if a.startswith("4"))
    services = by.get("4100", 0.0)
    cogs = sum(v for a, v in by.items() if a.startswith("5"))
    payroll_now = sum(by.get(a, 0.0) for a in ("6000", "6010", "6020"))
    cash = float(wh.query("select closing_cash from marts.fct_cash_monthly where month = ?::date", [m])[0]["closing_cash"])
    bridge = wh.query("""select (expansion_mrr + contraction_mrr + churned_mrr + reactivation_mrr) / nullif(opening_mrr, 0) as net
                         from marts.fct_mrr_bridge_monthly where month <= ?::date order by month desc limit 6""", [m])
    net = sum(float(b["net"] or 0) for b in bridge) / max(1, len(bridge))
    ss_new = wh.query("""select coalesce(sum(revenue), 0) / 6 as v from marts.fct_customer_revenue_monthly
                         where movement = 'new' and customer_id like 'SS-%' and month > ?::date - interval 6 month and month <= ?::date""", [m, m])[0]["v"]
    if m == _month(None, wh):
        pipe = [{"close_month": str(r["close_date"])[:7], "arr": float(r["amount_arr"]), "prob": float(r["probability"])}
                for r in wh.query("select close_date, amount_arr, probability from marts.fct_pipeline")]
    else:
        pipe = [{"close_month": str(r["close_date"])[:7], "arr": float(r["amount_arr"]), "prob": float(r["p"])}
                for r in wh.query("""select close_date, amount_arr, case when is_closed then 0.5 else probability end as p
                                     from staging.stg_crm__opportunities
                                     where created_date < ?::date + interval 1 month
                                       and (not is_closed or close_date >= ?::date + interval 1 month)""", [m, m])]
    book = wh.query("""select coalesce(sum(bookings_arr), 0) / 12 as v from marts.fct_bookings_monthly
                       where month > ?::date - interval 12 month and month <= ?::date""", [m, m])[0]["v"]
    fc = wh.query("""select payroll, other_opex from marts.fct_forecast_monthly where as_of_month = ?::date and scenario = 'base'
                     order by month""", [m])
    other_now = sum(v for a, v in by.items() if a.startswith("6") and a not in ("6000", "6010", "6020", "6600"))
    return {"start_month": m[:7], "mrr": revenue - services, "services": services, "cash": cash, "cogs_pct": cogs / revenue if revenue else 0,
            "existing_net_monthly": net, "self_serve_new_mrr": float(ss_new or 0), "pipeline": pipe,
            "bookings_arr_monthly": float(book or 0), "payroll": [float(r["payroll"]) for r in fc] or [payroll_now],
            "other_opex": [float(r["other_opex"]) for r in fc] or [other_now], "payroll_now": payroll_now,
            "other_opex_now": other_now}


SCENARIO_ORDER = ["base", "upside", "downside"]


def _scenario_levers(wh, scenario, with_raise=True):
    """A planning scenario as engine levers (seeds/scenario_levers.csv), plus its planned round
    (seeds/fundraise_scenarios.csv) when with_raise."""
    lv = {r["lever"]: float(r["value"]) for r in wh.query("select lever, value from seeds.scenario_levers where scenario = ?", [scenario])}
    if "cycle_days" in lv:
        lv["cycle_days"] = int(lv["cycle_days"])
    if with_raise:
        r = wh.query("select raise_amount, close_month from seeds.fundraise_scenarios where scenario = ?", [scenario])
        if r:
            lv["raise_amount"], lv["raise_month"] = float(r[0]["raise_amount"]), str(r[0]["close_month"])[:7]
    return lv


def _engine_scenario(wh, scenario, base=None, months=18):
    from finance_os import fpa
    base = base or _stress_base(wh)
    return fpa.project(base, _scenario_levers(wh, scenario), months)


def _scenario_summary(scenario, out):
    rows, sm = out["rows"], out["summary"]
    rev12 = sum(r["revenue"] for r in rows[:12])
    return {"scenario": scenario, "as_of_month": None, "revenue_next_12m": round(rev12, 2),
            "gross_margin_pct_next_12m": round(1 - sum(r["cogs"] for r in rows[:12]) / rev12, 4) if rev12 else None,
            "opex_next_12m": round(sum(r["payroll"] + r["other_opex"] for r in rows[:12]), 2),
            "ebitda_next_12m": sm["ebitda_12m"], "cash_in_12m": rows[min(11, len(rows) - 1)]["cash_no_raise"],
            "cash_out_month": sm["cash_out_month_no_raise"], "runway_months": sm["runway_months_no_raise"],
            "runway_months_with_raise": sm["runway_months"], "cash_out_month_with_raise": sm["cash_out_month"],
            "arr_in_12m": sm["arr_12m"], "first_ebitda_positive": sm["first_ebitda_positive"]}


def scenario_summaries(wh, base=None):
    """Every planning scenario through the one driver engine: next-12-month P&L, cash and runway."""
    base = base or _stress_base(wh)
    out = []
    for sc in SCENARIO_ORDER:
        sm = _scenario_summary(sc, _engine_scenario(wh, sc, base))
        sm["as_of_month"] = base["start_month"]
        out.append(sm)
    return out


def run_stress_test(wh, preset=None, nrr_pts=None, win_rate_pct=None, cycle_days=None, price_pct=None, cogs_pts=None,
                    hiring_pct=None, opex_pct=None, raise_amount=None, raise_month=None, months=24):
    """Stress test the plan: revenue, EBITDA, ARR and cash for 24 months under the given levers, next to the baseline."""
    from finance_os import fpa
    base = _stress_base(wh)
    levers = {k: v for k, v in (STRESS_PRESETS.get(preset or "", {})).items() if k != "label"}
    levers.update({k: v for k, v in dict(nrr_pts=nrr_pts, win_rate_pct=win_rate_pct, cycle_days=cycle_days, price_pct=price_pct,
                                         cogs_pts=cogs_pts, hiring_pct=hiring_pct, opex_pct=opex_pct, raise_amount=raise_amount,
                                         raise_month=raise_month).items() if v is not None})
    baseline_levers, detail = {}, None
    delay = levers.pop("raise_delay_months", None)
    if delay:  # compare the planned round on time with the same round late
        planned = _scenario_levers(wh, "base")
        baseline_levers = {"raise_amount": planned.get("raise_amount", 0.0), "raise_month": planned.get("raise_month")}
        if planned.get("raise_month"):
            y, m = int(planned["raise_month"][:4]), int(planned["raise_month"][5:7]) - 1 + int(delay)
            levers.update(raise_amount=planned["raise_amount"], raise_month=f"{y + m // 12:04d}-{m % 12 + 1:02d}")
        detail = {"planned_close": planned.get("raise_month"), "delayed_close": levers.get("raise_month"), "raise_amount": planned.get("raise_amount")}
    if levers.pop("lose_largest", None):
        months_out = int(levers.pop("lose_in_months", 3))
        top = wh.query("""select customer_id, revenue from marts.fct_customer_revenue_monthly where month = ?::date
                          order by revenue desc limit 1""", [_month(None, wh)])
        if top:
            y, m = int(base["start_month"][:4]), int(base["start_month"][5:7]) - 1 + months_out
            levers.update(lost_mrr=float(top[0]["revenue"]), lost_month=f"{y + m // 12:04d}-{m % 12 + 1:02d}")
            detail = {"customer_id": top[0]["customer_id"], "mrr": float(top[0]["revenue"]), "leaves_in": levers["lost_month"],
                      "share_of_mrr": round(float(top[0]["revenue"]) / base["mrr"], 4) if base["mrr"] else None}
    baseline = fpa.stress_test(base, baseline_levers, int(months))
    scenario = fpa.stress_test(base, levers, int(months))
    rows = [{"month": b["month"], "base_revenue": b["revenue"], "scenario_revenue": s["revenue"], "base_cash": b["cash"],
             "scenario_cash": s["cash"], "base_ebitda": b["ebitda"], "scenario_ebitda": s["ebitda"], "base_arr": b["arr"],
             "scenario_arr": s["arr"], "scenario_new_arr": s["new_arr_booked"]} for b, s in zip(baseline["rows"], scenario["rows"])]
    return {"source": "finance_os.fpa.stress_test from fct_gl_monthly, fct_cash_monthly, fct_mrr_bridge_monthly, fct_pipeline, "
                      "fct_bookings_monthly, fct_forecast_monthly (base payroll and opex)",
            "row_count": len(rows), "rows": rows, "levers": scenario["levers"], "baseline": baseline["summary"],
            "scenario": scenario["summary"], "assumptions": {k: v for k, v in base.items() if k not in ("pipeline", "payroll", "other_opex")},
            "presets": {k: {**v, "note": PRESET_NOTES.get(k)} for k, v in STRESS_PRESETS.items()}, "preset": preset,
            "preset_detail": detail,
            "note": "Existing customers move at the trailing 6-month net rate, adjusted by NRR points; sales-led bookings come "
                    "from the open pipeline (probability x win-rate change, shifted by the cycle change), then the 12-month "
                    "bookings rate; new usage ramps over three months."}


def get_segment_pnl(wh, dimension="region", month=None, months=12):
    """Segment P&L by region or channel: this month's lines per segment and the monthly trend. Ties to the ledger."""
    m = _month(month, wh)
    rows = wh.query("""select segment, revenue, cogs, gross_margin, gross_margin_pct, cost_to_serve, contribution_margin,
                              revenue_share, allocated_opex, operating_income
                       from marts.fct_segment_pnl_monthly where dimension = ? and month = ?::date order by revenue desc""", [dimension, m])
    trend = wh.query("""select strftime(month, '%Y-%m') as month, segment, revenue, contribution_margin, operating_income
                        from marts.fct_segment_pnl_monthly where dimension = ? and month > ?::date - interval (?) month and month <= ?::date
                        order by month, segment""", [dimension, m, int(months), m])
    return _result(rows, "marts.fct_segment_pnl_monthly, dim_customer_geo", month=m[:7], dimension=dimension, trend=trend,
                   note="Revenue and COGS by customer; cost to serve = payment fees, support, success; remaining opex "
                        "allocated by drivers (platform by audio hours, sales by sales-led customers, services by project revenue, G&A by revenue). An Unallocated line ties each cut to the ledger.")


def get_consolidation(wh, month=None):
    """Consolidation worksheet for a closed month: each entity's P&L and balance sheet (subsidiaries translated to USD:
    P&L at the average rate, balance sheet at the closing rate), the intercompany eliminations, and the consolidated
    total. Also each subsidiary's monthly intercompany charge, payroll and CTA over 12 months."""
    m = _month(month, wh)
    ents = wh.query("select * from marts.dim_entity order by entity_id")
    cols = [e["entity_id"] for e in ents] + ["ELIM"]
    lines = wh.query("""select entity_id, account_id, account_name, account_type, rollup_name, balance_usd
                        from marts.fct_consolidation_monthly where month = ?::date""", [m])

    def sheet(types, natural):
        rows = {}
        for r in lines:
            if r["account_type"] not in types:
                continue
            k = (r["account_type"], r["account_id"])
            row = rows.setdefault(k, {"account_id": r["account_id"], "line": r["account_name"], "account_type": r["account_type"],
                                      "rollup": r["rollup_name"], **{c: 0.0 for c in cols}})
            sign = -1 if natural and r["account_type"] in ("revenue", "liability", "equity") else 1
            row[r["entity_id"]] += sign * float(r["balance_usd"] or 0)
        out = sorted(rows.values(), key=lambda x: (types.index(x["account_type"]), x["account_id"]))
        for r in out:
            r["consolidated"] = round(sum(r[c] for c in cols), 2)
            for c in cols:
                r[c] = round(r[c], 2)
        return out

    pl = sheet(["revenue", "cogs", "opex"], True)
    total = {"account_id": "", "line": "Operating income (before depreciation and tax)", "account_type": "total", "rollup": ""}
    for c in cols + ["consolidated"]:
        total[c] = round(sum(r[c] if r["account_type"] == "revenue" else -r[c] for r in pl if r["account_id"] != "6600"), 2)
    bs = sheet(["asset", "liability", "equity"], True)
    trend = wh.query("""select strftime(month, '%Y-%m') as month, entity_id,
                               sum(case when account_id = '4900' then -amount_usd else 0 end) as ic_charge,
                               sum(case when account_id in ('6000', '6010', '6020') then amount_usd else 0 end) as payroll
                        from marts.fct_gl_entity_monthly where entity_id <> 'US01'
                          and month > ?::date - interval 12 month and month <= ?::date group by 1, 2 order by 1, 2""", [m, m])
    cta = wh.query("""select strftime(month, '%Y-%m') as month, entity_id, -balance_usd as cta
                      from marts.fct_consolidation_monthly where account_id = '3900'
                        and month > ?::date - interval 12 month and month <= ?::date order by 1, 2""", [m, m])
    return {"source": "marts.fct_consolidation_monthly, fct_gl_entity_monthly, dim_entity", "month": m[:7], "entities": ents,
            "columns": cols, "row_count": len(pl), "rows": pl + [total], "balance_sheet": bs, "trend": trend, "cta": cta,
            "note": "Subsidiaries are cost-plus service providers to the parent; their charges (4900) and the parent's fees "
                    "(6900) eliminate, as do intercompany receivables and payables. Balance sheet translated at closing "
                    "rates; the difference is the cumulative translation adjustment (3900)."}


SWEEP_TARGET_WEEKS = 6     # operating account target: six weeks of outflows
SWEEP_MMF_BUFFER_WEEKS = 8  # money market keeps eight weeks of outflows before anything goes into T-bills


def get_contracts(wh, month=None, customer_id=None):
    """Committed-use contracts at a closed month end: RPO, current RPO, contracted ARR vs run-rate ARR, each contract's
    burn pace (usage vs commitment), projected shortfall / overage, the renewal base and revenue at risk, and the trend."""
    m = _month(month, wh)
    where, args = "month = ?::date", [m]
    if customer_id:
        where += " and customer_id = ?"
        args.append(customer_id)
    rows = wh.query(f"""select contract_id, customer_id, segment, billing_model, strftime(start_date, '%Y-%m-%d') as start_date,
                               strftime(end_date, '%Y-%m-%d') as end_date, contract_year, elapsed_months, current_commitment,
                               consumed_ytd, remaining_current, burn_pace, projected_shortfall, projected_overage,
                               rpo, crpo, days_to_renewal, in_renewal_window
                        from marts.fct_contract_revenue_monthly where {where} order by rpo desc""", args)
    trend = wh.query("""select strftime(f.month, '%Y-%m') as month, sum(f.contracted_arr) as contracted_arr, sum(f.rpo) as rpo,
                               sum(f.crpo) as crpo, sum(f.projected_shortfall) as projected_shortfall,
                               sum(f.projected_overage) as projected_overage,
                               (select max(k.value) from marts.fct_kpi_monthly k where k.month = f.month and k.metric_name = 'arr') as run_rate_arr
                        from marts.fct_contract_revenue_monthly f
                        where f.month <= ?::date group by f.month order by f.month""", [m])
    renewals = [r for r in rows if r["in_renewal_window"]]
    at_risk = [r for r in renewals if (r["burn_pace"] or 0) < 0.9]

    def total(k, rs=None):
        return round(sum(float(r[k] or 0) for r in (rows if rs is None else rs)), 2)

    summary = {"contracts": len(rows), "rpo": total("rpo"), "crpo": total("crpo"), "contracted_arr": total("current_commitment"),
               "run_rate_arr": next((t["run_rate_arr"] for t in trend if t["month"] == m[:7]), None),
               "projected_shortfall": total("projected_shortfall"), "projected_overage": total("projected_overage"),
               "renewal_base_180d": total("current_commitment", renewals),
               "revenue_at_risk": total("current_commitment", at_risk),
               "prepaid_credits_unused": total("remaining_current", [r for r in rows if r["billing_model"] == "prepaid_credits"])}
    return _result(rows, "marts.fct_contract_revenue_monthly", month=m[:7], summary=summary, trend=trend,
                   note="RPO = commitment left this contract year + later years; cRPO = the part due in 12 months. "
                        "Revenue at risk = commitments renewing within 180 days on contracts burning below 90% of pace.")


def get_driver_bridges(wh, month=None):
    """Why things moved this month: gross margin bridge (volume, price, cost to serve, services), net burn bridge
    (revenue, cost of revenue, payroll, other opex, capex, working capital), cloud cost bridge by product (demand,
    efficiency, rate, shared, commitment) and the headcount bridge (opening, hires, leavers, closing) by department."""
    m = _month(month, wh)
    steps = wh.query("""select bridge, step_order, step, amount from marts.fct_margin_burn_bridge_monthly
                        where month = ?::date order by bridge, step_order""", [m])
    cloud = wh.query("""select product_id, opening, demand, efficiency, rate, shared, commitment, other_cloud, closing
                        from marts.fct_cloud_cost_bridge_monthly where month = ?::date order by product_id = 'all', closing desc""", [m])
    hc = wh.query("""select department_id, opening, hires, leavers, closing, hires_ytd, leavers_ytd
                     from marts.fct_headcount_bridge where month = ?::date order by closing desc""", [m])
    return _result(steps, "marts.fct_margin_burn_bridge_monthly, fct_cloud_cost_bridge_monthly, fct_headcount_bridge",
                   month=m[:7], gross_margin=[s for s in steps if s["bridge"] == "gross_margin"],
                   net_burn=[s for s in steps if s["bridge"] == "net_burn"], cloud_cost=cloud, headcount=hc,
                   note="Bridges add up: prior month + steps = this month (tested).")


def get_gpu_efficiency(wh, months=12):
    """GPU efficiency by month and GPU type: idle share, idle cost, commitment coverage and utilization, unused commit
    cost; plus open vendor purchase commitments and the magic number trend."""
    rows = wh.query("""select strftime(month, '%Y-%m') as month, gpu_type, gpu_hours, idle_hours, idle_share, idle_cost,
                              committed_hours, commit_coverage, commit_utilization, unused_commit_cost
                       from marts.fct_gpu_efficiency_monthly
                       where month > (select max(month) from marts.fct_gpu_efficiency_monthly) - interval (?) month
                       order by month, gpu_type""", [int(months)])
    commitments = wh.query("""select vendor_id, contract_id, strftime(end_date, '%Y-%m-%d') as end_date, committed_gpu_type,
                                     committed_hours_month, rate, committed_spend_month, months_remaining, remaining_commitment
                              from marts.fct_vendor_commitments order by remaining_commitment desc""")
    magic = wh.query("""select strftime(month, '%Y-%m') as month, magic_number from marts.fct_efficiency_quarterly
                        where magic_number is not null order by month""")
    return _result(rows, "marts.fct_gpu_efficiency_monthly, fct_vendor_commitments, fct_efficiency_quarterly",
                   commitments=commitments, magic_number=magic,
                   note="Idle share = warm-pool GPU time / all GPU time. Coverage = committed / used hours.")


def get_cost_anomalies(wh, days=90):
    """Daily cloud and GPU cost anomalies (more than 3 standard deviations and at least $500 from the trailing 28 days)
    with the owning team."""
    rows = wh.query("""select strftime(spend_date, '%Y-%m-%d') as spend_date, vendor_id, service, team, cost, expected,
                              deviation, z_score, direction
                       from marts.fct_cost_anomalies
                       where spend_date > (select max(spend_date) from marts.fct_tech_spend_daily) - interval (?) day
                       order by spend_date desc""", [int(days)])
    return _result(rows, "marts.fct_cost_anomalies", days=int(days),
                   note="No rows means no day broke 3 standard deviations and $500 in the window.")


def get_procurement(wh, months=12):
    """Procurement: savings won each month (negotiated GPU rate reductions on hours used, early-payment discounts),
    year-to-date totals, and the remaining purchase commitments by vendor contract."""
    rows = wh.query("""select strftime(month, '%Y-%m') as month, rate_savings, early_pay_discounts, total_savings
                       from marts.fct_procurement_savings_monthly
                       where month > (select max(month) from marts.fct_procurement_savings_monthly) - interval (?) month
                       order by month""", [int(months)])
    ytd = wh.query("""select sum(rate_savings) as rate_savings, sum(early_pay_discounts) as early_pay_discounts,
                             sum(total_savings) as total_savings
                      from marts.fct_procurement_savings_monthly
                      where extract(year from month) = (select extract(year from max(month)) from marts.fct_procurement_savings_monthly)""")
    commitments = wh.query("""select vendor_id, contract_id, strftime(end_date, '%Y-%m-%d') as end_date, months_remaining,
                                     committed_spend_month, remaining_commitment
                              from marts.fct_vendor_commitments where remaining_commitment > 0 order by remaining_commitment desc""")
    return _result(rows, "marts.fct_procurement_savings_monthly, fct_vendor_commitments", ytd=ytd[0] if ytd else {},
                   commitments=commitments)



def get_ceo_one_pager(wh):
    """One page for the CEO: the headline numbers, then the top five opportunities and top five risks across the
    company, each sized in dollars, with the owner and where to look. Candidates come from contracts, pricing,
    procurement, GPU efficiency, collections, customer health, margins, budget and scenarios; ranked by dollars."""
    m = _month(None, wh)
    k = {r["metric_name"]: r["value"] for r in wh.query("select metric_name, value from marts.fct_kpi_monthly where month = ?::date", [m])}
    c = get_contracts(wh)["summary"]
    opp, risk = [], []

    def add(lst, title, amount, detail, owner, page):
        if amount and amount > 0:
            lst.append({"title": title, "amount": round(float(amount), 2), "detail": detail, "owner": owner, "page": page})

    add(opp, "Upsize renewals running over commitment", c["projected_overage"],
        "Usage at run rate above committed minimums: re-paper at a higher commit before renewal.", "CRO", "contracts")
    for r in wh.query("""select scenario, note, delta_gross_margin from marts.fct_price_simulation
                         where delta_gross_margin > 0 order by delta_gross_margin desc limit 1"""):
        add(opp, f"Pricing: {r['note'].split(';')[0]}", r["delta_gross_margin"], "Annual gross-margin gain in the price simulation after volume loss.", "CEO / CFO", "pricing")
    leak = wh.query("""select sum(discount_amount) * 12 / 3 as v from marts.fct_discount_leakage
                       where is_over_policy and month > ?::date - interval 3 month and month <= ?::date""", [m, m])[0]["v"]
    add(opp, "Stop discounts above policy", leak, "Discount over the approved band, annualized from the last 3 months.", "CRO", "pricing")
    idle = wh.query("""select sum(idle_cost) * 12 / 3 as v from marts.fct_gpu_efficiency_monthly
                       where month > ?::date - interval 3 month and month <= ?::date""", [m, m])[0]["v"]
    add(opp, "Cut idle GPU warm pool by half", (idle or 0) / 2, "Idle (warm-pool) GPU cost, annualized; half is the realistic target.", "VP Engineering", "spend")
    overdue = wh.query("select sum(balance) as v from marts.fct_ar_invoices where balance > 0 and days_past_due > 30")[0]["v"]
    add(opp, "Collect AR more than 30 days past due", overdue, "Cash already earned and overdue.", "Controller", "ar")

    add(risk, "Renewals burning below commitment", c["revenue_at_risk"],
        "Commitments renewing in 180 days on contracts under 90% of pace: likely to downsize or churn.", "CRO", "contracts")
    add(risk, "Commitment shortfalls this contract year", c["projected_shortfall"],
        "True-ups or expiring credits customers will dispute; a churn signal.", "CS lead", "contracts")
    at_risk = wh.query("select sum(arr) as v, count(*) as n from marts.fct_customer_health where health = 'at_risk'")[0]
    add(risk, f"{at_risk['n'] or 0} customer(s) flagged at risk", at_risk["v"], "ARR of customers with falling usage, overdue balances or disputes.", "CS lead", "growth")
    below = wh.query("""select sum(revenue * gross_margin_floor_pct - gross_margin) * 12 as v, count(*) as n
                        from marts.fct_customer_margin_monthly where month = ?::date and is_below_floor""", [m])[0]
    add(risk, f"{below['n'] or 0} customer(s) below the margin floor", below["v"], "Annualized gross margin short of each product floor.", "CFO", "revenue")
    sc = {s_["scenario"]: s_ for s_ in scenario_summaries(wh)}
    if "base" in sc and "downside" in sc:
        add(risk, "Downside scenario", sc["base"]["revenue_next_12m"] - sc["downside"]["revenue_next_12m"],
            "Next-12-month revenue lost if NRR drops 5 points, win rate falls a quarter and deals slip a month.", "CFO", "plan")
    bva = wh.query("""select sum(fy_fav_variance) as v from marts.fct_bva_monthly where month = ?::date""", [m]) if wh.query(
        "select 1 from information_schema.columns where table_name = 'fct_bva_monthly' and column_name = 'fy_fav_variance'") else []
    if bva and bva[0]["v"] is not None and float(bva[0]["v"]) < 0:
        add(risk, "Full year landing below budget", -float(bva[0]["v"]), "Full-year forecast vs budget at the current run rate.", "CFO", "budget")
    shortfall = wh.query("""select sum(unused_commit_cost) * 12 / 3 as v from marts.fct_gpu_efficiency_monthly
                            where month > ?::date - interval 3 month and month <= ?::date""", [m, m])[0]["v"]
    add(risk, "Paying for unused GPU commitment", shortfall, "Committed GPU hours not used, annualized.", "VP Engineering", "spend")

    vc = get_vendor_concentration(wh)
    if vc["rows"] and vc["summary"]["top1_share"] and vc["summary"]["top1_share"] > 0.5:
        top = vc["rows"][0]
        add(risk, f"Single-vendor dependence: {top['vendor_id']} is {top['share']:.0%} of vendor spend", top["spend"],
            f"Trailing 12-month spend with one vendor (HHI {vc['summary']['hhi']:,}); price or capacity changes hit margin directly.",
            "VP Engineering / CFO", "drivers")
    opp.sort(key=lambda r: -r["amount"])
    risk.sort(key=lambda r: -r["amount"])
    headline = {"month": m[:7], "revenue": k.get("revenue"), "arr": k.get("arr"), "gross_margin_pct": k.get("gross_margin_pct"),
                "net_burn": k.get("net_burn"), "closing_cash": k.get("closing_cash"), "nrr": k.get("nrr"),
                "rpo": c["rpo"], "contracted_arr": c["contracted_arr"],
                "runway_base": sc.get("base", {}).get("runway_months"), "ebitda_next_12m": sc.get("base", {}).get("ebitda_next_12m")}
    return _result(opp[:5] + risk[:5], "get_contracts, fct_price_simulation, fct_discount_leakage, fct_gpu_efficiency_monthly, "
                   "fct_ar_invoices, fct_customer_health, fct_customer_margin_monthly, fct_bva_monthly, driver engine scenarios",
                   month=m[:7], headline=headline, opportunities=opp[:5], risks=risk[:5],
                   note="Ranked by dollars (annualized where the source is monthly). Each item names an owner and the page to open.")


def get_driver_tree(wh, month=None):
    """The value driver tree for a closed month vs the prior month: EBITDA = revenue - cost of revenue - opex;
    revenue = usage (audio hours x revenue per hour) + services; audio hours = active customers x hours per customer;
    cost of revenue = audio hours x cost per hour + services cost; opex = payroll (headcount x cost per head) + other."""
    m = _month(month, wh)
    rows = wh.query("""
        with gl as (
            select month,
                   sum(case when account_type = 'revenue' then natural_amount else 0 end) as revenue,
                   sum(case when account_id = '4100' then natural_amount else 0 end) as services,
                   sum(case when account_type = 'cogs' then natural_amount else 0 end) as cogs,
                   sum(case when account_type = 'opex' and account_id in ('6000', '6010', '6020') then natural_amount else 0 end) as payroll,
                   sum(case when account_type = 'opex' and account_id not in ('6000', '6010', '6020', '6600') then natural_amount else 0 end) as other_opex
            from marts.fct_gl_monthly where month in (?::date, ?::date - interval 1 month) group by 1),
        ue as (
            select month, sum(audio_hours) as hours, sum(cogs) as usage_cogs, count(distinct case when revenue > 0 then customer_id end) as customers
            from marts.fct_unit_economics_monthly where month in (?::date, ?::date - interval 1 month) group by 1),
        hc as (
            select month, sum(headcount) as headcount from marts.fct_headcount_monthly
            where month in (?::date, ?::date - interval 1 month) group by 1)
        select gl.*, ue.hours, ue.usage_cogs, ue.customers, hc.headcount
        from gl left join ue using (month) left join hc using (month) order by month""", [m, m, m, m, m, m])
    if len(rows) < 2:
        return _result([], "marts.fct_gl_monthly", note="Need two closed months.")
    prev, cur = rows[0], rows[1]

    def v(r, key):
        f = lambda x: float(x or 0)  # noqa: E731
        usage = f(r["revenue"]) - f(r["services"])
        return {
            "ebitda": f(r["revenue"]) - f(r["cogs"]) - f(r["payroll"]) - f(r["other_opex"]),
            "revenue": f(r["revenue"]), "usage_revenue": usage, "services_revenue": f(r["services"]),
            "audio_hours": f(r["hours"]), "revenue_per_hour": usage / f(r["hours"]) if f(r["hours"]) else 0,
            "active_customers": f(r["customers"]), "hours_per_customer": f(r["hours"]) / f(r["customers"]) if f(r["customers"]) else 0,
            "cost_of_revenue": f(r["cogs"]), "usage_cost": f(r["usage_cogs"]),
            "cost_per_hour": f(r["usage_cogs"]) / f(r["hours"]) if f(r["hours"]) else 0,
            "other_cost_of_revenue": f(r["cogs"]) - f(r["usage_cogs"]),
            "opex": f(r["payroll"]) + f(r["other_opex"]), "payroll": f(r["payroll"]), "other_opex": f(r["other_opex"]),
            "headcount": f(r["headcount"]), "cost_per_head": f(r["payroll"]) / f(r["headcount"]) if f(r["headcount"]) else 0,
        }[key]

    tree = [("ebitda", "EBITDA", None, "usd"), ("revenue", "Revenue", "ebitda", "usd"),
            ("usage_revenue", "Usage revenue", "revenue", "usd"), ("audio_hours", "Audio hours", "usage_revenue", "count"),
            ("active_customers", "Active customers", "audio_hours", "count"), ("hours_per_customer", "Hours per customer", "audio_hours", "count"),
            ("revenue_per_hour", "Revenue per hour", "usage_revenue", "price"), ("services_revenue", "Services revenue", "revenue", "usd"),
            ("cost_of_revenue", "Cost of revenue", "ebitda", "usd"), ("usage_cost", "Usage cost (GPU, cloud)", "cost_of_revenue", "usd"),
            ("cost_per_hour", "Cost per audio hour", "usage_cost", "price"), ("other_cost_of_revenue", "Services and other cost", "cost_of_revenue", "usd"),
            ("opex", "Operating expenses", "ebitda", "usd"), ("payroll", "Payroll", "opex", "usd"),
            ("headcount", "Headcount", "payroll", "count"), ("cost_per_head", "Cost per head", "payroll", "usd"),
            ("other_opex", "Other opex", "opex", "usd")]
    depth = {}
    out = []
    for key, label, parent, unit in tree:
        depth[key] = 0 if parent is None else depth[parent] + 1
        now, before = v(cur, key), v(prev, key)
        out.append({"node": key, "label": label, "parent": parent, "depth": depth[key], "unit": unit,
                    "value": round(now, 4), "prior": round(before, 4), "change": round(now - before, 4),
                    "change_pct": round(now / before - 1, 4) if before else None})
    # how much each first-level driver moved EBITDA (costs count negative)
    sign = {"revenue": 1, "cost_of_revenue": -1, "opex": -1}
    impact = [{"driver": r["label"], "ebitda_impact": round(sign[r["node"]] * r["change"], 2)} for r in out if r["node"] in sign]
    return _result(out, "marts.fct_gl_monthly, fct_unit_economics_monthly, fct_headcount_monthly", month=m[:7],
                   prior_month=str(prev["month"])[:7], ebitda_impact=impact,
                   note="Each node is computed from the ledger and operating data for the two months; children multiply or add up to their parent.")


EXPLORE_GROUPS = {"month": "e.entry_month", "account": "l.account_id || ' ' || a.account_name", "account_type": "a.account_type",
                  "rollup": "a.rollup", "department": "coalesce(l.department_id, 'NONE')", "entity": "coalesce(l.entity_id, 'US01')",
                  "customer": "l.customer_id", "vendor": "l.vendor_id", "entry_type": "e.entry_type"}


def explore_ledger(wh, start_month=None, end_month=None, account_type=None, account=None, rollup=None, department=None,
                   entity=None, customer_id=None, vendor_id=None, entry_type=None, text=None, group_by="account", top=25):
    """Ask the ledger anything specific: every journal line in a month range, narrowed by any mix of account type,
    account (id or name), rollup, department, legal entity, customer, vendor, entry type or memo text; totals grouped by
    one dimension, the monthly trend of the selection, and the largest lines behind it. Amounts are natural sign
    (revenue and liabilities positive as credits, costs and assets positive as debits)."""
    if group_by not in EXPLORE_GROUPS:
        return _result([], "explore", note=f"group_by must be one of {', '.join(EXPLORE_GROUPS)}")
    end = _month(end_month, wh)
    start = _month(start_month, wh) if start_month else str(wh.query("select min(entry_month) as m from staging.stg_erp__journal_entries")[0]["m"])[:10]
    where = ["e.entry_month between ?::date and ?::date"]
    args = [start, end]
    for col, val in (("a.account_type", account_type), ("a.rollup", rollup), ("l.department_id", department), ("coalesce(l.entity_id, 'US01')", entity),
                     ("l.customer_id", customer_id), ("l.vendor_id", vendor_id), ("e.entry_type", entry_type)):
        if val:
            where.append(f"lower({col}) = lower(?)")
            args.append(val)
    if account:
        where.append("(l.account_id = ? or lower(a.account_name) like lower(?))")
        args += [account, f"%{account}%"]
    if text:
        where.append("lower(e.memo) like lower(?)")
        args.append(f"%{text}%")
    sign = "case when a.account_type in ('revenue', 'liability', 'equity') then -l.amount else l.amount end"
    base = f"""from staging.stg_erp__journal_lines l
               join staging.stg_erp__journal_entries e using (entry_id)
               join marts.dim_gl_account a using (account_id)
               where {' and '.join(where)}"""
    g = EXPLORE_GROUPS[group_by]
    alias = {"customer": "customer_id", "vendor": "vendor_id", "department": "department_id", "entity": "entity_id"}.get(group_by, group_by)
    rows = wh.query(f"""select {g if group_by != 'month' else "strftime(e.entry_month, '%Y-%m')"} as {alias}, sum({sign}) as amount,
                               count(*) as lines from (select * from staging.stg_erp__journal_lines) l
                        join staging.stg_erp__journal_entries e using (entry_id)
                        join marts.dim_gl_account a using (account_id)
                        where {' and '.join(where)}
                        group by 1 order by {'1' if group_by == 'month' else 'abs(sum(' + sign + ')) desc'}""", args)
    trend = wh.query(f"select strftime(e.entry_month, '%Y-%m') as month, sum({sign}) as amount {base} group by 1 order by 1", args)
    lines = wh.query(f"""select strftime(e.entry_date, '%Y-%m-%d') as entry_date, e.entry_id, e.entry_type, e.memo, l.account_id,
                                a.account_name, l.department_id, l.entity_id, l.customer_id, l.vendor_id, {sign} as amount
                         {base} order by abs({sign}) desc limit ?""", args + [int(top)])
    total = round(sum(float(r["amount"] or 0) for r in rows), 2)
    return _result(rows, "staging.stg_erp__journal_lines + stg_erp__journal_entries + dim_gl_account", start=start[:7], end=end[:7],
                   group_by=group_by, total=total, line_count=sum(int(r["lines"]) for r in rows), trend=trend, top_lines=lines,
                   filters={k: v for k, v in dict(account_type=account_type, account=account, rollup=rollup, department=department,
                                                   entity=entity, customer_id=customer_id, vendor_id=vendor_id, entry_type=entry_type,
                                                   text=text).items() if v},
                   note="Natural sign: revenue, liabilities and equity are positive as credits; costs and assets as debits.")


def explore_options(wh):
    """The values each explore filter can take (for pickers)."""
    q = lambda sql: [r["v"] for r in wh.query(sql)]  # noqa: E731
    return {"source": "staging + marts dimensions", "row_count": 0, "rows": [],
            "accounts": wh.query("select account_id, account_name, account_type, rollup from marts.dim_gl_account order by account_id"),
            "account_types": q("select distinct account_type as v from marts.dim_gl_account order by 1"),
            "rollups": q("select distinct rollup as v from marts.dim_gl_account where rollup is not null order by 1"),
            "departments": q("select distinct department_id as v from staging.stg_erp__journal_lines where department_id is not null order by 1"),
            "entities": q("select distinct coalesce(entity_id, 'US01') as v from staging.stg_erp__journal_lines order by 1"),
            "customers": q("select distinct customer_id as v from staging.stg_erp__journal_lines where customer_id is not null order by 1"),
            "vendors": q("select distinct vendor_id as v from staging.stg_erp__journal_lines where vendor_id is not null order by 1"),
            "entry_types": q("select distinct entry_type as v from staging.stg_erp__journal_entries order by 1"),
            "months": q("select distinct strftime(entry_month, '%Y-%m') as v from staging.stg_erp__journal_entries order by 1"),
            "metrics": wh.query("select metric_name, label, unit from seeds.metric_catalog order by label")}


def get_vendor_concentration(wh, months=12):
    """How dependent we are on a few vendors: billed spend by vendor over the trailing months, each vendor's share and
    the cumulative share, top-1 and top-3 share, the Herfindahl-Hirschman index (HHI: sum of squared shares x 10,000;
    above 2,500 = highly concentrated), and what is still committed to each vendor and when its contract ends."""
    m = _month(None, wh)
    rows = wh.query("""select l.vendor_id, sum(l.credit) as spend, count(distinct l.entry_id) as bills
                       from staging.stg_erp__journal_lines l join staging.stg_erp__journal_entries e using (entry_id)
                       where l.account_id = '2000' and l.vendor_id is not null and l.credit > 0
                         and e.entry_month > ?::date - interval (?) month and e.entry_month <= ?::date
                       group by 1 order by 2 desc""", [m, int(months), m])
    total = sum(float(r["spend"]) for r in rows) or 1
    commit = {r["vendor_id"]: r for r in wh.query("""select vendor_id, sum(remaining_commitment) as remaining_commitment,
                                                            strftime(max(end_date), '%Y-%m-%d') as contract_end
                                                     from marts.fct_vendor_commitments group by 1""")}
    run = 0.0
    for r in rows:
        share = float(r["spend"]) / total
        run += share
        r["share"], r["cumulative_share"] = round(share, 4), round(run, 4)
        c = commit.get(r["vendor_id"], {})
        r["remaining_commitment"], r["contract_end"] = c.get("remaining_commitment"), c.get("contract_end")
    hhi = round(sum((float(r["spend"]) / total * 100) ** 2 for r in rows))
    return _result(rows, "staging.stg_erp__journal_lines (bills booked to AP), marts.fct_vendor_commitments", months=int(months),
                   summary={"vendors": len(rows), "total_spend": round(total, 2), "top1_share": rows[0]["share"] if rows else None,
                            "top3_share": round(sum(r["share"] for r in rows[:3]), 4), "hhi": hhi,
                            "concentration": "high" if hhi > 2500 else "moderate" if hhi > 1500 else "low"},
                   note="HHI above 2,500 is highly concentrated (US DOJ guideline); a single critical vendor needs an exit plan.")


DRIVER_SERIES = {
    "audio_hours": "Audio hours", "active_customers": "Active customers", "revenue_per_hour": "Revenue per hour",
    "cost_per_hour": "Cost per audio hour", "revenue": "Revenue", "cost_of_revenue": "Cost of revenue",
    "payroll": "Payroll", "other_opex": "Other opex", "headcount": "Headcount", "gpu_idle_share": "Idle GPU share",
    "ebitda": "EBITDA",
}


def get_driver_correlation(wh, months=18):
    """How drivers move together: month-over-month changes of the operating drivers over the trailing months and the
    Pearson correlation of every pair (1 = always move together, -1 = opposite, 0 = unrelated), with the strongest
    pairs. Correlation is not causation: use it to find which drivers to model jointly and which to watch."""
    rows = wh.query("""
        with gl as (
            select month,
                   sum(case when account_type = 'revenue' then natural_amount else 0 end) as revenue,
                   sum(case when account_type = 'cogs' then natural_amount else 0 end) as cost_of_revenue,
                   sum(case when account_id in ('6000', '6010', '6020') then natural_amount else 0 end) as payroll,
                   sum(case when account_type = 'opex' and account_id not in ('6000', '6010', '6020', '6600') then natural_amount else 0 end) as other_opex
            from marts.fct_gl_monthly where month <= (select max(month) from marts.fct_kpi_monthly) group by 1),
        ue as (select month, sum(audio_hours) as audio_hours, sum(revenue) as usage_revenue, sum(cogs) as usage_cogs,
                      count(distinct case when revenue > 0 then customer_id end) as active_customers
               from marts.fct_unit_economics_monthly group by 1),
        hc as (select month, sum(headcount) as headcount from marts.fct_headcount_monthly group by 1),
        gpu as (select month, sum(idle_hours) / nullif(sum(gpu_hours), 0) as gpu_idle_share from marts.fct_gpu_efficiency_monthly group by 1)
        select strftime(gl.month, '%Y-%m') as month, gl.revenue, gl.cost_of_revenue, gl.payroll, gl.other_opex,
               gl.revenue - gl.cost_of_revenue - gl.payroll - gl.other_opex as ebitda,
               ue.audio_hours, ue.active_customers, ue.usage_revenue / nullif(ue.audio_hours, 0) as revenue_per_hour,
               ue.usage_cogs / nullif(ue.audio_hours, 0) as cost_per_hour, hc.headcount, gpu.gpu_idle_share
        from gl left join ue using (month) left join hc using (month) left join gpu using (month)
        order by 1""")[-(int(months) + 1):]
    keys = list(DRIVER_SERIES)
    changes = []
    for prev, cur in zip(rows, rows[1:]):
        ch = {"month": cur["month"]}
        for k in keys:
            a, b = prev.get(k), cur.get(k)
            if k in ("ebitda",):  # can cross zero: use the change in dollars
                ch[k] = None if a is None or b is None else float(b) - float(a)
            else:
                ch[k] = None if not a or b is None else float(b) / float(a) - 1
        changes.append(ch)

    def corr(x, y):
        pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
        if len(pairs) < 6:
            return None
        n = len(pairs)
        mx, my = sum(a for a, _ in pairs) / n, sum(b for _, b in pairs) / n
        sx = sum((a - mx) ** 2 for a, _ in pairs) ** 0.5
        sy = sum((b - my) ** 2 for _, b in pairs) ** 0.5
        return None if not sx or not sy else round(sum((a - mx) * (b - my) for a, b in pairs) / (sx * sy), 3)

    series = {k: [c[k] for c in changes] for k in keys}
    matrix, pairs = [], []
    for i, a in enumerate(keys):
        row = {"driver": DRIVER_SERIES[a]}
        for j, b in enumerate(keys):
            r = 1.0 if a == b else corr(series[a], series[b])
            row[b] = r
            if j > i and r is not None:
                pairs.append({"driver_a": DRIVER_SERIES[a], "driver_b": DRIVER_SERIES[b], "correlation": r,
                              "strength": "strong" if abs(r) >= 0.7 else "moderate" if abs(r) >= 0.4 else "weak"})
        matrix.append(row)
    pairs.sort(key=lambda x: -abs(x["correlation"]))
    return _result(matrix, "marts.fct_gl_monthly, fct_unit_economics_monthly, fct_headcount_monthly, fct_gpu_efficiency_monthly",
                   columns=[{"key": k, "label": v} for k, v in DRIVER_SERIES.items()], strongest_pairs=pairs[:10],
                   months=len(changes), changes=changes,
                   note="Correlation of month-over-month % changes (EBITDA in dollars). Not causation; needs at least 6 months.")


def get_decisions_needed(wh):
    """The situations that need a leadership decision now, each with the evidence behind it, the owner and the deadline
    (no canned recommendation: ask the assistant to reason one from the evidence). Built from rules over contracts, vendor concentration, forecast bias, the funding plan, runway,
    covenants and the margin floor, so the list changes as the numbers do."""
    out = []
    c = get_contracts(wh)
    at_risk = [r for r in c["rows"] if r["in_renewal_window"] and (r["burn_pace"] or 0) < 0.9]
    if at_risk:
        worst = min(at_risk, key=lambda r: r["days_to_renewal"])
        out.append({"decision": "Renewals burning below commitment",
                    "evidence": f"{len(at_risk)} contract(s) renewing within 180 days run below 90% of pace; "
                                f"{_usd_text(c['summary']['revenue_at_risk'])} of commitment at risk. First up: {worst['contract_id']} in {worst['days_to_renewal']} days.",
                    "owner": "CRO", "by": f"{worst['days_to_renewal']} days", "amount": c["summary"]["revenue_at_risk"],
                    "contracts_at_risk": len(at_risk), "first_contract": worst["contract_id"], "days_to_first": worst["days_to_renewal"]})
    vc = get_vendor_concentration(wh)
    if vc["rows"] and (vc["summary"]["top1_share"] or 0) > 0.5:
        top = vc["rows"][0]
        out.append({"decision": f"Single-vendor dependence: {top['vendor_id']} renewal",
                    "evidence": f"{top['vendor_id']} is {top['share']:.0%} of vendor spend (HHI {vc['summary']['hhi']:,}); "
                                f"{_usd_text(top['remaining_commitment'] or 0)} still committed, contract ends {top['contract_end'] or 'n/a'}.",
                    "owner": "VP Engineering / CFO", "by": top["contract_end"] or "next renewal", "amount": top["spend"],
                    "vendor_share": top["share"], "hhi": vc["summary"]["hhi"], "remaining_commitment": top["remaining_commitment"]})
    fe = get_forecast_error_by_driver(wh)
    ex = next((x for x in fe["summary"] if x["driver"] == "existing_customers"), None)
    if ex and abs(ex["bias"]) > 0.02 * (fe["rows"][0]["actual_revenue"] if fe["rows"] else 1):
        out.append({"decision": "Forecast running off on existing customers",
                    "evidence": f"Forecasts ran {_usd_text(abs(ex['bias']))} a month {'high' if ex['bias'] > 0 else 'low'} on existing customers "
                                f"over the last {fe['versions']} closes ({ex['share_of_abs_ebitda_error']:.0%} of forecast error).",
                    "owner": "VP Finance", "by": "next forecast", "amount": abs(ex["bias"]) * 12,
                    "monthly_bias": ex["bias"], "share_of_error": ex["share_of_abs_ebitda_error"]})
    sc = {x["scenario"]: x for x in scenario_summaries(wh)}
    base = sc.get("base")
    fr = wh.query("select raise_amount, close_month from seeds.fundraise_scenarios where scenario = 'base'")
    if base and fr:
        need = base["runway_months"] is not None and base["runway_months"] < 24
        out.append({"decision": "Funding plan vs runway",
                    "evidence": (f"Base plan: {_usd_text(fr[0]['raise_amount'])} round in {str(fr[0]['close_month'])[:7]}. Without it, "
                                 + (f"cash runs out in {base['runway_months']} months." if need else "cash does not run out within five years")
                                 + f"; base EBITDA next 12 months {_usd_text(base['ebitda_next_12m'])}."),
                    "owner": "CEO / CFO", "by": str(fr[0]["close_month"])[:7], "amount": fr[0]["raise_amount"],
                    "runway_months": base["runway_months"], "ebitda_next_12m": base["ebitda_next_12m"]})
    below = wh.query("""select count(*) as n, sum(revenue * gross_margin_floor_pct - gross_margin) * 12 as v
                        from marts.fct_customer_margin_monthly where month = ?::date and is_below_floor""", [_month(None, wh)])[0]
    if below["n"]:
        out.append({"decision": "Customers below the margin floor",
                    "evidence": f"{below['n']} customer(s) below their product margin floor, {_usd_text(below['v'])} a year short of it.",
                    "owner": "CFO / CRO", "by": "next renewal", "amount": below["v"], "customers": below["n"]})
    cov = wh.query("""select rule_id, description, min(month) as m from marts.fct_treasury_covenants
                      where status = 'breach' and month >= (select max(month) from marts.fct_kpi_monthly) group by 1, 2""")
    for r in cov:
        out.append({"decision": f"Covenant {r['rule_id']} breach", "evidence": f"{r['description']}: breach from {str(r['m'])[:7]}.",
                    "owner": "CFO", "by": str(r["m"])[:7], "amount": None})
    return _result(out, "get_contracts, get_vendor_concentration, get_forecast_error_by_driver, driver engine scenarios, "
                        "fct_customer_margin_monthly, fct_treasury_covenants",
                   note="Rules over the governed numbers; each decision names the evidence, the options and an owner.")


def _ttm_statements(wh):
    """Trailing-12-month income statement and the latest balance sheet, from the three-statement financials."""
    fs = get_financial_statements(wh, period="month", periods=12)
    cols = [c for c in fs["rows"][0] if c[:2] == "20"]
    line = {}
    for r in fs["rows"]:
        if r.get("line") and r["line"] not in line:
            line[r["line"]] = r
    ttm = lambda name: sum(float(line[name].get(c) or 0) for c in cols) if name in line else 0.0  # noqa: E731
    bal = lambda name: float(line[name].get(cols[-1]) or 0) if name in line else 0.0  # noqa: E731
    liabilities = {"accounts_payable": bal("Accounts payable"), "accrued_payroll_taxes": bal("Payroll taxes payable"),
                   "accrued_benefits": bal("Benefits and deductions payable")}
    return {
        "period": f"{cols[0]} to {cols[-1]}", "end_month": cols[-1],
        "revenue": ttm("Total revenue"), "cogs": ttm("Total cost of revenue"), "ebitda": ttm("EBITDA"),
        "depreciation": ttm("Depreciation"), "ebit": ttm("Operating income (EBIT)"), "net_income": ttm("Net income"),
        "capex": -ttm("Capital expenditure"), "cfo": ttm("Cash from operations"), "interest": 0.0,
        "cash": bal("Cash - operating"), "receivables": bal("Accounts receivable"),
        "fixed_assets_net": bal("Fixed assets at cost") + bal("Accumulated depreciation"),
        "total_assets": bal("Total assets"), "payables": bal("Accounts payable"),
        "current_assets": bal("Cash - operating") + bal("Accounts receivable"),
        "current_liabilities": bal("Total liabilities"), "total_liabilities": bal("Total liabilities"),
        "equity": bal("Total equity"), "liabilities": liabilities,
        "receivables_open": cols and float(line.get("Accounts receivable", {}).get(cols[0]) or 0),
        "nwc_open": None,
    }


def company_wacc(wh):
    """The company's WACC (CAPM cost of equity on the peer beta, relevered at the target debt-equity ratio); the
    default discount rate for business cases and projects."""
    from finance_os import corpfin as cf
    cma = _cma(wh)
    t = _us_combined(_tax_rates(wh))
    de = cma.get("target_debt_to_equity", 0.0)
    ke = cf.capm(cma["risk_free_rate"], cf.relever_beta(cma["unlevered_beta"], de, t), cma["market_risk_premium"]) + cma.get("private_company_premium", 0.0)
    return cf.wacc(1.0, de, ke, cma["pre_tax_cost_of_debt"], t)["wacc"]


def _cma(wh):
    return {r["item"]: float(r["value"]) for r in wh.query("select item, value from seeds.capital_market_assumptions")}


def _tax_rates(wh):
    out = {}
    for r in wh.query("select entity_id, jurisdiction, rate, regime from seeds.corporate_tax_rates"):
        out.setdefault(r["entity_id"], []).append({"jurisdiction": r["jurisdiction"], "rate": float(r["rate"]), "regime": r["regime"]})
    return out


def _us_combined(rates):
    fed = next(x["rate"] for x in rates["US01"] if "federal" in x["jurisdiction"])
    state = next((x["rate"] for x in rates["US01"] if "state" in x["jurisdiction"]), 0.0)
    return fed + state * (1 - fed)  # state tax is deductible for federal


def get_corporate_finance(wh):
    """Corporate finance view of Echo Labs on trailing-12-month numbers: cash flow from assets (OCF, net capital
    spending, change in NWC) and to creditors / stockholders; ratio analysis and the DuPont identity; corporate
    income tax by legal entity (marginal vs average rate, UK bands, US loss carryforward and the deferred tax asset);
    percent-of-sales pro forma balance sheet with external financing needed; internal and sustainable growth rates;
    accounting, cash and financial break-even; and WACC with the cost of equity from CAPM."""
    from finance_os import corpfin as cf
    st = _ttm_statements(wh)
    cma, rates = _cma(wh), _tax_rates(wh)
    us_rate = _us_combined(rates)

    # cash flow from assets = OCF - net capital spending - change in NWC (= CF to creditors + CF to stockholders)
    nwc = wh.query("""select strftime(month, '%Y-%m') as month, net_working_capital from marts.fct_working_capital_monthly
                      where month <= ?::date order by month desc limit 13""", [st["end_month"] + "-01"])
    d_nwc = float(nwc[0]["net_working_capital"]) - float(nwc[-1]["net_working_capital"]) if len(nwc) > 1 else 0.0
    ocf = st["ebit"] + st["depreciation"]  # no income tax paid (losses); OCF = EBIT + depreciation - taxes
    ncs = st["capex"]
    cffa = ocf - ncs - d_nwc
    equity_raised = float(wh.query("""select coalesce(sum(case when e.entry_type = 'funding' then l.credit else 0 end), 0) as v
                                      from staging.stg_erp__journal_lines l join staging.stg_erp__journal_entries e using (entry_id)
                                      where e.entry_month > ?::date - interval 12 month and e.entry_month <= ?::date
                                        and l.account_id = '3000'""", [st["end_month"] + "-01", st["end_month"] + "-01"])[0]["v"])
    cash_flow = {"operating_cash_flow": round(ocf, 2), "net_capital_spending": round(ncs, 2), "change_in_nwc": round(d_nwc, 2),
                 "cash_flow_from_assets": round(cffa, 2), "cash_flow_to_creditors": 0.0,
                 "cash_flow_to_stockholders": round(-equity_raised, 2),
                 "change_in_cash_balancing_item": round(cffa + equity_raised, 2),
                 "note": "No debt: cash flow to creditors is zero. Cash flow to stockholders = dividends - new equity raised."}

    ratio = cf.ratios({**st, "inventory": 0.0})
    ratio["operating_leverage"] = None

    # corporate income tax by entity, trailing 12 months, in local currency
    ent = wh.query("""select entity_id, currency,
                             sum(case when account_type in ('revenue', 'cogs', 'opex') then -amount_local end) as pti_local,
                             sum(case when account_type in ('revenue', 'cogs', 'opex') then -amount_usd end) as pti_usd
                      from marts.fct_gl_entity_monthly where month > ?::date - interval 12 month and month <= ?::date
                      group by 1, 2 order by 1""", [st["end_month"] + "-01", st["end_month"] + "-01"])
    cum_us = float(wh.query("""select sum(case when account_type in ('revenue', 'cogs', 'opex') then -amount_usd end) as v
                               from marts.fct_gl_entity_monthly where entity_id = 'US01' and month <= ?::date""",
                            [st["end_month"] + "-01"])[0]["v"] or 0)
    taxes, total_tax_usd, total_pti_usd = [], 0.0, 0.0
    for e in ent:
        pti, pti_usd = float(e["pti_local"] or 0), float(e["pti_usd"] or 0)
        fx = pti_usd / pti if pti else 1.0
        if e["entity_id"] == "UK01":
            t = cf.uk_corporation_tax(pti)
        elif e["entity_id"] == "US01":
            nol = cf.with_carryforward(pti, max(-(cum_us - pti), 0.0))
            t = cf.tax_on(nol["taxable_after_nol"], [(None, us_rate)])
            t.update({"marginal_rate": us_rate, "nol_carryforward": round(nol["nol_closing"], 2),
                      "deferred_tax_asset_gross": round(nol["nol_closing"] * us_rate, 2),
                      "valuation_allowance": round(nol["nol_closing"] * us_rate, 2),
                      "note": "Cumulative US losses carry forward; a full valuation allowance applies while the US entity loses money."})
        else:
            t = cf.tax_on(pti, [(None, rates[e["entity_id"]][0]["rate"])])
        tax_usd = t["tax"] * fx
        total_tax_usd += tax_usd
        total_pti_usd += pti_usd
        taxes.append({"entity_id": e["entity_id"], "currency": e["currency"], "pre_tax_income_local": round(pti, 2),
                      "pre_tax_income_usd": round(pti_usd, 2), "tax_local": t["tax"], "tax_usd": round(tax_usd, 2),
                      "average_rate": t["average_rate"], "marginal_rate": t["marginal_rate"],
                      **{k: v for k, v in t.items() if k in ("nol_carryforward", "deferred_tax_asset_gross", "valuation_allowance", "note")}})
    tax_summary = {"group_pre_tax_income": round(total_pti_usd, 2), "group_tax": round(total_tax_usd, 2),
                   "group_effective_rate": round(total_tax_usd / total_pti_usd, 4) if total_pti_usd > 0 else None,
                   "note": "The group loses money but the UK and India subsidiaries earn a cost-plus margin, so they owe tax; "
                           "no income tax is booked in the ledger yet (this is the provision it should carry)."}

    # pro forma balance sheet and EFN at the base scenario's growth
    base = scenario_summaries(wh)
    g = next(x["revenue_next_12m"] for x in base if x["scenario"] == "base") / st["revenue"] - 1 if st["revenue"] else 0.0
    bs = {"assets": {"cash": st["cash"], "receivables": st["receivables"], "fixed_assets": st["fixed_assets_net"]},
          "liabilities": st["liabilities"], "equity": st["equity"]}
    proforma = cf.percent_of_sales(bs, st["net_income"], st["revenue"], g, payout=0.0, spontaneous=("payable", "accrued"))
    proforma["growth_used"] = round(g, 4)
    proforma["efn_cash_held_flat"] = round(proforma["efn"] - (proforma["projected_assets"]["cash"] - st["cash"]), 2)
    proforma["note"] = ("Percent of sales: assets and spontaneous liabilities grow with revenue; equity grows by retained "
                        "earnings at today's margin (no dividends). Positive EFN = outside money needed; this method holds "
                        "cash in proportion to sales, so read EFN as the cash cushion's cost, not a cash shortfall.")
    growth = cf.growth_rates(st["net_income"], st["total_assets"], st["equity"], payout=0.0)

    # cost of capital: CAPM cost of equity on the relevered peer beta, plus a private-company premium
    de = cma.get("target_debt_to_equity", 0.0)
    beta_l = cf.relever_beta(cma["unlevered_beta"], de, us_rate)
    ke = cf.capm(cma["risk_free_rate"], beta_l, cma["market_risk_premium"]) + cma.get("private_company_premium", 0.0)
    w = cf.wacc(1.0, de, ke, cma["pre_tax_cost_of_debt"], us_rate)
    cost_of_capital = {"risk_free_rate": cma["risk_free_rate"], "market_risk_premium": cma["market_risk_premium"],
                       "unlevered_beta": cma["unlevered_beta"], "levered_beta": round(beta_l, 4),
                       "private_company_premium": cma.get("private_company_premium", 0.0), "cost_of_equity": round(ke, 4),
                       "pre_tax_cost_of_debt": cma["pre_tax_cost_of_debt"], "tax_rate": round(us_rate, 4),
                       "debt_to_equity": de, **w,
                       "previous_hurdle_rate": 0.15,
                       "note": "No debt, so WACC = cost of equity. Business cases and projects discount at this WACC by default."}

    # break-even (monthly revenue) from the latest month's cost behavior
    cb = wh.query("select * from marts.fct_cost_behavior_monthly order by month desc limit 1")[0]
    dep_m = float(wh.query("select coalesce(sum(natural_amount), 0) as v from marts.fct_gl_monthly where account_id = '6600' and month = ?::date",
                           [str(cb["month"])[:10]])[0]["v"])
    fixed_cash = float(cb["fixed_costs"]) - dep_m
    rate_m = (1 + w["wacc"]) ** (1 / 12) - 1
    life_m = int(cma.get("asset_life_years", 4) * 12)
    fixed_cost_basis = float(wh.query("select sum(debit) as v from staging.stg_erp__journal_lines where account_id = '1500'")[0]["v"] or 0)
    be = cf.break_even(fixed_cash, dep_m, float(cb["cm_ratio"]), investment=fixed_cost_basis, life=life_m, rate=rate_m, tax_rate=0.0)
    be.update({"month": str(cb["month"])[:7], "revenue": float(cb["revenue"]), "cm_ratio": float(cb["cm_ratio"]),
               "fixed_cash_costs": round(fixed_cash, 2), "depreciation": round(dep_m, 2),
               "degree_of_operating_leverage": cf.degree_of_operating_leverage(float(cb["contribution_margin"]), float(cb["operating_income"])),
               "note": "Monthly revenue needed: accounting = net income 0; cash = operating cash flow 0; financial = NPV 0 on "
                       "the capitalized equipment at the WACC (its equivalent annual cost replaces depreciation). DOL is "
                       "negative while operating income is below zero."})
    return _result([], "three-statement financials (TTM), fct_working_capital_monthly, fct_gl_entity_monthly, "
                       "fct_cost_behavior_monthly, seeds.corporate_tax_rates, seeds.capital_market_assumptions, driver engine",
                   period=st["period"], cash_flow=cash_flow, ratios=ratio, taxes=taxes, tax_summary=tax_summary,
                   proforma=proforma, growth=growth, cost_of_capital=cost_of_capital, break_even=be,
                   statements={k: round(v, 2) for k, v in st.items() if isinstance(v, float)},
                   note="Trailing 12 closed months; balance sheet at the latest close.")


def evaluate_project(wh, investment, life_years, annual_revenue, annual_costs, salvage=0, nwc=0, tax_rate=None,
                     discount_rate=None, depreciation="straight_line", compare_flows=None):
    """Capital budgeting on a project: cash flows with the depreciation tax shield, after-tax salvage and working
    capital, NPV, IRR, payback, discounted payback and profitability index at the company WACC (or a given rate);
    with compare_flows (another project's cash flows), the crossover rate."""
    from finance_os import corpfin as cf
    rates = _tax_rates(wh)
    t = _us_combined(rates) if tax_rate is None else float(tax_rate)
    r = discount_rate
    if r is None:
        cc = get_corporate_finance(wh)["cost_of_capital"]
        r = cc["wacc"]
    out = cf.project_cash_flows(float(investment), int(life_years), float(annual_revenue), float(annual_costs), t, float(r),
                                float(salvage or 0), float(nwc or 0), depreciation)
    if compare_flows:
        out["crossover_rate"] = cf.crossover_rate(out["flows"], [float(x) for x in compare_flows])
    return _result(out.pop("rows"), "finance_os.corpfin.project_cash_flows", tax_rate=round(t, 4), discount_rate=round(float(r), 4), **out,
                   note="OCF = (revenue - costs)(1 - t) + depreciation x t. Final year adds salvage after tax on the gain "
                        "over book value and recovers working capital.")


CALCULATORS = {
    "future_value": ("tvm", ["rate", "periods", "pv"]), "present_value": ("tvm", ["rate", "periods", "fv"]),
    "annuity": ("annuity", ["rate", "periods", "payment", "due", "growth"]), "perpetuity": ("perpetuity", ["rate", "payment", "growth"]),
    "loan": ("loan_schedule", ["principal", "annual_rate", "years", "periods_per_year", "kind"]),
    "bond_price": ("bond_price", ["face", "coupon_rate", "ytm", "years", "freq"]), "bond_ytm": ("bond_ytm", ["price", "face", "coupon_rate", "years", "freq"]),
    "interest_rate_risk": ("interest_rate_risk", ["face", "coupon_rate", "ytm", "years", "shock", "freq"]),
    "ddm": ("ddm", ["dividend_next", "required_return", "growth", "supernormal"]), "voting": ("voting", ["shares_owned", "shares_total", "seats", "cumulative"]),
    "holding_return": ("holding_return", ["price_begin", "price_end", "dividend"]), "return_stats": ("return_stats", ["returns"]),
    "portfolio": ("portfolio", ["w1", "r1", "s1", "r2", "s2", "corr"]), "sml": ("sml", ["rf", "mrp", "beta", "expected_return"]),
    "wacc": ("wacc", ["equity_value", "debt_value", "cost_of_equity", "cost_of_debt", "tax_rate", "preferred_value", "cost_of_preferred"]),
    "flotation": ("flotation_adjusted", ["investment", "weights_flotation"]),
    "rights_offering": ("rights_offering", ["price_now", "subscription_price", "shares_outstanding", "funds_needed"]),
    "mm": ("mm", ["unlevered_value_or_ebit", "debt", "cost_of_debt", "unlevered_cost_of_equity", "tax_rate", "ebit"]),
    "homemade_leverage": ("homemade_leverage", ["shares", "price", "borrow", "rate", "eps_unlevered"]),
    "payout": ("payout", ["net_income", "shares", "price", "cash_distributed"]), "split": ("split", ["shares", "price", "ratio", "stock_dividend_pct"]),
    "bid_price": ("bid_price", ["investment", "life", "units", "variable_cost", "fixed_costs", "tax_rate", "rate", "salvage", "nwc"]),
    "crossover": ("crossover_rate", ["flows_a", "flows_b"]), "tax": ("tax_on", ["income", "bands"]),
    "uk_tax": ("uk_corporation_tax", ["profit"]),
}


def finance_calculator_specs(wh):
    """Every calculator kind and its input names (for the Calculators page)."""
    return {"source": "finance_os.corpfin", "row_count": len(CALCULATORS), "rows": [{"kind": k, "function": f, "inputs": ps} for k, (f, ps) in CALCULATORS.items()]}


def finance_calculator(wh, kind, inputs):
    """Textbook corporate-finance calculators (not company data): time value of money, annuities, perpetuities, loan
    amortization, bond price / YTM / interest-rate risk, dividend discount model, straight vs cumulative voting,
    holding-period returns, arithmetic vs geometric averages and standard deviation, two-asset portfolios, CAPM / SML,
    WACC, flotation costs, rights offerings, M&M, homemade leverage, dividends vs repurchases, splits, bid price,
    crossover rate and tax bands."""
    from finance_os import corpfin as cf
    if kind not in CALCULATORS:
        return {"error": f"kind must be one of {', '.join(CALCULATORS)}"}
    fn, params = CALCULATORS[kind]
    args = {k: v for k, v in (inputs or {}).items() if k in params and v is not None and v != ""}
    try:
        out = getattr(cf, fn)(**args)
    except (TypeError, ValueError, ZeroDivisionError) as e:
        return {"error": f"{kind}: {e}. Inputs: {', '.join(params)}"}
    if not isinstance(out, dict):
        out = {"value": out}
    rows = out.pop("rows", [])
    return {"source": f"finance_os.corpfin.{fn}", "row_count": len(rows), "rows": rows, "kind": kind, "inputs": args, "result": out}

_LINEAGE = {}


def metric_lineage(model):
    """Upstream lineage of a mart from dbt's manifest: the raw sources and seeds it is built from, and the models
    in between (source → staging → intermediate → mart)."""
    if model in _LINEAGE:
        return _LINEAGE[model]
    import json
    path = Path(__file__).resolve().parents[3] / "warehouse" / "target" / "manifest.json"
    if not path.exists():
        return {"sources": [], "seeds": [], "models": []}
    man = json.loads(path.read_text(encoding="utf-8"))
    nodes = {**man["nodes"], **man["sources"]}
    start = next((k for k in man["nodes"] if k.startswith("model.") and k.endswith("." + model)), None)
    seen, todo, out = set(), [start] if start else [], {"sources": set(), "seeds": set(), "models": set()}
    while todo:
        k = todo.pop()
        if k in seen or k not in nodes:
            continue
        seen.add(k)
        n = nodes[k]
        if k.startswith("source."):
            out["sources"].add(f"{n['source_name']}.{n['name']}")
            continue
        if k.startswith("seed."):
            out["seeds"].add(n["name"])
            continue
        if k.startswith("model.") and k != start:
            out["models"].add(n["name"])
        todo += n.get("depends_on", {}).get("nodes", [])
    res = {key: sorted(v) for key, v in out.items()}
    _LINEAGE[model] = res
    return res


def _status(x, better, amber, red):
    if x is None:
        return "grey"
    if better == "higher":
        return "red" if x <= red else "amber" if x <= amber else "green"
    return "red" if x >= red else "amber" if x >= amber else "green"


MULTIPLES = {"quick_ratio", "burn_multiple", "magic_number", "ltv_to_cac_burdened"}
BASIS_LABEL = {"value": "", "month-over-month": " vs last month", "vs budget (favorable +)": " vs budget",
               "payroll vs budget (overrun +)": " payroll vs budget", "vs run-rate ARR": " vs run-rate ARR"}


def _fmt_metric(v, unit, metric):
    """A metric value the way a reader expects it: 81.2%, 65.1 days, $53.8K, 1.87x, 5."""
    if v is None:
        return "n/a"
    if metric == "rule_of_40":
        return f"{v * 100:.0f}"
    if metric in MULTIPLES:
        return f"{v:.2f}x"
    if unit == "ratio":
        return f"{v * 100:.1f}%"
    if unit == "usd":
        return _usd_text(v)
    if unit == "days":
        return f"{v:.1f} days"
    if unit == "months":
        return f"{v:.1f} months"
    return f"{v:,.0f}"


def _status_reason(status, x, shown, t, better, unit="", metric=""):
    """Why a KPI has its status, from the data only: the comparison and the line it crossed (no advice)."""
    if x is None:
        return "No comparison available this month"
    if shown == "value":
        f = lambda v: _fmt_metric(v, unit, metric)  # noqa: E731
        val = f(x)
    else:
        f = lambda v: f"{v * 100:+.0f}%" if abs(v * 100 - round(v * 100)) < 1e-9 else f"{v * 100:+.1f}%"  # noqa: E731
        val = f"{x * 100:+.1f}%"
    label = BASIS_LABEL.get(shown, f" {shown}")
    side = "below" if better == "higher" else "above"
    if shown == "value":  # the card already shows the value: say only where it sits
        if status == "red":
            return f"{side.capitalize()} the red line of {f(t.get('red'))}"
        if status == "amber":
            return f"Past the amber line of {f(t.get('amber'))}; red at {f(t.get('red'))}"
        return f"Within threshold (amber at {f(t.get('amber'))})"
    if status == "red":
        return f"{val}{label}: {side} the red line of {f(t.get('red'))}"
    if status == "amber":
        return f"{val}{label}: past the amber line of {f(t.get('amber'))}; red at {f(t.get('red'))}"
    return f"{val}{label}: within threshold (amber at {f(t.get('amber'))})"


def get_decision_kpis(wh, month=None):
    """Every governed metric with its status: its value, the comparison its threshold uses (value, month-over-month,
    vs budget / plan / run rate), green / amber / red status and why (the line it crossed), and its purpose,
    formula, owner, source model, lineage back to raw sources, the reconciliation checks that prove it (with this
    month's result) and data freshness. Answers 'which numbers need a decision this month and why'."""
    import yaml
    m = _month(month, wh)
    spec = {x["name"]: x for x in yaml.safe_load((Path(__file__).resolve().parents[3] / "warehouse" / "metrics" / "kpis.yml")
                                                  .read_text(encoding="utf-8"))["metrics"]}
    vals = {r["metric_name"]: float(r["value"]) for r in wh.query(
        "select metric_name, value from marts.fct_metric_values_monthly where month = ?::date", [m])}
    prev = {r["metric_name"]: float(r["value"]) for r in wh.query(
        "select metric_name, value from marts.fct_metric_values_monthly where month = ?::date - interval 1 month", [m])}
    bva = {r["account_type"]: r for r in wh.query("""select account_type, sum(actual) as actual, sum(budget) as budget
                                                    from marts.fct_bva_monthly where month = ?::date group by 1""", [m])}
    pay = wh.query("""select sum(actual) as actual, sum(budget) as budget from marts.fct_bva_monthly
                      where month = ?::date and account_id in ('6000', '6010', '6020')""", [m])[0]
    recon = {}
    for r in wh.query("select check_name, status, explanation from recon.recon_status where period = ?::date", [m]):
        recon.setdefault(r["check_name"], []).append(r)
    live = wh.query("select max(entry_date) as d from staging.stg_erp__journal_entries")[0]["d"]
    out = []
    for name, sp in spec.items():
        v = vals.get(name)
        t = sp.get("threshold") or {}
        basis = t.get("basis", "value")
        if basis == "mom":
            x = None if v is None or not prev.get(name) else (v - prev[name]) / abs(prev[name])
            shown = "month-over-month"
        elif basis == "vs_budget":
            b = bva.get(name if name != "revenue" else "revenue") if name in ("revenue", "cogs", "opex") else None
            if b and float(b["budget"] or 0):
                act, bud = float(b["actual"]), float(b["budget"])
                x = (act - bud) / bud if name == "revenue" else (bud - act) / bud  # favorable +
            else:
                x = None
            shown = "vs budget (favorable +)"
        elif basis == "vs_plan":
            x = (float(pay["actual"]) - float(pay["budget"])) / float(pay["budget"]) if pay["budget"] else None
            shown = "payroll vs budget (overrun +)"
        elif basis == "vs_run_rate":
            x = (v - vals["arr"]) / vals["arr"] if v is not None and vals.get("arr") else None
            shown = "vs run-rate ARR"
        else:
            x, shown = v, "value"
        better = "higher" if basis == "vs_budget" else t.get("better")  # budget variances are favorable-positive
        st = _status(x, better, t.get("amber"), t.get("red"))
        checks = sp.get("recon_checks") or []
        res = [r for c in checks for r in recon.get(c, [])]
        recon_status = "not applicable" if not checks else ("pass" if res and all(r["status"] == "pass" for r in res)
                                                            else "fail" if any(r["status"] != "pass" for r in res) else "no result")
        lin = metric_lineage(sp["source_model"])
        out.append({"metric": name, "label": sp["label"], "unit": sp["unit"], "value": v, "prior": prev.get(name),
                    "compare_basis": shown, "compare_value": None if x is None else round(x, 4),
                    "status": st, "threshold": {k: t.get(k) for k in ("basis", "better", "amber", "red")},
                    "status_reason": _status_reason(st, x, shown, t, better, sp["unit"], name),
                    "purpose": sp["purpose"], "formula": sp["formula"], "owner": sp["owner"], "source_model": sp["source_model"],
                    "lineage_sources": lin["sources"], "lineage_seeds": lin["seeds"], "lineage_models": lin["models"],
                    "recon_checks": checks, "recon_status": recon_status, "version": sp.get("version"),
                    "freshness": {"closed_through": m[:7], "live_through": str(live)[:10]}})
    order = {"red": 0, "amber": 1, "green": 2, "grey": 3}
    out.sort(key=lambda r: (order[r["status"]], r["label"]))
    counts = {k: sum(1 for r in out if r["status"] == k) for k in order}
    return _result(out, "warehouse/metrics/kpis.yml (thresholds, decisions), marts.fct_metric_values_monthly, fct_bva_monthly, "
                        "recon.recon_status, dbt manifest (lineage)", month=m[:7], counts=counts,
                   trust={"recon_checks_failing": sum(1 for v in recon.values() for r in v if r["status"] != "pass"),
                          "recon_checks_run": sum(len(v) for v in recon.values()), "live_through": str(live)[:10]},
                   note="Every number carries its purpose, definition, owner, source, lineage, reconciliation status and "
                        "threshold. No canned actions: ask for a recommendation and it is reasoned from this month's data.")


COST_PARTS = [("direct_gpu_cost", "GPU compute per hour"), ("shared_gpu_cost", "Shared GPU pool per hour"),
              ("gpu_commit_shortfall_cost", "Unused GPU commitment per hour"), ("cloud_overhead_cost", "Cloud overhead per hour"),
              ("payment_fees", "Payment fees per hour"), ("support_cost", "Support per hour"), ("success_cost", "Customer success per hour")]


def get_contribution_bridge(wh, month=None):
    """Contribution-margin variance bridge, this month vs last: usage contribution margin = revenue - cost of revenue
    - payment fees - support - success. The change splits into volume (more audio hours at last month's margin per
    hour), mix (which products the hours were in), price (revenue per hour by product), and each cost-to-serve
    component per hour (GPU, shared pool, unused commitment, cloud, fees, support, success). Also the customers and
    workloads that moved contribution most. The steps add up exactly."""
    m = _month(month, wh)
    rows = wh.query(f"""select month, product_id, sum(audio_hours) as h, sum(revenue) as rev, sum(contribution_margin) as cm,
                               {', '.join(f'sum({c}) as {c}' for c, _ in COST_PARTS)}
                        from marts.fct_unit_economics_monthly where month in (?::date, ?::date - interval 1 month)
                        group by 1, 2""", [m, m])
    cur = {r["product_id"]: r for r in rows if str(r["month"])[:10] == m}
    pre = {r["product_id"]: r for r in rows if str(r["month"])[:10] != m}
    f = lambda r, k: float(r.get(k) or 0) if r else 0.0  # noqa: E731
    H1, H0 = sum(f(r, "h") for r in cur.values()), sum(f(r, "h") for r in pre.values())
    CM1, CM0 = sum(f(r, "cm") for r in cur.values()), sum(f(r, "cm") for r in pre.values())
    cmh0 = {p: f(pre.get(p), "cm") / f(pre.get(p), "h") if f(pre.get(p), "h") else 0.0 for p in set(cur) | set(pre)}
    avg0 = CM0 / H0 if H0 else 0.0
    volume = (H1 - H0) * avg0
    mix = sum(f(cur.get(p), "h") * cmh0[p] for p in cmh0) - H1 * avg0
    price = sum(f(cur.get(p), "h") * ((f(cur.get(p), "rev") / f(cur.get(p), "h") if f(cur.get(p), "h") else 0)
                                       - (f(pre.get(p), "rev") / f(pre.get(p), "h") if f(pre.get(p), "h") else 0)) for p in cur)
    steps = [{"step": "Volume (audio hours)", "amount": round(volume, 2)}, {"step": "Product mix", "amount": round(mix, 2)},
             {"step": "Price (revenue per hour)", "amount": round(price, 2)}]
    for c, label in COST_PARTS:
        d = sum(f(cur.get(p), "h") * ((f(cur.get(p), c) / f(cur.get(p), "h") if f(cur.get(p), "h") else 0)
                                       - (f(pre.get(p), c) / f(pre.get(p), "h") if f(pre.get(p), "h") else 0)) for p in cur)
        steps.append({"step": label, "amount": round(-d, 2)})
    resid = CM1 - CM0 - sum(x["amount"] for x in steps)
    if abs(resid) >= 0.01:
        steps.append({"step": "New and discontinued products", "amount": round(resid, 2)})
    movers = wh.query("""with a as (select customer_id, workload, sum(contribution_margin) as cm, sum(revenue) as rev, sum(audio_hours) as h
                                    from marts.fct_unit_economics_monthly where month = ?::date group by 1, 2),
                              b as (select customer_id, workload, sum(contribution_margin) as cm
                                    from marts.fct_unit_economics_monthly where month = ?::date - interval 1 month group by 1, 2)
                         select coalesce(a.customer_id, b.customer_id) as customer_id, coalesce(a.workload, b.workload) as workload,
                                coalesce(a.cm, 0) as contribution_margin, coalesce(b.cm, 0) as prior, coalesce(a.cm, 0) - coalesce(b.cm, 0) as change,
                                a.cm / nullif(a.rev, 0) as contribution_margin_pct, a.cm / nullif(a.h, 0) as cm_per_hour
                         from a full join b on a.customer_id = b.customer_id and a.workload = b.workload
                         order by abs(coalesce(a.cm, 0) - coalesce(b.cm, 0)) desc limit 12""", [m, m])
    return _result(steps, "marts.fct_unit_economics_monthly", month=m[:7],
                   start={"label": "Last month contribution", "amount": round(CM0, 2)}, end={"label": "This month contribution", "amount": round(CM1, 2)},
                   hours={"this": round(H1, 2), "prior": round(H0, 2)}, margin_pct={"this": round(CM1 / sum(f(r, "rev") for r in cur.values()), 4) if cur else None,
                                                                                    "prior": round(CM0 / sum(f(r, "rev") for r in pre.values()), 4) if pre else None},
                   movers=movers, note="Usage business only (services are project-billed). Steps add up to the change exactly.")


def get_margin_sensitivity(wh):
    """Contribution margin sensitivity: next-12-month usage contribution margin (and %) on the latest month's run rate
    for each combination of price change (rows) and cost-to-serve-per-hour change (columns), plus a volume table.
    Pairs with get_runway_sensitivity for cash."""
    m = _month(None, wh)
    r = wh.query("""select sum(revenue) as rev, sum(revenue - contribution_margin) as cost, sum(audio_hours) as h
                    from marts.fct_unit_economics_monthly where month = ?::date""", [m])[0]
    rev, cost = float(r["rev"]) * 12, float(r["cost"]) * 12
    grid = []
    for pr in (-0.15, -0.10, -0.05, 0.0, 0.05):
        row = {"price_change": pr}
        for cc in (-0.10, 0.0, 0.10, 0.20, 0.35):
            rv, cs = rev * (1 + pr), cost * (1 + cc)
            row[f"cost {cc:+.0%}"] = round((rv - cs) / rv, 4)
        grid.append(row)
    vol = [{"volume_change": v, "contribution_margin": round((rev - cost) * (1 + v), 2)} for v in (-0.2, -0.1, 0.0, 0.1, 0.2)]
    return _result(grid, "marts.fct_unit_economics_monthly (latest month x 12)", month=m[:7],
                   base={"annual_revenue": round(rev, 2), "annual_cost_to_serve": round(cost, 2),
                         "contribution_margin_pct": round((rev - cost) / rev, 4) if rev else None},
                   volume=vol, note="Cells are contribution margin % (price changes revenue per hour; cost changes cost to serve per hour).")


def get_control_queue(wh):
    """One queue of everything unresolved that needs an owner's action: budget variances to explain, failing
    reconciliations, open close tasks, AP bills to review, cash-application and billing exceptions, overdue
    receivables, cost anomalies, renewals burning below commitment, and KPIs at red. Each item has an owner, an
    amount, its age, the threshold it broke, the action and the page that resolves it."""
    m = _month(None, wh)
    end = wh.query("select max(entry_date) as d from staging.stg_erp__journal_entries")[0]["d"]
    items = []

    def add(kind, ref, desc, owner, amount, since, threshold, action, page, severity="medium"):
        age = None
        if since:
            from datetime import date
            try:
                age = (date.fromisoformat(str(end)[:10]) - date.fromisoformat(str(since)[:10])).days
            except ValueError:
                age = None
        items.append({"type": kind, "reference": ref, "description": desc, "owner": owner, "amount": amount, "age_days": age,
                      "threshold": threshold, "action": action, "page": page, "severity": severity})

    for a in wh.query("""select alert_id, message, route_to, variance, month, commentary_status from marts.fct_bva_alerts
                         where month = ?::date order by abs(variance) desc""", [m]):
        add("Budget variance", a["alert_id"], a["message"], a["route_to"], abs(float(a["variance"])), a["month"],
            "Materiality: $25K and 10%", "Root cause, commentary and a CFO decision (variance case)", "budget",
            "high" if abs(float(a["variance"])) > 100000 else "medium")
    for r in wh.query("select check_name, period, entity_id, variance, explanation from recon.recon_status where status <> 'pass'"):
        add("Reconciliation break", f"{r['check_name']} {str(r['period'])[:7]}", r["explanation"] or r["check_name"], "Controller",
            abs(float(r["variance"] or 0)), r["period"], "Must tie within tolerance", "Investigate and post the correcting entry", "trust", "high")
    for t in wh.query("""select task_id, task, owner, due_date, open_items from marts.fct_close_status
                         where month = ?::date and status <> 'complete'""", [m]):
        add("Close task", t["task_id"], t["task"], t["owner"], None, t["due_date"], "Due by close workday",
            "Complete with evidence and sign off", "close", "high")
    for b in wh.query("select doc_file, vendor_id, total, reason, detail from marts.fct_ap_review_queue"):
        add("AP bill to review", b["doc_file"], f"{b['vendor_id']}: {b['reason']}", "AP specialist", float(b["total"] or 0), None,
            "Matched to PO and contract", "Approve or reject (approval card)", "ap")
    for e in wh.query("select exception_type, customer_id, reference_id, exception_date, amount, detail from marts.fct_cash_application_exceptions"):
        add("Cash application", e["reference_id"], f"{e['customer_id']}: {e['detail']}", "AR specialist", float(e["amount"] or 0),
            e["exception_date"], "Payments applied to the right invoice", "Re-apply the payment (approval card)", "ar", "high")
    for e in wh.query("select exception_type, project_id, invoice_id, amount_at_risk, detail from marts.fct_billing_exceptions"):
        add("Billing exception", e["invoice_id"], f"{e['project_id']}: {e['detail']}", "Billing specialist", float(e["amount_at_risk"] or 0),
            None, "Invoice matches contract rates", "Correct the invoice before sending", "billing")
    for i in wh.query("""select invoice_ref, customer_id, balance, days_past_due, due_date from marts.fct_ar_invoices
                         where balance > 0 and days_past_due > 60 order by balance desc"""):
        add("Overdue receivable", i["invoice_ref"], f"{i['customer_id']} {i['days_past_due']} days past due", "Controller",
            float(i["balance"]), i["due_date"], "Over 60 days", "Escalate; consider credit hold and a reserve", "ar", "high")
    for a in wh.query("""select spend_date, vendor_id, service, team, deviation from marts.fct_cost_anomalies
                         where spend_date > (select max(spend_date) from marts.fct_tech_spend_daily) - interval 30 day"""):
        add("Cost anomaly", f"{a['vendor_id']} {a['service']}", f"{a['service']} spend spike ({a['team']})", a["team"] or "Head of Infra",
            abs(float(a["deviation"])), a["spend_date"], "3 standard deviations and $500", "Find the cause; stop it or accept it", "spend")
    for c in [r for r in get_contracts(wh)["rows"] if r["in_renewal_window"] and (r["burn_pace"] or 0) < 0.9]:
        add("Renewal at risk", c["contract_id"], f"{c['customer_id']} at {c['burn_pace']:.0%} of commitment pace, renews in {c['days_to_renewal']} days",
            "CRO", float(c["current_commitment"]), None, "Burn pace below 90% inside 180 days of renewal", "Save plan before renewal", "contracts", "high")
    for k in [r for r in get_decision_kpis(wh)["rows"] if r["status"] == "red"]:
        add("KPI at red", k["metric"], f"{k['label']} {k['compare_basis']}", k["owner"], None, None,
            f"{k['threshold']['basis']}: red at {k['threshold']['red']}", f"Owner reviews; {k['status_reason']}", "kpis", "high")
    sev = {"high": 0, "medium": 1}
    items.sort(key=lambda x: (sev.get(x["severity"], 2), -(x["amount"] or 0)))
    by_type = {}
    for x in items:
        by_type[x["type"]] = by_type.get(x["type"], 0) + 1
    return _result(items, "fct_bva_alerts, recon.recon_status, fct_close_status, fct_ap_review_queue, fct_cash_application_exceptions, "
                          "fct_billing_exceptions, fct_ar_invoices, fct_cost_anomalies, get_contracts, get_decision_kpis",
                   month=m[:7], counts=by_type, open_items=len(items),
                   note="Variances count as resolved once a CFO decision is recorded (the workspace marks them).")


AP_CONTROLS = [  # every control an AP bill goes through, in the order a reviewer reads them
    ("unknown_vendor", "Vendor is in the vendor master"),
    ("missing_po", "Bill quotes a purchase order"),
    ("po_not_found", "Purchase order exists"),
    ("po_vendor_mismatch", "Purchase order belongs to this vendor"),
    ("arithmetic_mismatch", "Line items add up to the total"),
    ("amount_mismatch", "Total matches the bill booked in the ERP"),
    ("duplicate_invoice", "Not already received (no duplicate invoice number)"),
]


def get_approval_evidence(wh, kind, target_id, payload=None, document=None):
    """The evidence behind an approval card, so a reviewer can see whether to approve or reject: each control or
    guardrail with pass / fail, the key facts, who is required to approve, links to the detail, and whether the
    proposal agrees with the checks. Reads the data fresh, so it reflects the situation now."""
    import json
    payload = json.loads(payload) if isinstance(payload, str) else (payload or {})
    checks, facts, links, approver, related = [], [], [], "Finance", []

    if kind in ("ap_approve", "ap_reject"):
        d = [document] if document else wh.query("select * from marts.fct_ap_documents where doc_file = ?", [target_id])
        if d:
            d = d[0]
            issues = set(d["issues"] or [])
            checks = [{"check": label, "passed": code not in issues, "detail": None} for code, label in AP_CONTROLS]
            for c in checks:
                if not c["passed"] and "duplicate" in c["check"].lower():
                    orig = wh.query("""select doc_file, erp_bill_id, invoice_date, total from marts.fct_ap_documents
                                       where vendor_invoice_number = ? and doc_file <> ? and erp_bill_id is not null
                                       order by doc_file limit 1""",
                                    [d["vendor_invoice_number"], target_id])
                    if orig:
                        o = orig[0]
                        c["detail"] = f"Same invoice number as {o['doc_file']}, already booked as {o['erp_bill_id']} for ${float(o['total']):,.2f}"
                        related.append({"label": "Original bill", **{k: str(v) for k, v in o.items()}})
                if not c["passed"] and "ERP" in c["check"]:
                    c["detail"] = f"Bill ${float(d['total'] or 0):,.2f} vs ERP ${float(d['erp_amount'] or 0):,.2f}"
                if not c["passed"] and "add up" in c["check"]:
                    c["detail"] = f"Lines ${float(d['lines_total'] or 0):,.2f} vs total ${float(d['total'] or 0):,.2f}"
            facts = [{"label": "Vendor", "value": d["vendor_name"] or d["vendor_id"]}, {"label": "Invoice", "value": d["vendor_invoice_number"]},
                     {"label": "Amount", "value": f"${float(d['total'] or 0):,.2f}"}, {"label": "PO", "value": d["po_number"] or "none"},
                     {"label": "Intake route", "value": d["route"]}]
            links = [{"label": f"Open vendor {d['vendor_id']}", "entity": {"kind": "vendor", "id": d["vendor_id"]}} if d["vendor_id"] else None,
                     {"label": "AP inbox", "page": "ap"}]
        approver = "AP specialist (Controller above $10K)"
    elif kind == "deal_approval":
        ev = payload.get("evaluation") or {}
        checks = [{"check": c["rule"], "passed": c["passed"], "detail": c["detail"], "approver": c.get("approver", "Finance")} for c in ev.get("checks", [])]
        risk = ev.get("risk") or {}
        facts = [{"label": "Monthly revenue", "value": f"${ev.get('monthly_revenue', 0):,.2f}"},
                 {"label": "Gross margin", "value": f"{ev.get('gross_margin_pct', 0):.1%} (floor {ev.get('floor_pct', 0):.1%})"},
                 {"label": "Contract value", "value": f"${ev.get('contract_value', 0):,.2f} over {ev.get('term_months')} months"}]
        if risk:
            facts += [{"label": "Margin if cost hits P90", "value": f"{(risk.get('gross_margin_pct_at_p90_cost') or 0):.1%}"},
                      {"label": "First-year commission", "value": f"${(risk.get('commission') or {}).get('first_year_commission', 0):,.2f}"},
                      {"label": "Discount vs history", "value": f"{((risk.get('discounts') or {}).get('this_deal_percentile') or 0):.0%} percentile"}]
        facts += [{"label": "Revenue-recognition flags", "value": ", ".join(f["flag"] for f in ev.get("revrec_flags", [])) or "none"}]
        failed = [c for c in checks if not c["passed"]]
        approver = ", ".join(ev.get("approvers") or sorted({c.get("approver", "Finance") for c in failed})) or "Rules (auto-approve)"
        links = [{"label": "Open in the deal desk", "page": "deals"}]
    elif kind in ("reminder_approve", "reminder_reject"):
        inv = wh.query("""select invoice_ref, customer_id, balance, days_past_due, is_disputed, due_date from marts.fct_ar_invoices
                          where invoice_ref = ?""", [target_id])
        if inv:
            i = inv[0]
            checks = [{"check": "Invoice is past due", "passed": (i["days_past_due"] or 0) > 0, "detail": f"{i['days_past_due']} days past due"},
                      {"check": "Not in dispute", "passed": not i["is_disputed"], "detail": None},
                      {"check": "Balance still open", "passed": float(i["balance"] or 0) > 0, "detail": f"${float(i['balance'] or 0):,.2f} open"}]
            facts = [{"label": "Customer", "value": i["customer_id"]}, {"label": "Due", "value": str(i["due_date"])[:10]}]
            links = [{"label": f"Open customer {i['customer_id']}", "entity": {"kind": "customer", "id": i["customer_id"]}}]
        approver = "AR specialist"
    elif kind == "cash_application_fix":
        refs = [payload.get("applied_ref"), payload.get("correct_invoice_ref")]
        rows = {r["invoice_ref"]: r for r in wh.query(
            "select invoice_ref, customer_id, amount, balance from marts.fct_ar_invoices where invoice_ref in (?, ?)", refs)}
        a, b = rows.get(refs[0]), rows.get(refs[1])
        amt = float(payload.get("amount") or 0)
        checks = [{"check": "Same customer on payment and target invoice", "passed": bool(b) and b["customer_id"] == payload.get("customer_id"), "detail": None},
                  {"check": "Target invoice has an open balance covering the payment", "passed": bool(b) and float(b["balance"] or 0) >= amt - 0.01,
                   "detail": f"open ${float(b['balance'] or 0):,.2f} vs payment ${amt:,.2f}" if b else None},
                  {"check": "Currently applied invoice is over-applied", "passed": bool(a) and float(a["balance"] or 0) < 0,
                   "detail": f"{refs[0]} balance ${float(a['balance'] or 0):,.2f}" if a else None}]
        facts = [{"label": "Payment", "value": f"{target_id} · ${amt:,.2f}"}, {"label": "Remittance says", "value": str(payload.get("remittance_ref"))}]
        approver = "Controller"
    elif kind == "commission_dispute":
        facts = [{"label": "Claim", "value": payload.get("claim")}, {"label": "Statement credit (ARR)", "value": f"${float(payload.get('credited_arr') or 0):,.2f}"},
                 {"label": "Amount claimed", "value": f"${float(payload.get('claimed_amount') or 0):,.2f}" if payload.get("claimed_amount") else "not stated"}]
        approver = "VP Sales and Controller"
        links = [{"label": "Commissions", "page": "comp"}]
    links = [l for l in links if l]
    failed = [c for c in checks if not c["passed"]]
    verdict = "no checks" if not checks else ("all checks pass" if not failed else f"{len(failed)} of {len(checks)} checks failed")
    proposes_yes = kind in ("ap_approve", "reminder_approve", "cash_application_fix", "deal_approval")
    agrees = None if not checks else (not failed) == proposes_yes
    return {"source": "fct_ap_documents, deal desk evaluation, fct_ar_invoices", "row_count": len(checks), "rows": checks,
            "kind": kind, "target_id": target_id, "verdict": verdict, "failed": len(failed), "facts": facts, "required_approver": approver,
            "links": links, "related": related, "proposal_agrees_with_checks": agrees,
            "approve_means": {"ap_reject": "The bill is rejected and never paid.", "ap_approve": "The bill becomes payable in the next payment run.",
                              "deal_approval": "The quote is approved (overriding any failed guardrail) and recorded in the audit log.",
                              "reminder_approve": "The reminder is sent to the customer.", "reminder_reject": "The reminder is discarded.",
                              "cash_application_fix": "The payment is re-applied to the target invoice.",
                              "commission_dispute": "The dispute is upheld and the statement is to be adjusted."}.get(kind, "")}


def get_invoice_detail(wh, invoice_ref):
    """Everything about one customer invoice (project invoices PINV…, usage invoices INV-…; a Stripe invoice id in_…
    is resolved to its ERP invoice): header and terms, the lines (milestones, labor hours x rate, or audio hours by
    product), tax and currency, payments applied, disputes, the journal entries it posted, the Stripe invoice for
    usage billing, and checks that the lines, the ledger and Stripe all agree with the invoice total. The PDF is
    rendered from the same data at /api/invoices/{ref}/pdf."""
    ref = invoice_ref
    if str(ref).startswith("in_"):
        hit = wh.query("select erp_invoice_ref from staging.stg_stripe__invoices where invoice_id = ?", [ref])
        ref = hit[0]["erp_invoice_ref"] if hit else ref
    h = wh.query("""select a.*, strftime(a.invoice_date, '%Y-%m-%d') as invoice_date_s, strftime(a.due_date, '%Y-%m-%d') as due_date_s,
                           strftime(a.paid_date, '%Y-%m-%d') as paid_date_s, c.customer_name
                    from marts.fct_ar_invoices a left join marts.dim_customer c using (customer_id) where a.invoice_ref = ?""", [ref])
    if not h:
        return _result([], "marts.fct_ar_invoices", note=f"No invoice {invoice_ref}.")
    h = h[0]
    header = {"invoice_ref": ref, "type": h["invoice_type"], "customer_id": h["customer_id"], "customer_name": h["customer_name"],
              "segment": h["segment"], "project_id": h["project_id"], "invoice_date": h["invoice_date_s"], "due_date": h["due_date_s"],
              "amount": h["amount"], "applied": h["applied_amount"], "balance": h["balance"], "status": h["status"],
              "paid_date": h["paid_date_s"], "days_to_pay": h["days_to_pay"], "days_past_due": h["days_past_due"], "is_disputed": h["is_disputed"],
              "terms_days": (dt.date.fromisoformat(h["due_date_s"]) - dt.date.fromisoformat(h["invoice_date_s"])).days if h["due_date_s"] and h["invoice_date_s"] else None}
    lines, contract, stripe = [], None, None
    if h["invoice_type"] == "project":
        pi = wh.query("""select i.*, p.project_name, strftime(i.service_month, '%Y-%m') as service_month_s
                         from staging.stg_projects__project_invoices i left join marts.dim_project p using (project_id)
                         where i.invoice_id = ?""", [ref])
        if pi:
            header.update({"project_name": pi[0]["project_name"], "contract_id": pi[0]["contract_id"], "service_month": pi[0]["service_month_s"]})
            k = wh.query("select * from staging.stg_projects__contracts where contract_id = ?", [pi[0]["contract_id"]])
            contract = k[0] if k else None
        lines = wh.query("""select l.line_no, l.line_type, coalesce(m.milestone_name, l.labor_category, cl.description, l.line_type) as description,
                                   l.milestone_id, l.clin_id, l.hours, l.rate, l.amount
                            from staging.stg_projects__project_invoice_lines l
                            left join staging.stg_projects__milestones m using (milestone_id)
                            left join staging.stg_projects__clins cl on cl.clin_id = l.clin_id
                            where l.invoice_id = ? order by l.line_no""", [ref])
        if not lines:
            lines = [{"line_no": 1, "line_type": "services", "description": header.get("project_name") or "Professional services",
                      "hours": None, "rate": None, "amount": h["amount"]}]
    else:
        st = wh.query("""select invoice_id, invoice_number, status, collection_method, strftime(service_month, '%Y-%m') as service_month,
                                strftime(created_at, '%Y-%m-%d') as created, strftime(paid_at, '%Y-%m-%d') as paid, attempt_count,
                                total, amount_paid, amount_remaining
                         from staging.stg_stripe__invoices where erp_invoice_ref = ?""", [ref])
        stripe = st[0] if st else None
        if stripe:
            header["service_month"] = stripe["service_month"]
            lines = wh.query("""select row_number() over (order by product_id) as line_no, 'usage' as line_type,
                                       product_id || ' audio transcription' as description, audio_hours as hours,
                                       amount / nullif(audio_hours, 0) as rate, amount
                                from staging.stg_stripe__invoice_lines where invoice_id = ? order by product_id""", [stripe["invoice_id"]])
    tax = wh.query("select country, currency, tax_regime, invoice_rate, amount_local, tax_rate, tax_local, tax_usd, realized_fx from marts.fct_invoice_tax_fx where invoice_ref = ?", [ref])
    payments = wh.query("""select payment_id, strftime(received_date, '%Y-%m-%d') as received_date, amount, remittance_ref, applied_ref,
                                  remittance_ref <> applied_ref as misapplied
                           from staging.stg_erp__customer_payments where applied_ref = ? or remittance_ref = ? order by received_date""", [ref, ref])
    disputes = wh.query("""select dispute_id, strftime(opened_date, '%Y-%m-%d') as opened_date, amount, status, root_cause, note
                           from staging.stg_erp__disputes where invoice_ref = ?""", [ref])
    gl = wh.query("""select e.entry_id, strftime(e.entry_date, '%Y-%m-%d') as entry_date, e.entry_type, l.account_id, a.account_name,
                            l.debit, l.credit
                     from staging.stg_erp__journal_entries e join staging.stg_erp__journal_lines l using (entry_id)
                     join marts.dim_gl_account a using (account_id)
                     where e.source_ref = ? order by e.entry_date, e.entry_id, l.line_no""", [ref])
    amt = float(h["amount"] or 0)
    line_sum = round(sum(float(x["amount"] or 0) for x in lines), 2)
    rev_posted = round(sum(float(x["credit"] or 0) - float(x["debit"] or 0) for x in gl if x["account_id"] in ("4000", "4100")), 2)
    checks = [{"check": "Lines add up to the invoice total", "passed": abs(line_sum - amt) < 0.01, "detail": f"lines ${line_sum:,.2f} vs invoice ${amt:,.2f}"}]
    if gl and any(x["account_id"] in ("4000", "4100") for x in gl):
        checks.append({"check": "Revenue posted to the ledger equals the invoice", "passed": abs(rev_posted - amt) < 0.01, "detail": f"GL revenue ${rev_posted:,.2f}"})
    elif h["invoice_type"] == "usage":
        checks.append({"check": "Revenue posted to the ledger", "passed": True, "detail": "usage revenue is posted per customer at month end (rated usage); reconciled in gl_revenue_vs_rated_usage"})
    if stripe:
        checks.append({"check": "Stripe invoice total equals the ERP invoice", "passed": abs(float(stripe["total"]) - amt) < 0.01, "detail": f"Stripe ${float(stripe['total']):,.2f}"})
    paid = round(sum(float(x["amount"]) for x in payments if x["applied_ref"] == ref), 2)
    checks.append({"check": "Cash applied matches the payments received", "passed": abs(paid - float(h["applied_amount"] or 0)) < 0.01,
                   "detail": f"payments ${paid:,.2f} vs applied ${float(h['applied_amount'] or 0):,.2f}"})
    if any(x["misapplied"] for x in payments):
        checks.append({"check": "Payments applied to the invoice the customer named", "passed": False, "detail": "a payment's remittance names a different invoice"})
    return _result(lines, "marts.fct_ar_invoices, projects invoices and lines, stg_stripe__invoices, customer payments, disputes, journal",
                   header=header, contract=contract, tax=tax[0] if tax else None, payments=payments, disputes=disputes, journal=gl,
                   stripe=stripe, checks=checks, pdf_url=f"/api/invoices/{ref}/pdf",
                   note="The PDF is generated from this same data, so it always matches what was billed and posted.")

def get_treasury_sweep(wh):
    """Simulated cash sweeps over the 13-week forecast. Each week the operating account takes the net flow, then:
    excess above six weeks of outflows sweeps to the money market fund; a shortfall below the four-week policy pulls
    from the money market; money market above an eight-week buffer buys T-bills (3-month ladder). Interest accrues
    weekly at each account's yield; 'idle' is the interest forgone if everything sat in the operating account.
    Cash is also shown by legal entity (each subsidiary banks locally)."""
    accounts = {a["account_type"]: a for a in wh.query("select * from seeds.treasury_accounts")}
    pos = {r["account_type"]: float(r["balance"]) for r in wh.query("select account_type, balance from marts.fct_cash_position")}
    weeks = wh.query("select week, strftime(week_start, '%Y-%m-%d') as week_start, inflows, payroll, vendors, other_opex from marts.fct_cash_forecast_13w order by week")
    weekly_out = -sum(float(w["payroll"]) + float(w["vendors"]) + float(w["other_opex"]) for w in weeks) / max(1, len(weeks))
    op, mmf, tb = pos.get("operating", 0.0), pos.get("money_market", 0.0), pos.get("treasury_bills", 0.0)
    y_mmf, y_tb = float(accounts["money_market"]["annual_yield"]), float(accounts["treasury_bills"]["annual_yield"])
    rows, earned, idle_rate = [], 0.0, 0.0
    for w in weeks:
        net = float(w["inflows"]) + float(w["payroll"]) + float(w["vendors"]) + float(w["other_opex"])
        op += net
        target, floor = weekly_out * SWEEP_TARGET_WEEKS, weekly_out * 4
        sweep = 0.0
        if op > target:
            sweep = op - target
        elif op < floor:
            sweep = -min(mmf, target - op)
        op, mmf = op - sweep, mmf + sweep
        to_tb = max(0.0, mmf - weekly_out * SWEEP_MMF_BUFFER_WEEKS)
        mmf, tb = mmf - to_tb, tb + to_tb
        interest = mmf * y_mmf / 52 + tb * y_tb / 52
        mmf += mmf * y_mmf / 52
        tb += tb * y_tb / 52
        earned += interest
        rows.append({"week": w["week"], "week_start": w["week_start"], "net_flow": round(net, 2), "sweep_to_mmf": round(sweep, 2),
                     "to_tbills": round(to_tb, 2), "operating": round(op, 2), "money_market": round(mmf, 2), "treasury_bills": round(tb, 2),
                     "interest": round(interest, 2), "operating_weeks": round(op / weekly_out, 1) if weekly_out else None})
    total = rows[-1]["operating"] + rows[-1]["money_market"] + rows[-1]["treasury_bills"] if rows else 0
    by_entity = wh.query("""select e.entity_id, d.entity_name, d.currency, sum(e.amount_usd) as cash_usd, sum(e.amount_local) as cash_local
                            from marts.fct_gl_entity_monthly e join marts.dim_entity d using (entity_id)
                            where e.account_id = '1000' group by 1, 2, 3 order by 1""")
    return {"source": "marts.fct_cash_position, fct_cash_forecast_13w, seeds.treasury_accounts, fct_gl_entity_monthly",
            "row_count": len(rows), "rows": rows, "interest_13w": round(earned, 2),
            "interest_annualized": round(earned * 4, 2), "avg_weekly_outflow": round(weekly_out, 2),
            "ending_total": round(total, 2), "by_entity": by_entity,
            "policy": {"target_weeks": SWEEP_TARGET_WEEKS, "floor_weeks": 4, "mmf_buffer_weeks": SWEEP_MMF_BUFFER_WEEKS},
            "note": "Simulated sweeps (no bank connection): rules are the treasury policy; balances start from today's split."}


def _p(props, required=()):
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


MONTH = {"type": "string", "description": "Month as YYYY-MM. Omit for the latest month with data."}
# Exact KPI names from the metric catalog (warehouse/metrics/kpis.yml), given to the model in the schema.
METRIC_NAMES = ["revenue", "cogs", "opex", "gross_margin_pct", "gross_burn", "net_burn", "closing_cash",
                "runway_months", "arr", "headcount", "arr_per_employee", "nrr", "grr", "active_customers",
                "new_customers", "churned_customers", "logo_churn_rate", "gross_mrr_churn_rate", "dso_days", "cei",
                "ar_over_60", "net_new_arr", "quick_ratio", "burn_multiple", "rule_of_40", "cac", "cac_burdened",
                "ltv_to_cac_burdened", "cac_payback_burdened_months", "magic_number", "contracted_arr", "rpo", "crpo"]
METRIC = {"type": "string", "enum": METRIC_NAMES}
SCENARIO = {"type": "string", "enum": ["base", "upside", "downside"]}

TOOLS = {
    "get_attention_items": (get_attention_items,
                            "Everything currently flagged across all modules (projects, billing, budget, margins, AR, AP, "
                            "vendor renewals, reconciliations). Use first for broad questions like 'what needs attention?'.",
                            _p({})),
    "get_kpis":(get_kpis, "Company KPIs for one month from the governed metric layer (revenue, run-rate ARR, burn, runway, "
                "margins, churn, DSO, net new ARR, burn multiple, rule of 40, burdened CAC, RPO …). For LTV to CAC and CAC "
                "payback on both bases (S&M-only and burdened) use get_saas_metrics.",
                 _p({"month": MONTH, "metrics": {"type": "array", "items": METRIC,
                                                 "description": "Metric names to return; omit for all."}})),
    "get_kpi_trend": (get_kpi_trend, "One KPI month by month.",
                      _p({"metric": METRIC, "start_month": MONTH, "end_month": MONTH}, ["metric"])),
    "get_metric_definition": (get_metric_definition, "A metric's definition: formula, purpose, owner, caveats.",
                              _p({"metric": METRIC}, ["metric"])),
    "get_pnl": (get_pnl, "Income statement (revenue, COGS, opex) for a month range, grouped by account, rollup or department.",
                _p({"start_month": MONTH, "end_month": MONTH,
                    "group_by": {"type": "string", "enum": ["account", "rollup", "department"]}})),
    "get_financial_statements": (get_financial_statements,
                                 "Three-statement view: income statement, balance sheet and cash flow (indirect), one column "
                                 "per month, quarter or year. Use for 'show me the P&L / balance sheet / cash flow'.",
                                 _p({"period": {"type": "string", "enum": ["month", "quarter", "year"]},
                                     "periods": {"type": "integer"}, "end_month": MONTH})),
    "get_saas_metrics": (get_saas_metrics, "SaaS unit economics by month: CAC, ARPA, LTV, LTV:CAC, CAC payback, YoY growth, "
                         "EBITDA margin, Rule of 40, free cash flow and FCF margin.", _p({"months": {"type": "integer"}})),
    "get_cost_behavior": (get_cost_behavior, "Fixed vs variable costs, contribution margin, breakeven revenue, margin of "
                          "safety and operating leverage by month, with each account's classification. Use for cost-cut, "
                          "breakeven and 'should we take this order' questions.", _p({"months": {"type": "integer"}})),
    "get_revenue_pvm": (get_revenue_pvm, "Price / volume / mix bridge of usage revenue vs the prior month, by product.",
                        _p({"month": MONTH})),
    "get_long_range_plan": (get_long_range_plan, "Five-year long-range plan: revenue, margins, opex by function, EBITDA, "
                            "capex, free cash flow, financing and cash by year.", _p({})),
    "get_runway_sensitivity": (get_runway_sensitivity, "Sensitivity table: months of runway by NRR change and opex "
                               "change, from the last closed month.", _p({})),
    "evaluate_business_case": (evaluate_business_case, "NPV, IRR and payback for an investment: amount spent today and "
                               "the net cash it returns each year (build vs buy, hire vs outsource, capex).",
                               _p({"investment": {"type": "number"}, "annual_inflows": {"type": "array", "items": {"type": "number"}},
                                   "discount_rate": {"type": "number"}, "annual_costs": {"type": "array", "items": {"type": "number"}},
                                   "name": {"type": "string"}}, ["investment", "annual_inflows"])),
    "evaluate_marketing_campaign": (evaluate_marketing_campaign, "NPV, IRR and payback of a marketing campaign: revenue per new "
                                    "customer from recently won customers, current gross margin and churn.",
                                    _p({"spend": {"type": "number"}, "new_customers": {"type": "number"},
                                        "years": {"type": "integer"}, "discount_rate": {"type": "number"}},
                                       ["spend", "new_customers"])),
    "get_kpi_scorecard": (get_kpi_scorecard, "The executive scorecard for a month: each headline metric with last month, "
                          "last year, budget, a 12-month trend and how it compares to SaaS benchmarks. Use for 'how are we "
                          "doing?' and any 'compared to what?' question.", _p({"month": MONTH})),
    "get_month_summary": (get_month_summary, "What changed this month and why: revenue drivers (price/volume/mix, biggest "
                          "customer moves), margin, cost changes and budget variances, cash and efficiency, customer risk and "
                          "pipeline, each with a status. Use for monthly reviews and 'what happened this month?'.", _p({"month": MONTH})),
    "get_growth_efficiency": (get_growth_efficiency, "ARR waterfall by month (new, expansion, reactivation, contraction, "
                              "churn, net new ARR) with quick ratio and burn multiple.", _p({"months": {"type": "integer"}})),
    "get_cohort_retention": (get_cohort_retention, "Retention by signup cohort: revenue retention (vs first full month) or "
                             "logo retention, for up to N months after signup.",
                             _p({"kind": {"type": "string", "enum": ["revenue", "gross", "logo"]}, "max_months": {"type": "integer"}})),
    "get_customer_health": (get_customer_health, "Customer health from leading indicators (usage trend, days since usage, "
                            "overdue invoices, disputes, margin floor), at-risk ARR and revenue concentration (top 1/5/10).",
                            _p({"health": {"type": "string", "enum": ["at_risk", "watch", "healthy"]}})),
    "get_pipeline": (get_pipeline, "Sales pipeline: open deals by stage, weighted ARR, next-quarter coverage vs quota, slipped "
                     "deals, monthly bookings and win rates by segment.", _p({})),
    "get_product_unit_economics": (get_product_unit_economics, "Revenue and cost to serve per audio hour and gross margin by "
                                   "product, by month.", _p({"months": {"type": "integer"}})),
    "get_receivables_dashboard": (get_receivables_dashboard, "Receivables in full: every open invoice with segment, aging "
                                  "bucket, route and recommended action; DSO, CEI and average days delinquent by month; "
                                  "expected customer receipts by week.", _p({})),
    "get_budget_dashboard": (get_budget_dashboard, "Budget vs actual by department and account for a closed month with "
                             "favorable/unfavorable variances (signed so positive is good), YTD and full-year forecast, owners, "
                             "alerts and commentary, and the 12-month actual vs budget trend.", _p({"month": MONTH})),
    "get_spend_dashboard": (get_spend_dashboard, "Tech spend by vendor, team, category, model and tagging; monthly trend "
                            "with audio hours and cost per audio hour; GPU commit utilization; forecast; contract renewals.",
                            _p({"months": {"type": "integer"}})),
    "get_ap_dashboard": (get_ap_dashboard, "AP: every vendor bill with route and issues, exceptions by reason, open bills "
                         "by due date with early-pay discounts, and DPO by month.", _p({})),
    "get_close_dashboard": (get_close_dashboard, "Month-end close: checklist by owner, workday and status (overdue "
                            "flagged), reconciliation results, and past closes.", _p({})),
    "get_projects_dashboard": (get_projects_dashboard, "Projects: budget, EAC, % complete, earned vs billed (under/over "
                               "billing), forecast margin, funding by CLIN and exceptions.", _p({})),
    "get_commissions_dashboard": (get_commissions_dashboard, "Commissions by rep and month: attainment vs quota, credited "
                                  "ARR, commission (base, accelerator, clawback, SPIFF), this year's credits by customer "
                                  "(with splits), comp plan versions, SPIFF programs, and DEFERRED COMMISSIONS under ASC "
                                  "340-40 (capitalized, amortized, balance, current portion).", _p({})),
    "get_tax_dashboard": (get_tax_dashboard, "Sales tax / VAT / GST and FX by month, currency and regime: billings, tax "
                          "collected, tax due, realized and unrealized FX.", _p({})),
    "get_trust_dashboard": (get_trust_dashboard, "Reconciliation results by check and period with pass rate trend and "
                            "open failures (the data quality score).", _p({})),
    "get_close_review": (get_close_review, "The controller's close review for the month being closed: accruals and true-ups, "
                         "prepaid amortization, each balance sheet account vs its support (reconciled or not), flux analysis "
                         "of every account vs last month with explanations and materiality, journal entries by type, the "
                         "close checklist and the ASC 606 roll-forward.", _p({})),
    "run_stress_test": (run_stress_test, "Stress test the plan for 24 months against the baseline. Levers: nrr_pts (annual NRR "
                        "change, e.g. -0.05), win_rate_pct (-0.2 = 20% fewer wins), cycle_days (+30 = deals close a month "
                        "later), price_pct, cogs_pts (cost to serve, share of revenue), hiring_pct (1 = hiring plan, 0 = "
                        "freeze), opex_pct, raise_amount + raise_month (YYYY-MM). Presets: downturn, price_war, gpu_squeeze, "
                        "lean, breakout, severe_downside, fundraise_delayed (planned round six months late), "
                        "largest_customer_churn (top customer leaves in 3 months), gpu_price_shock. Use for any "
                        "'what happens if…' question.",
                        _p({"preset": {"type": "string", "enum": list(STRESS_PRESETS)},
                            "nrr_pts": {"type": "number"}, "win_rate_pct": {"type": "number"}, "cycle_days": {"type": "integer"},
                            "price_pct": {"type": "number"}, "cogs_pts": {"type": "number"}, "hiring_pct": {"type": "number"},
                            "opex_pct": {"type": "number"}, "raise_amount": {"type": "number"}, "raise_month": {"type": "string"},
                            "months": {"type": "integer"}})),
    "get_segment_pnl": (get_segment_pnl, "Segment P&L by region (North America, EMEA, APAC) or channel (self-serve, direct "
                        "sales, public sector): revenue, COGS, gross margin, cost to serve, contribution, allocated opex, "
                        "operating income, and the monthly trend.",
                        _p({"dimension": {"type": "string", "enum": ["region", "channel"]}, "month": MONTH, "months": {"type": "integer"}})),
    "get_consolidation": (get_consolidation, "Multi-entity consolidation for a closed month: P&L and balance sheet per legal "
                          "entity (US parent, UK and India subsidiaries, translated to USD), intercompany eliminations, "
                          "consolidated totals, monthly intercompany charges and the cumulative translation adjustment.",
                          _p({"month": MONTH})),
    "get_ceo_one_pager": (get_ceo_one_pager, "The CEO one-pager: headline numbers and the top five opportunities and top five "
                          "risks across the company, each sized in dollars with an owner. Use for 'what should I focus on', "
                          "'biggest risks / opportunities', board or CEO summaries.", _p({})),
    "get_driver_tree": (get_driver_tree, "Value driver tree for a month vs the prior month: EBITDA to revenue (customers x "
                        "hours per customer x revenue per hour, services), cost of revenue (cost per hour) and opex "
                        "(headcount x cost per head, other), with each driver's change and EBITDA impact.", _p({"month": MONTH})),
    "explore_ledger": (explore_ledger, "Answer any SPECIFIC ledger question: amounts in a month range filtered by account "
                       "type, account (id or name), rollup, department, legal entity (US01, UK01, IN01), customer, vendor, "
                       "entry type or memo text, grouped by month / account / account_type / rollup / department / entity / "
                       "customer / vendor / entry_type, with the monthly trend and the largest journal lines. Use when no "
                       "dashboard tool fits, e.g. 'what did we spend on AWS-like cloud in ENG in Q2 2026'.",
                       _p({"start_month": MONTH, "end_month": MONTH, "account_type": {"type": "string"}, "account": {"type": "string"},
                           "rollup": {"type": "string"}, "department": {"type": "string"}, "entity": {"type": "string"},
                           "customer_id": {"type": "string"}, "vendor_id": {"type": "string"}, "entry_type": {"type": "string"},
                           "text": {"type": "string"}, "group_by": {"type": "string", "enum": list(EXPLORE_GROUPS)},
                           "top": {"type": "integer"}})),
    "explore_options": (explore_options, "The values each explore_ledger filter can take (accounts, departments, entities, "
                        "customers, vendors, entry types, months) and the governed metrics.", _p({})),
    "get_vendor_concentration": (get_vendor_concentration, "Vendor concentration: trailing billed spend (AP) by vendor, share and "
                                 "cumulative share, top-1 / top-3 share, HHI, remaining commitment and contract end.",
                                 _p({"months": {"type": "integer"}})),
    "get_driver_correlation": (get_driver_correlation, "How operating drivers move together: correlation of monthly "
                               "changes (audio hours, customers, price and cost per hour, revenue, cost, payroll, opex, "
                               "headcount, idle GPU, EBITDA) with the strongest pairs.", _p({"months": {"type": "integer"}})),
    "get_decisions_needed": (get_decisions_needed, "Decisions leadership or the board must make now (renewal save plans, "
                             "second GPU vendor, forecast assumptions, funding plan, margin-floor repricing, covenants), each "
                             "with evidence, options, owner and deadline.", _p({})),
    "get_corporate_finance": (get_corporate_finance, "Corporate finance on trailing-12-month numbers: cash flow from assets "
                              "(OCF, net capital spending, change in NWC) and to creditors / stockholders; liquidity, leverage, "
                              "turnover and profitability ratios and the DuPont identity; corporate income tax by entity (marginal "
                              "vs average, UK bands, US loss carryforward and deferred tax asset); pro forma balance sheet and "
                              "external financing needed (EFN); internal and sustainable growth rates; accounting, cash and "
                              "financial break-even and DOL; WACC with CAPM cost of equity.", _p({})),
    "evaluate_project": (evaluate_project, "Capital budgeting for a project: cash flows with depreciation tax shield, "
                         "after-tax salvage and working capital; NPV, IRR, payback, discounted payback, profitability index "
                         "at the company WACC (or discount_rate); crossover rate vs compare_flows.",
                         _p({"investment": {"type": "number"}, "life_years": {"type": "integer"}, "annual_revenue": {"type": "number"},
                             "annual_costs": {"type": "number"}, "salvage": {"type": "number"}, "nwc": {"type": "number"},
                             "tax_rate": {"type": "number"}, "discount_rate": {"type": "number"},
                             "depreciation": {"type": "string", "enum": ["straight_line", "double_declining"]},
                             "compare_flows": {"type": "array", "items": {"type": "number"}}},
                            ["investment", "life_years", "annual_revenue", "annual_costs"])),
    "finance_calculator": (finance_calculator, "Textbook corporate-finance calculators (not company data). kind: "
                           + ", ".join(CALCULATORS) + ". inputs: the named parameters for that kind (rates as decimals).",
                           _p({"kind": {"type": "string", "enum": list(CALCULATORS)}, "inputs": {"type": "object"}}, ["kind", "inputs"])),
    "finance_calculator_specs": (finance_calculator_specs, "List the calculator kinds and their inputs.", _p({})),
    "get_decision_kpis": (get_decision_kpis, "Every governed KPI with its status: value, the threshold comparison (value, "
                          "month-over-month, vs budget, vs plan), green/amber/red status and the line it crossed, "
                          "purpose, formula, owner, source, lineage to raw sources, reconciliation status and freshness. Use "
                          "for 'which numbers need a decision', 'what is red', 'is this number trustworthy'.", _p({"month": MONTH})),
    "get_contribution_bridge": (get_contribution_bridge, "Contribution-margin variance bridge vs last month: volume, product mix, "
                                "price per hour and each cost-to-serve component per hour (GPU, shared pool, unused commitment, "
                                "cloud, payment fees, support, success), plus the customers and workloads that moved it.",
                                _p({"month": MONTH})),
    "get_margin_sensitivity": (get_margin_sensitivity, "Contribution margin % for price change x cost-to-serve change, and "
                               "contribution by volume change, on the latest month's run rate.", _p({})),
    "get_control_queue": (get_control_queue, "The unresolved queue: budget variances to explain, reconciliation breaks, open "
                          "close tasks, AP bills to review, cash-application and billing exceptions, overdue receivables, cost "
                          "anomalies, renewals at risk and KPIs at red, each with owner, amount, age, threshold and action.", _p({})),
    "get_invoice_detail": (get_invoice_detail, "Everything about one customer invoice (PINV…, INV-…, or a Stripe in_… id): "
                           "header, terms, lines, tax and currency, payments, disputes, journal entries, the Stripe invoice, "
                           "and checks that lines, ledger and Stripe agree; plus a link to its PDF.",
                           _p({"invoice_ref": {"type": "string"}}, ["invoice_ref"])),
    "get_contracts": (get_contracts, "Committed-use customer contracts: RPO, current RPO (next 12 months), contracted ARR "
                      "vs run-rate ARR, burn pace (usage vs commitment), projected shortfall / overage, renewal base, "
                      "revenue at risk, prepaid credit pools; per contract and as a monthly trend.",
                      _p({"month": MONTH, "customer_id": {"type": "string"}})),
    "get_driver_bridges": (get_driver_bridges, "Bridges explaining a month's change: gross margin (volume, price, cost to "
                           "serve, services), net burn (revenue, cost of revenue, payroll, opex, capex, working capital), "
                           "cloud cost by product (demand, efficiency, rate, shared, commitment) and headcount (hires, leavers).",
                           _p({"month": MONTH})),
    "get_gpu_efficiency": (get_gpu_efficiency, "GPU efficiency: idle share and idle cost, commitment coverage and "
                           "utilization, unused commit cost, vendor purchase commitments remaining, magic number trend.",
                           _p({"months": {"type": "integer"}})),
    "get_cost_anomalies": (get_cost_anomalies, "Daily cloud/GPU cost anomalies (3 sigma and $500 vs trailing 28 days) with owner team.",
                           _p({"days": {"type": "integer"}})),
    "get_procurement": (get_procurement, "Procurement savings (negotiated GPU rate cuts, early-pay discounts) by month and "
                        "year to date, and remaining vendor purchase commitments.", _p({"months": {"type": "integer"}})),
    "get_treasury_sweep": (get_treasury_sweep, "Simulated treasury sweeps over 13 weeks: operating account kept at six weeks "
                           "of outflows, excess to the money market, surplus into T-bills; interest earned; cash by legal entity.", _p({})),
    "get_budget_vs_actual": (get_budget_vs_actual, "Company budget vs. actual for a month by DEPARTMENT and GL ACCOUNT (not "
                             "projects: for a project's budget or overrun use get_projects), with alerts, "
                             "and THIS fiscal year's full-year forecast vs budget (fy_forecast, fy_forecast_variance). "
                             "Use for 'where will we land this year versus budget'.",
                             _p({"month": MONTH, "department": {"type": "string", "description": "ENG, INF, SAL, PS, GA or NONE"},
                                 "alerts_only": {"type": "boolean"}})),
    "get_variance_case": (get_variance_case, "The full case file for one budget variance: pass alert_id, or account (e.g. 'usage revenue') "
                          "and month, or nothing for the month's largest. Use for 'take me through the X variance'. Returns "
                          "what happened (month, YTD, full year), the source journal lines, the reconciliation chain from "
                          "source system to GL to reported actual, the root cause decomposed into drivers and classified, "
                          "the owner, and the CFO's decision choices with full-year effect. For recommended actions, reason from this evidence.",
                          _p({"alert_id": {"type": "string"}, "account": {"type": "string", "description": "account id or name, e.g. usage revenue"},
                              "month": MONTH})),
    "get_variance_drivers": (get_variance_drivers, "The journal lines behind a budget alert (alert_id from get_budget_vs_actual).",
                             _p({"alert_id": {"type": "string"}}, ["alert_id"])),
    "get_unit_economics": (get_unit_economics, "Customer margins (gross, contribution, vs. floor) and product cost to serve.",
                           _p({"month": MONTH, "customer_id": {"type": "string"}, "below_floor_only": {"type": "boolean"}})),
    "get_revenue_movements": (get_revenue_movements, "MRR bridge (new, expansion, contraction, churn) for a month, or one customer's history.",
                              _p({"month": MONTH, "customer_id": {"type": "string"}})),
    "get_tech_spend": (get_tech_spend, "Cloud and GPU spend (what we spent with GCP / Nimbus) for a month by vendor, team, category or model, with tagging coverage.",
                       _p({"month": MONTH, "group_by": {"type": "string", "enum": ["vendor", "team", "category", "model"]}})),
    "get_gpu_capacity_and_forecast": (get_gpu_capacity_and_forecast, "Reserved GPU use vs. commit, 3-month spend forecast, vendor renewals.", _p({})),
    "get_projects": (get_projects, "Project financials: budget, EAC, variance at completion (how far over/under budget "
                     "a project will finish), % complete, earned, billed, unbilled, and project exceptions.",
                     _p({"project_id": {"type": "string"}})),
    "get_contract_funding": (get_contract_funding,
                             "Contract and CLIN funding used vs. funded, with 75%/90% alerts. The federal contract is "
                             "C-105 (project P-105, type federal_tm). Filter by contract_id or project_id, or omit both for all.",
                             _p({"contract_id": {"type": "string"}, "project_id": {"type": "string"}})),
    "get_billing_status": (get_billing_status, "Billing status per project, the next billing run, and invoice validation exceptions.", _p({})),
    "get_ar_aging": (get_ar_aging, "AR aging buckets now, recent DSO/CEI, and chronic late payers.",
                     _p({"customer_id": {"type": "string"}})),
    "get_collections_queue": (get_collections_queue, "Ranked collections queue and invoices on hold (disputes, cash-application issues).",
                              _p({"limit": {"type": "integer", "minimum": 1, "maximum": 40}})),
    "get_ar_exceptions": (get_ar_exceptions, "Cash-application exceptions and the dispute log.", _p({})),
    "get_ap_review_queue": (get_ap_review_queue, "Vendor bills that need review, with reasons, and AP routing totals.", _p({})),
    "get_reconciliation_status": (get_reconciliation_status, "Every reconciliation check: passing and failing periods.",
                                  _p({"failing_only": {"type": "boolean"}})),
    "get_forecast": (get_forecast, "Rolling 18-month driver-based forecast (P&L, EBITDA, cash) for a scenario (base, "
                     "upside, downside), plus each scenario's next-12-month revenue, runway and cash-out month. Not "
                     "budget vs actual: for this year versus budget use get_budget_vs_actual.", _p({"scenario": SCENARIO})),
    "get_forecast_changes": (get_forecast_changes, "How the forecast changed since the previous close: this close's "
                             "forecast vs the one as of last close (same engine and levers), by month, with the starting-point "
                             "drivers that moved, and stored daily snapshots.", _p({"scenario": SCENARIO})),
    "get_forecast_error_by_driver": (get_forecast_error_by_driver, "Forecast error by DRIVER: the engine re-run as of each "
                                     "of the last closes vs actuals in DOLLARS, split into existing customers, new customers, services, "
                                     "cost volume vs cost rate, payroll and other opex, with bias and average error per driver.",
                                     _p({"versions": {"type": "integer"}, "horizon": {"type": "integer"}})),
    "get_forecast_accuracy": (get_forecast_accuracy, "How accurate and biased past forecasts were: % error and % bias by P&L "
                              "line (revenue, cogs, opex, ebitda) and months ahead. Use for 'how biased / accurate were our "
                              "forecasts'. For which DRIVER caused the error in dollars, use get_forecast_error_by_driver.", _p({})),
    "get_headcount_plan": (get_headcount_plan, "Headcount plan and loaded payroll by month, the open/approved roles, and "
                           "the risk-adjusted workforce plan (hiring probability, start slippage, attrition and backfills, "
                           "merit increases, recruiting and equipment cost) vs plan.",
                           _p({"scenario": SCENARIO})),
    "get_budget_build": (get_budget_build, "NEXT fiscal year's budget being built: bottom-up department asks vs top-down "
                         "board targets, with the gap. Not this year's budget vs actual.", _p({})),
    "get_shared_cost_allocation": (get_shared_cost_allocation, "Shared overhead (software, rent, professional fees) "
                                   "allocated to departments by headcount for a month.", _p({"month": MONTH})),
    "get_working_capital": (get_working_capital, "AR, AP, net working capital, DSO, DPO and cash conversion cycle by month.", _p({})),
    "get_revenue_recognition": (get_revenue_recognition, "ASC 606: deferred revenue roll-forward, contract assets/liabilities, "
                                "and the revenue adjustment vs the GL, with project detail for a month.", _p({"month": MONTH})),
    "get_cash_forecast": (get_cash_forecast, "13-week cash forecast, cash by bank account, and covenant/policy breaches "
                          "(minimum cash, runway, liquidity).", _p({})),
    "get_payment_runs": (get_payment_runs, "Proposed vendor payment runs for unpaid bills, with early-pay discounts.", _p({})),
    "get_close_status": (get_close_status, "Month-end close checklist status, accruals and prepaid amortization for a month. Use for "
                         "'what is blocking the close / sign-off?': open checklist tasks are the blockers.",
                         _p({"month": MONTH})),
    "get_pricing_analysis": (get_pricing_analysis, "Price-change simulations (revenue and margin impact) and discount leakage.", _p({})),
    "get_cap_table_and_fundraise": (get_cap_table_and_fundraise, "Cap table and fundraise scenarios: price, dilution, "
                                    "option-pool top-up, and whether cash lasts until the round closes.", _p({})),
    "get_commissions": (get_commissions, "Sales commission statements for a month: credited new/expansion ARR (after "
                        "credit splits), comp credit, clawbacks, quota attainment, base and accelerator commission, SPIFFs, "
                        "the comp plan version, plus year to date and the customer credits behind them. For plan versions, "
                        "splits, SPIFF programs and deferred commissions (ASC 340-40) use get_commissions_dashboard.", _p({"rep_id": {"type": "string"}, "month": MONTH})),
    "price_deal": (price_deal, "Deal desk pricing check (read-only): revenue, cost and gross margin per product at a "
                   "discount, the guardrail checks (discount band, margin floor, term, commit, payment terms, SLA, unlimited "
                   "usage, non-standard terms), revenue-recognition flags, the risk view, and who must approve.",
                   _p({"customer": {"type": "string"},
                       "lines": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                 "properties": {"product_id": {"type": "string", "enum": ["batch_base", "batch_pro", "stream"]},
                                                "hours_per_month": {"type": "number"}}, "required": ["product_id", "hours_per_month"]}},
                       "discount_pct": {"type": "number"}, "term_months": {"type": "integer"}, "monthly_commit": {"type": "number"},
                       "payment_terms_days": {"type": "integer"}, "sla": {"type": "string", "description": "standard or a description of the custom SLA"},
                       "unlimited_usage": {"type": "boolean"}, "prepaid_credits": {"type": "boolean"}, "free_months": {"type": "integer"},
                       "custom_terms": {"type": "string"}},
                      ["customer", "lines"])),
    "get_customer_detail": (get_customer_detail, "Everything about one customer (IDs like SS-001, MM-003, EN-002, FD-001): monthly revenue and margin, invoices "
                            "(open, paid, disputed), payments, lifecycle events, projects and open alerts.",
                            _p({"customer_id": {"type": "string"}}, ["customer_id"])),
    "get_vendor_detail": (get_vendor_detail, "Everything about one vendor: bills, AP postings and payments, bill PDFs "
                          "and their review status, contract, and what is still owed. For how much was SPENT with a vendor "
                          "in a month, use get_tech_spend.", _p({"vendor_id": {"type": "string"}}, ["vendor_id"])),
    "get_project_detail": (get_project_detail, "Everything about one project (IDs like P-101; not customers): monthly budget, EAC, earned, billed, "
                           "unbilled and deferred, its invoices and exceptions.", _p({"project_id": {"type": "string"}}, ["project_id"])),
    "get_tax_and_fx": (get_tax_and_fx, "Sales tax/VAT/GST and FX gains/losses: one month by currency and regime, plus "
                       "all-time totals by currency and an all_time_total grand total (call once; no need to add months up).",
                       _p({"month": MONTH})),
}


def openai_tool_specs(extra=None):
    specs = [{"type": "function", "function": {"name": n, "description": d, "parameters": p}}
             for n, (_, d, p) in TOOLS.items()]
    return specs + (extra or [])


def run_tool(wh, name, args):
    """Run a read tool. `_as_of` (from the workspace Period control) becomes the tool's month when the tool takes one
    and none was given; tools without a month ignore it."""
    import inspect
    fn = TOOLS[name][0]
    args = dict(args or {})
    as_of = args.pop("_as_of", None)
    if as_of and "month" in inspect.signature(fn).parameters and not args.get("month"):
        args["month"] = str(as_of)[:7]
    return fn(wh, **args)
