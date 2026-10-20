"""What a live project invoice bills, the way a services team really invoices:

- fixed-fee projects bill milestones: the oldest milestone the customer has accepted that is not yet fully invoiced,
  for what remains of it (a milestone may be billed in parts, e.g. 50% on acceptance). No accepted milestone, no
  invoice: work the customer has not signed off cannot be billed.
- time-and-materials projects bill hours: quarter-hours at the contract's rate for each labor category (split across
  the two most senior categories), with anything left as other direct costs (travel, tools).

Billed-to-date comes from the history's invoice lines plus the live ones, so a milestone is never billed twice.
"""
import csv
import json
from collections import defaultdict
from decimal import ROUND_DOWN, Decimal

from finance_os.paths import ROOT

SRC = ROOT / "data" / "synthetic"
LIVE = ROOT / "data" / "live"
CENT = Decimal("0.01")
QUARTER = Decimal("0.25")
FIXED = {"fixed_fee"}


def _csv(name):
    path = SRC / f"{name}.csv"
    return list(csv.DictReader(open(path, encoding="utf-8"))) if path.exists() else []


def _jsonl(name):
    path = LIVE / f"{name}.jsonl"
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()] if path.exists() else []


def milestone_billed():
    billed = defaultdict(Decimal)
    for l in _csv("project_invoice_lines") + _jsonl("project_invoice_lines"):
        if l.get("milestone_id"):
            billed[l["milestone_id"]] += Decimal(str(l["amount"]))
    return billed


def contract_type(contract_id):
    return next((k["contract_type"] for k in _csv("contracts") if k["contract_id"] == contract_id), None)


def next_milestone(project_id, today, exclude=()):
    """The oldest accepted milestone with something left to bill: (milestone, remaining) or None."""
    billed = milestone_billed()
    for m in sorted(_csv("milestones"), key=lambda m: (m["accepted_date"] or "9999", m["milestone_id"])):
        if m["project_id"] != project_id or not m["accepted_date"] or m["accepted_date"] > str(today) or m["milestone_id"] in exclude:
            continue
        left = Decimal(m["amount"]) - billed[m["milestone_id"]]
        if left > 0:
            return m, left
    return None


def milestone_lines(project_id, today, share=None):
    """Lines for a fixed-fee invoice: the next accepted milestone, all of what is left or `share` of the milestone."""
    hit = next_milestone(project_id, today)
    if not hit:
        return None
    m, left = hit
    amount = left if share is None else min(left, (Decimal(m["amount"]) * Decimal(str(share))).quantize(CENT))
    part = "" if amount == Decimal(m["amount"]) else f" ({(amount / Decimal(m['amount'])):.0%} of {Decimal(m['amount']):,.2f})"
    return [{"line_no": 1, "line_type": "milestone", "milestone_id": m["milestone_id"], "amount": str(amount.quantize(CENT)),
             "description": f"{m['milestone_name']}{part}, accepted {m['accepted_date']}"}], amount, m["milestone_name"]


def tm_lines(contract_id, amount):
    """Lines for a T&M invoice of `amount`: quarter-hours at contract rates across the two most senior categories,
    the remainder as other direct costs."""
    rates = sorted(((r["labor_category"], Decimal(r["bill_rate"])) for r in _csv("contract_rates") if r["contract_id"] == contract_id),
                   key=lambda x: -x[1])[:2]
    amount = Decimal(str(amount)).quantize(CENT)
    if not rates:
        return [{"line_no": 1, "line_type": "labor", "amount": str(amount)}]
    lines, left = [], amount
    for i, (cat, rate) in enumerate(rates):
        budget = left * (Decimal("0.6") if i == 0 and len(rates) > 1 else 1)
        hours = (budget / rate / QUARTER).to_integral_value(ROUND_DOWN) * QUARTER
        if hours <= 0:
            continue
        cost = (hours * rate).quantize(CENT)
        lines.append({"line_no": len(lines) + 1, "line_type": "labor", "labor_category": cat, "hours": str(hours),
                      "rate": str(rate), "amount": str(cost)})
        left -= cost
    if left > 0:
        lines.append({"line_no": len(lines) + 1, "line_type": "odc", "amount": str(left.quantize(CENT)),
                      "description": "Other direct costs (travel, tools)"})
    return lines
