"""Implementation projects (raw_projects, M6): contracts, budgets, POs, timesheets, subcontractor bills,
ODCs, milestones, project invoices and PM estimates to complete.

- Fixed fee: labor cost follows budget × cost_overrun over the actual duration; milestones are billed
  on acceptance (unless bill: false).
- T&M / T&M with cap / federal T&M: hours are scaled so labor + ODC earned through the end of data hits
  billed_target; invoiced monthly in arrears on the 5th (labor by category, ODC at cost; CLINs for federal).
- PM estimate to complete each month: max(planned total cost − actual − open commitments, 0). The PM
  recognizes a fixed-fee overrun from the project's midpoint on.
Labor cost uses a loaded hourly rate from salary, employer tax and benefits.
"""
import calendar
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

CENTS = Decimal("0.01")
QUARTER = Decimal("0.25")


def _cents(x):
    return x.quantize(CENTS, rounding=ROUND_HALF_UP)


def _quarter_hours(x):
    return (x / QUARTER).quantize(Decimal(1), rounding=ROUND_HALF_UP) * QUARTER


def _months(start, end):
    out, y, m = [], start.year, start.month
    while date(y, m, 1) <= end:
        out.append(date(y, m, 1))
        y, m = y + (m == 12), m % 12 + 1
    return out


def _month_end(d):
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def _fridays(month):
    d = month
    while d.weekday() != 4:
        d += timedelta(days=1)
    out = []
    while d.month == month.month:
        out.append(d)
        d += timedelta(days=7)
    return out


def _active(e, day):
    return e["hire_date"] <= day and (e["termination_date"] is None or e["termination_date"] > day)


def build_projects(cfg, employees, rng):
    window_end = cfg["window"]["end"]
    tax = Decimal(cfg["payroll"]["employer_tax_pct"])
    benefits = Decimal(cfg["payroll"]["benefits_per_month"])
    std_hours = Decimal(cfg["labor_cost_policy"]["standard_hours_year"])
    category_of = cfg["labor_category_by_title"]

    def cost_rate(e):
        return _cents((e["annual_salary"] * (1 + tax) + benefits * 12) / std_hours)

    t = defaultdict(list)
    seq = defaultdict(int)

    def next_id(prefix):
        seq[prefix] += 1
        return f"{prefix}{seq[prefix]:05d}"

    for p in cfg["projects"]:
        c = p["contract"]
        pid, cid = p["project_id"], p["customer_id"]
        ctype = c["type"]
        is_tm = ctype in ("tm", "tm_cap", "federal_tm")
        planned_end = p["end"]
        actual_end = p.get("end_actual", planned_end)
        overrun = Decimal(p.get("cost_overrun", "1"))

        t["contracts"].append({
            "contract_id": c["contract_id"], "customer_id": cid, "contract_type": ctype,
            "start_date": p["start"], "end_date": planned_end, "contract_value": Decimal(c["value"]),
            "ceiling": Decimal(c.get("ceiling") or c.get("cap") or c["value"]),
            "funded_amount": Decimal(c.get("funded") or c["value"]),
            "payment_terms_days": c["payment_terms_days"], "is_federal": ctype == "federal_tm"})
        for cl in c.get("clins", []):
            t["clins"].append({"contract_id": c["contract_id"], "clin_id": cl["clin_id"], "description": cl["description"],
                               "ceiling": Decimal(cl["ceiling"]), "funded": Decimal(cl["funded"])})
        for cat, rate in p.get("rates", {}).items():
            t["contract_rates"].append({"contract_id": c["contract_id"], "labor_category": cat, "bill_rate": Decimal(rate)})
        t["projects"].append({"project_id": pid, "contract_id": c["contract_id"], "customer_id": cid,
                              "project_name": p["name"], "project_type": ctype,
                              "start_date": p["start"], "planned_end_date": planned_end})
        for cost_type, amt in p["budget"].items():
            t["project_budgets"].append({"project_id": pid, "cost_type": cost_type, "budget_amount": Decimal(amt)})

        # Team: employees whose title maps to each needed category, active at project start.
        team = []
        for cat, n in sorted(p["team"].items()):
            pool = sorted((e for e in employees if category_of.get(e["title"]) == cat and _active(e, p["start"])),
                          key=lambda e: e["employee_id"])
            team += [(e, cat) for e in rng.sample(pool, min(n, len(pool)))]

        months_planned = _months(p["start"], actual_end)
        months = [m for m in months_planned if m <= window_end]

        # Monthly hours per team member (before scaling), with noise.
        raw = {}
        for m in months:
            for e, cat in team:
                if _active(e, m):
                    raw[(m, e["employee_id"])] = Decimal(rng.randint(80, 120)) / 100
        rate_of = {e["employee_id"]: cost_rate(e) for e, _ in team}
        cat_of = {e["employee_id"]: cat for e, cat in team}
        bill_rate = {cat: Decimal(r) for cat, r in p.get("rates", {}).items()}

        odc_total_planned = Decimal(p["budget"].get("odc", "0")) * overrun
        odc_month = odc_total_planned / len(months_planned)

        if is_tm:
            labor_target = Decimal(p["billed_target"]) - odc_month * len(months)
            value = sum(w * bill_rate[cat_of[eid]] for (m, eid), w in raw.items())
            scale = labor_target / value
        else:
            labor_cost_target = Decimal(p["budget"]["labor"]) * overrun * len(months) / len(months_planned)
            value = sum(w * rate_of[eid] for (m, eid), w in raw.items())
            scale = labor_cost_target / value

        hours_by_month_cat = defaultdict(Decimal)
        for (m, eid), w in sorted(raw.items()):
            fridays = _fridays(m)
            weekly = _quarter_hours(w * scale / len(fridays))
            for f in fridays:
                if f > window_end or weekly <= 0:
                    continue
                t["timesheets"].append({"timesheet_id": next_id("TS"), "employee_id": eid, "project_id": pid,
                                        "week_ending": f, "labor_category": cat_of[eid], "hours": weekly,
                                        "approved": True})
                hours_by_month_cat[(m, cat_of[eid])] += weekly

        # ODCs, mid-month.
        for m in months:
            t["odc_expenses"].append({"expense_id": next_id("ODC"), "project_id": pid, "expense_date": m.replace(day=14),
                                      "amount": _cents(odc_month), "description": "Travel and cloud test environments"})

        # POs and subcontractor bills against them, evenly over the planned duration.
        for po in p.get("pos", []):
            po_id = next_id("PO")
            t["purchase_orders"].append({"po_id": po_id, "project_id": pid, "vendor_id": po["vendor_id"],
                                         "po_date": po["date"], "amount": Decimal(po["amount"]),
                                         "description": po["description"]})
            per_month = _cents(Decimal(po["amount"]) / len(months_planned))
            for m in months:
                t["subcontractor_bills"].append({"bill_id": next_id("SB"), "project_id": pid, "vendor_id": po["vendor_id"],
                                                 "po_id": po_id, "bill_date": _month_end(m), "amount": per_month,
                                                 "description": po["description"]})

        # Billing.
        def invoice(inv_date, service_month, lines):
            inv_id = next_id("PINV")
            total = sum(l["amount"] for l in lines)
            t["project_invoices"].append({"invoice_id": inv_id, "project_id": pid, "contract_id": c["contract_id"],
                                          "customer_id": cid, "invoice_date": inv_date, "service_month": service_month,
                                          "amount": total})
            for n, l in enumerate(lines, 1):
                t["project_invoice_lines"].append({"invoice_id": inv_id, "line_no": n, **l})

        if is_tm:
            for m in months:
                inv_date = _month_end(m) + timedelta(days=5)
                if inv_date > window_end:
                    continue
                lines = []
                for (mm, cat), hours in sorted(hours_by_month_cat.items()):
                    if mm == m:
                        lines.append({"line_type": "labor", "clin_id": "0001" if ctype == "federal_tm" else None,
                                      "labor_category": cat, "milestone_id": None, "hours": hours,
                                      "rate": bill_rate[cat], "amount": _cents(hours * bill_rate[cat])})
                lines.append({"line_type": "odc", "clin_id": "0002" if ctype == "federal_tm" else None,
                              "labor_category": None, "milestone_id": None, "hours": None, "rate": None,
                              "amount": _cents(odc_month)})
                invoice(inv_date, m, lines)
        for ms in p.get("milestones", []):
            ms_id = next_id("MS")
            t["milestones"].append({"milestone_id": ms_id, "project_id": pid, "milestone_name": ms["name"],
                                    "amount": Decimal(ms["amount"]), "accepted_date": ms["accept"]})
            if ms["accept"] and ms.get("bill", True) and ms["accept"] + timedelta(days=3) <= window_end:
                invoice(ms["accept"] + timedelta(days=3), None,
                        [{"line_type": "milestone", "clin_id": None, "labor_category": None, "milestone_id": ms_id,
                          "hours": None, "rate": None, "amount": Decimal(ms["amount"])}])

        # PM estimate to complete at each month end.
        budget_total = sum(Decimal(v) for v in p["budget"].values())
        midpoint = p["start"] + (planned_end - p["start"]) / 2
        for m in months:
            me = _month_end(m)
            target = budget_total * (overrun if (not is_tm and me >= midpoint) else 1)
            labor = sum(Decimal(ts["hours"]) * rate_of[ts["employee_id"]] for ts in t["timesheets"]
                        if ts["project_id"] == pid and ts["week_ending"] <= me)
            subs = sum(b["amount"] for b in t["subcontractor_bills"] if b["project_id"] == pid and b["bill_date"] <= me)
            odc = sum(o["amount"] for o in t["odc_expenses"] if o["project_id"] == pid and o["expense_date"] <= me)
            commitments = sum(po["amount"] for po in t["purchase_orders"] if po["project_id"] == pid and po["po_date"] <= me)
            open_commit = max(commitments - sum(b["amount"] for b in t["subcontractor_bills"]
                                                if b["project_id"] == pid and b["po_id"] and b["bill_date"] <= me), 0)
            etc = max(target - labor - subs - odc - open_commit, 0) if me < actual_end else Decimal(0)
            t["pm_estimates"].append({"project_id": pid, "as_of_month": m, "etc_amount": _cents(etc)})

    for b in cfg.get("bills_without_po", []):
        t["subcontractor_bills"].append({"bill_id": next_id("SB"), "project_id": b["project_id"], "vendor_id": b["vendor_id"],
                                         "po_id": None, "bill_date": b["date"], "amount": Decimal(b["amount"]),
                                         "description": b["description"]})
    t["subcontractors"] = [dict(s) for s in cfg["subcontractors"]]
    return dict(t)
