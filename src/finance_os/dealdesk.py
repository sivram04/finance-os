"""Deal desk (M9): price a deal, check it against the guardrails, route it, and produce the quote.

A deal is a customer, the products with expected monthly audio hours, a discount off list, a term and a monthly
minimum commit. evaluate() works out, per product and in total:
  revenue    hours × list price × (1 − discount)
  cost       hours × cost to serve per hour (last 3 closed months, from marts.fct_unit_economics_monthly)
  margin     revenue − cost, and gross margin %
and checks the guardrails (seeds/deal_guardrails.csv, seeds/deal_policy.csv):
  DISCOUNT   the discount fits the band for the deal's monthly volume
  MARGIN     projected gross margin ≥ the revenue-weighted product floor (seeds/margin_floors.csv) + buffer
  TERM       term ≤ the maximum Sales may sign
  COMMIT     a discounted deal carries a monthly minimum commit ≥ the policy share of expected revenue
and adds the risk view a deal desk reviews (risk(), informational, not a guardrail):
  cost to serve P10/P50/P90   monthly cost per hour by product over the last 12 closed months, and the deal's
                              gross margin if cost runs at the P90 month
  credit exposure             billed in arrears on the segment's terms: about (1 + terms/30) months of revenue
                              outstanding at peak, plus the customer's open AR, against the credit limit
  commission impact           first-year commission at the plan in effect, as a share of first-year gross margin,
                              and months of gross margin to earn it back
  discount distribution       where this discount sits among the discounts customers actually got (last 12 months)
Inside every guardrail → auto-approved. Outside any → routed to Finance with the reasons (an approval card in the
workspace, decided and audited like every other action). quote_pdf() renders the quote / order form.
"""
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

CENT = Decimal("0.01")


def _d(x):
    return Decimal(str(x))


def _money(x):
    return f"${_d(x).quantize(CENT, ROUND_HALF_UP):,.2f}"


def inputs(wh):
    """Prices, unit costs, floors and guardrails from the warehouse."""
    prices = {r["product_id"]: _d(r["list_price_per_hour"]) for r in
              wh.query("select product_id, list_price_per_hour from staging.stg_synthetic__products")}
    costs = {r["product_id"]: _d(r["cost_per_hour"]) for r in wh.query("""
        select product_id, sum(cogs) / nullif(sum(audio_hours), 0) as cost_per_hour
        from marts.fct_unit_economics_monthly
        where month > (select max(month) from marts.fct_kpi_monthly) - interval 3 month
          and month <= (select max(month) from marts.fct_kpi_monthly)
        group by 1""")}
    floors = {r["product_id"]: _d(r["gross_margin_floor_pct"]) for r in wh.query("select * from seeds.margin_floors")}
    bands = wh.query("select * from seeds.deal_guardrails order by min_hours_month")
    policy = {r["rule_id"]: _d(r["value"]) for r in wh.query("select rule_id, value from seeds.deal_policy")}
    return prices, costs, floors, bands, policy


TERMS_DAYS = {"mid_market": 30, "enterprise": 45}
ENTERPRISE_ARR = Decimal(600_000)  # deals at or above this annual revenue are enterprise (terms, comp plan)


def _pct(values, q):
    v = sorted(values)
    if not v:
        return None
    k = (len(v) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def risk(wh, ev, policy):
    """The deal desk's risk view for an evaluated deal (see the module docstring)."""
    rev, annual = _d(ev["monthly_revenue"]), _d(ev["annual_revenue"])
    segment = "enterprise" if annual >= ENTERPRISE_ARR else "mid_market"
    hist = {}
    for r in wh.query("""select product_id, month, sum(cogs) / nullif(sum(audio_hours), 0) as cph
                         from marts.fct_unit_economics_monthly
                         where month > (select max(month) from marts.fct_kpi_monthly) - interval 12 month
                           and month <= (select max(month) from marts.fct_kpi_monthly)
                         group by 1, 2"""):
        if r["cph"] is not None:
            hist.setdefault(r["product_id"], []).append(float(r["cph"]))
    cts, p90_cost = [], Decimal(0)
    for l in ev["lines"]:
        h = hist.get(l["product_id"], [])
        p10, p50, p90 = (_pct(h, q) for q in (0.1, 0.5, 0.9))
        cts.append({"product_id": l["product_id"], "p10": p10, "p50": p50, "p90": p90, "months": len(h)})
        p90_cost += _d(l["hours_per_month"]) * _d(p90 or l["cost_per_hour"])
    gm_p90 = float(((rev - p90_cost) / rev).quantize(Decimal("0.0001"))) if rev else None

    terms = TERMS_DAYS[segment]
    open_ar = wh.query("""select coalesce(sum(balance), 0) as v from marts.fct_ar_invoices
                          where customer_id = ? and balance > 0""", [ev.get("customer") or ""])
    open_ar = _d(open_ar[0]["v"]) if open_ar else Decimal(0)
    peak = rev * (1 + _d(terms) / 30) + open_ar
    limit = policy.get("CREDIT-LIMIT", Decimal(1_500_000))

    plan = wh.query("""select p.plan_id, p.base_rate from seeds.comp_plans p join seeds.sales_reps r using (rep_id)
                       where r.segment_focus = ? and current_date between p.effective_from and p.effective_to
                       order by p.rep_id limit 1""", [segment])
    if not plan:
        plan = wh.query("""select p.plan_id, p.base_rate from seeds.comp_plans p join seeds.sales_reps r using (rep_id)
                           where r.segment_focus = ? order by p.effective_from desc limit 1""", [segment])
    rate = _d(plan[0]["base_rate"]) if plan else Decimal(0)
    commission = annual * rate
    gm_year = (rev - _d(ev["monthly_cost"])) * 12
    disc = [float(r["discount_pct"]) for r in wh.query("""
        select avg(discount_pct) as discount_pct from marts.fct_discount_leakage
        where segment <> 'self_serve' and month > (select max(month) from marts.fct_kpi_monthly) - interval 12 month
        group by customer_id""") if r["discount_pct"] is not None]
    d = float(ev["discount_pct"])
    return {
        "segment": segment,
        "cost_to_serve": cts, "gross_margin_pct_at_p90_cost": gm_p90,
        "credit": {"terms_days": terms, "open_ar": float(open_ar), "peak_exposure": float(peak.quantize(CENT)),
                   "credit_limit": float(limit), "within_limit": peak <= limit},
        "commission": {"plan_id": plan[0]["plan_id"] if plan else None, "rate": float(rate),
                       "first_year_commission": float(commission.quantize(CENT)),
                       "share_of_first_year_gross_margin": float((commission / gm_year).quantize(Decimal("0.0001"))) if gm_year else None,
                       "payback_months": float((commission / (gm_year / 12)).quantize(Decimal("0.1"))) if gm_year > 0 else None},
        "discounts": {"customers": len(disc), "p25": _pct(disc, 0.25), "median": _pct(disc, 0.5), "p75": _pct(disc, 0.75),
                      "max": max(disc) if disc else None,
                      "this_deal_percentile": round(sum(1 for x in disc if x < d) / len(disc), 2) if disc else None},
    }


def evaluate(wh, deal):
    """deal: {customer, lines: [{product_id, hours_per_month}], discount_pct, term_months, monthly_commit}."""
    prices, costs, floors, bands, policy = inputs(wh)
    disc = _d(deal.get("discount_pct") or 0)
    term = int(deal.get("term_months") or 12)
    commit = _d(deal.get("monthly_commit") or 0)
    lines, unknown = [], []
    for l in deal["lines"]:
        p = l["product_id"]
        if p not in prices:
            unknown.append(p)
            continue
        hours = _d(l["hours_per_month"])
        rev = (hours * prices[p] * (1 - disc)).quantize(CENT, ROUND_HALF_UP)
        cost = (hours * costs.get(p, Decimal(0))).quantize(CENT, ROUND_HALF_UP)
        lines.append({"product_id": p, "hours_per_month": float(hours), "list_price": float(prices[p]),
                      "net_price": float((prices[p] * (1 - disc)).quantize(Decimal("0.0001"))),
                      "cost_per_hour": float(costs.get(p, 0)), "monthly_revenue": float(rev), "monthly_cost": float(cost),
                      "gross_margin_pct": float(((rev - cost) / rev).quantize(Decimal("0.0001"))) if rev else None,
                      "floor_pct": float(floors.get(p, 0))})
    if unknown:
        return {"error": f"Unknown products {unknown}. Products: {sorted(prices)}"}
    rev = sum(_d(l["monthly_revenue"]) for l in lines)
    cost = sum(_d(l["monthly_cost"]) for l in lines)
    hours = sum(_d(l["hours_per_month"]) for l in lines)
    gm = (rev - cost) / rev if rev else Decimal(0)
    floor = (sum(_d(l["floor_pct"]) * _d(l["monthly_revenue"]) for l in lines) / rev if rev else Decimal(0)) + policy.get("MARGIN-BUFFER", Decimal(0))
    band = next((b for b in bands if _d(b["min_hours_month"]) <= hours < _d(b["max_hours_month"])), bands[-1])
    max_disc = _d(band["max_discount_pct"])
    checks = [
        {"rule": "DISCOUNT", "passed": disc <= max_disc,
         "detail": f"{disc:.1%} discount vs {max_disc:.0%} allowed for {hours:,.0f} hours/month ({band['band_id']})"},
        {"rule": "MARGIN", "passed": gm >= floor,
         "detail": f"projected gross margin {gm:.1%} vs blended floor {floor:.1%}"},
        {"rule": "TERM", "passed": term <= int(policy["MAX-TERM-MONTHS"]),
         "detail": f"{term} months vs {int(policy['MAX-TERM-MONTHS'])} max"},
        {"rule": "COMMIT", "passed": disc == 0 or commit >= rev * policy["MIN-COMMIT-PCT"],
         "detail": f"minimum commit {_money(commit)}/month vs {_money(rev * policy['MIN-COMMIT-PCT'])} required for a discount"},
    ]
    failed = [c for c in checks if not c["passed"]]
    out = {
        "customer": deal.get("customer"), "lines": lines, "discount_pct": float(disc), "term_months": term,
        "monthly_commit": float(commit), "monthly_revenue": float(rev), "monthly_cost": float(cost),
        "gross_margin_pct": float(gm.quantize(Decimal("0.0001"))), "floor_pct": float(floor.quantize(Decimal("0.0001"))),
        "annual_revenue": float(rev * 12), "contract_value": float(rev * term), "band": band["band_id"],
        "checks": checks, "route": "finance_review" if failed else "auto_approve",
        "reasons": [c["detail"] for c in failed],
    }
    out["risk"] = risk(wh, out, policy)
    return out


def quote_pdf(deal_id, evaluation, out_dir: Path, valid_days=30):
    """Quote / order form: products, prices, term, commit, totals, and the approval status."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{deal_id}.pdf"
    st = getSampleStyleSheet()
    e = evaluation
    story = [Paragraph("Echo Labs, Inc. — Quote and Order Form", st["Title"]),
             Paragraph(f"Quote {deal_id} · {date.today():%d %b %Y} · valid until {date.today() + timedelta(days=valid_days):%d %b %Y}", st["Normal"]),
             Paragraph(f"Customer: {e['customer']}", st["Normal"]), Spacer(1, 12)]
    rows = [["Product", "Hours / month", "List $/hr", "Your $/hr", "Monthly"]]
    for l in e["lines"]:
        rows.append([l["product_id"], f"{l['hours_per_month']:,.0f}", f"{l['list_price']:.4f}", f"{l['net_price']:.4f}",
                     _money(l["monthly_revenue"])])
    rows.append(["Total", "", "", "", _money(e["monthly_revenue"])])
    story.append(Table(rows, colWidths=[1.6 * inch, 1.2 * inch, 1.0 * inch, 1.0 * inch, 1.4 * inch],
                       style=TableStyle([("FONT", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONT", (0, -1), (-1, -1), "Helvetica-Bold"),
                                         ("ALIGN", (1, 1), (-1, -1), "RIGHT"), ("LINEBELOW", (0, 0), (-1, 0), 0.5, "black"),
                                         ("LINEABOVE", (0, -1), (-1, -1), 0.5, "black")])))
    story += [Spacer(1, 12),
              Paragraph(f"Discount off list: {e['discount_pct']:.1%} · Term: {e['term_months']} months · "
                        f"Minimum commit: {_money(e['monthly_commit'])} per month", st["Normal"]),
              Paragraph(f"Estimated contract value: {_money(e['contract_value'])}", st["Normal"]),
              Paragraph("Usage is billed monthly in arrears at the prices above; volume tiers do not stack with this discount. "
                        "Any shortfall below the minimum commit is billed as a true-up.", st["Normal"]),
              Spacer(1, 24),
              Paragraph("Accepted for the customer: ____________________   Date: ________", st["Normal"]),
              Paragraph("Approved for Echo Labs: ______________________   Date: ________", st["Normal"])]
    SimpleDocTemplate(str(path), pagesize=LETTER).build(story)
    return path
