"""Read-only tools the assistant can call (design §9.2, FR-11.1). No free-form SQL: each tool is a fixed,
parameterised query over the marts, recon tables or metric catalog, and every result names its source.

Results are JSON-ready: decimals become floats, dates ISO strings. Long results are cut to MAX_ROWS with a
note, so the model is told it is seeing part of the data rather than guessing.
"""
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


def _result(rows, source, note=None, **extra):
    out = {"source": source, "row_count": len(rows), "rows": rows[:MAX_ROWS], **extra}
    if len(rows) > MAX_ROWS:
        out["note"] = f"Showing {MAX_ROWS} of {len(rows)} rows; narrow the filters to see the rest."
    if note:
        out["note"] = (out.get("note", "") + " " + note).strip()
    return out


# ---- tool implementations -------------------------------------------------------------------------

def get_kpis(wh, month=None, metrics=None):
    m = _month(month, wh)
    rows = wh.query("""
        select k.metric_name, c.label, c.unit, k.value
        from marts.fct_kpi_monthly k join seeds.metric_catalog c using (metric_name)
        where k.month = ?::date and (? is null or list_contains(?::varchar[], k.metric_name))
        order by k.metric_name""", [m, metrics, metrics])
    unknown = sorted(set(metrics or []) - {r["metric_name"] for r in rows})
    note = f"Unknown metric names: {', '.join(unknown)}. Valid names: {', '.join(METRIC_NAMES)}." if unknown else None
    return _result(rows, "marts.fct_kpi_monthly + seeds.metric_catalog", note=note, month=m)


def get_kpi_trend(wh, metric, start_month=None, end_month=None):
    rows = wh.query("""
        select strftime(month, '%Y-%m') as month, value from marts.fct_kpi_monthly
        where metric_name = ? and month >= coalesce(?::date, date '1900-01-01')
          and month <= coalesce(?::date, date '2999-01-01')
        order by month""", [metric, start_month and _month(start_month, wh), end_month and _month(end_month, wh)])
    note = None if rows else f"No data for metric '{metric}'. Valid names: {', '.join(METRIC_NAMES)}."
    return _result(rows, "marts.fct_kpi_monthly", note=note, metric=metric)


def get_metric_definition(wh, metric):
    rows = wh.query("select * from seeds.metric_catalog where metric_name = ?", [metric])
    if not rows:
        names = [r["metric_name"] for r in wh.query("select metric_name from seeds.metric_catalog order by 1")]
        return _result([], "seeds.metric_catalog", note=f"Unknown metric. Available: {', '.join(names)}")
    return _result(rows, "seeds.metric_catalog (docs/METRIC_CATALOG.md)")


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
    rows = wh.query("""select strftime(month, '%Y-%m') as month, revenue, cogs, gross_margin_pct, payroll, other_opex,
                              opex, ebitda, closing_cash, financing_to_date, closing_cash_with_raise
                       from marts.fct_forecast_monthly where is_latest and scenario = ? order by month""", [scenario])
    summary = wh.query("select * from marts.fct_scenario_summary order by scenario")
    return _result(rows, "marts.fct_forecast_monthly, marts.fct_scenario_summary", scenario=scenario, scenarios=summary,
                   note="Driver-based forecast as of the last closed month; drivers in seeds/planning_scenarios.csv.")


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
    return _result(rows, "marts.fct_headcount_plan_monthly, seeds.hiring_plan", scenario=scenario, planned_roles=roles)


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


def price_deal(wh, customer, lines, discount_pct=0, term_months=12, monthly_commit=0):
    from finance_os import dealdesk
    ev = dealdesk.evaluate(wh, {"customer": customer, "lines": lines, "discount_pct": discount_pct,
                                "term_months": term_months, "monthly_commit": monthly_commit})
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
    rows = wh.query("""select strftime(month, '%Y-%m') as month, revenue, arr, sm_spend, new_customers, cac, arpa,
                              monthly_logo_churn, ltv, ltv_to_cac, cac_payback_months, revenue_growth_yoy, ebitda_margin,
                              rule_of_40, free_cash_flow, fcf_margin
                       from marts.fct_saas_metrics_monthly order by month desc limit ?""", [int(months)])
    return _result(rows[::-1], "marts.fct_saas_metrics_monthly",
                   note="CAC = S&M spend / new customers (trailing 3 months); LTV = ARPA × gross margin / monthly churn; "
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
    from finance_os import fpa
    _, _, k = _latest_unit_economics(wh)
    rev, cogs, opex = float(k["revenue"]), float(k["cogs"]), float(k["opex"])
    base_growth = float(wh.query("""select avg(value) as g from (select value / lag(value) over (order by month) - 1 as value
                                     from marts.fct_kpi_monthly where metric_name = 'revenue'
                                     order by month desc limit 6) t""")[0]["g"] or 0)
    base_growth = round(min(max(base_growth, -0.05), 0.10), 3)
    table = fpa.runway_sensitivity(float(k["closing_cash"]), rev, cogs / rev, opex,
                                   [-0.02, -0.01, 0, 0.01, 0.02, 0.03], [-0.20, -0.10, 0, 0.10], base_growth)
    return _result(table, "marts.fct_kpi_monthly (last closed month) + finance_os.fpa.runway_sensitivity",
                   base={"cash": float(k["closing_cash"]), "revenue": rev, "cogs_pct": round(cogs / rev, 4), "opex": opex,
                         "revenue_growth_monthly": base_growth},
                   note="Months until cash runs out, by monthly revenue growth (rows) and opex change (columns), "
                        "without new funding. '60+' = not within five years.")


def evaluate_business_case(wh, investment, annual_inflows, discount_rate=None, annual_costs=None, name="Business case"):
    from finance_os import fpa
    out = fpa.business_case(investment, annual_inflows, discount_rate or fpa.DEFAULT_DISCOUNT_RATE, annual_costs, name)
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
                            discount_rate or fpa.DEFAULT_DISCOUNT_RATE)
    out["assumptions"]["arpa_basis"] = "new customers' average monthly revenue in months 2-4 after signup (last 18 months)"
    return {"source": "finance_os.fpa.campaign_case + marts.fct_customer_revenue_monthly, fct_saas_metrics_monthly", **out}


def _p(props, required=()):
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


MONTH = {"type": "string", "description": "Month as YYYY-MM. Omit for the latest month with data."}
# Exact KPI names from the metric catalog (warehouse/metrics/kpis.yml), given to the model in the schema.
METRIC_NAMES = ["revenue", "cogs", "opex", "gross_margin_pct", "gross_burn", "net_burn", "closing_cash",
                "runway_months", "arr", "headcount", "arr_per_employee", "nrr", "grr", "active_customers",
                "new_customers", "churned_customers", "logo_churn_rate", "gross_mrr_churn_rate", "dso_days", "cei",
                "ar_over_60"]
METRIC = {"type": "string", "enum": METRIC_NAMES}
SCENARIO = {"type": "string", "enum": ["base", "upside", "downside"]}

TOOLS = {
    "get_attention_items": (get_attention_items,
                            "Everything currently flagged across all modules (projects, billing, budget, margins, AR, AP, "
                            "vendor renewals, reconciliations). Use first for broad questions like 'what needs attention?'.",
                            _p({})),
    "get_kpis":(get_kpis, "Company KPIs for one month (revenue, ARR, burn, runway, margins, churn, DSO …).",
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
    "get_runway_sensitivity": (get_runway_sensitivity, "Sensitivity table: months of runway by revenue growth and opex "
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
    "get_budget_vs_actual": (get_budget_vs_actual, "Company budget vs. actual for a month by DEPARTMENT and GL ACCOUNT (not "
                             "projects: for a project's budget or overrun use get_projects), with alerts, "
                             "and THIS fiscal year's full-year forecast vs budget (fy_forecast, fy_forecast_variance). "
                             "Use for 'where will we land this year versus budget'.",
                             _p({"month": MONTH, "department": {"type": "string", "description": "ENG, INF, SAL, PS, GA or NONE"},
                                 "alerts_only": {"type": "boolean"}})),
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
    "get_forecast_accuracy": (get_forecast_accuracy, "How accurate past forecasts were (error by line and months ahead).", _p({})),
    "get_headcount_plan": (get_headcount_plan, "Headcount plan and loaded payroll by month, and the open/approved roles.",
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
    "get_commissions": (get_commissions, "Sales commission statements for a month: credited new/expansion ARR, "
                        "clawbacks, quota attainment, base and accelerator commission, plus year to date and the "
                        "customer credits behind them.", _p({"rep_id": {"type": "string"}, "month": MONTH})),
    "price_deal": (price_deal, "Deal desk pricing check (read-only): revenue, cost and gross margin per product at a "
                   "discount, the guardrail checks (discount band, margin floor, term, commit) and whether it would "
                   "auto-approve or need Finance.",
                   _p({"customer": {"type": "string"},
                       "lines": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                 "properties": {"product_id": {"type": "string", "enum": ["batch_base", "batch_pro", "stream"]},
                                                "hours_per_month": {"type": "number"}}, "required": ["product_id", "hours_per_month"]}},
                       "discount_pct": {"type": "number"}, "term_months": {"type": "integer"}, "monthly_commit": {"type": "number"}},
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
    fn = TOOLS[name][0]
    return fn(wh, **args)
