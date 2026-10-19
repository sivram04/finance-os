"""Legal entities (seeds/entities.csv) and who works for which (seeds/entity_assignment.csv).

Echo Labs, Inc. (US) is the parent: it contracts every customer and owns the IP. The subsidiaries are cost-plus
service providers, the standard structure for a US SaaS company with people abroad: they employ local staff and
charge the parent their cost plus a transfer-pricing markup each month. In the books (history and live alike):
  - each employee's payroll posts to their entity (entity_of: title share, picked by a stable hash of the id)
  - month end, each subsidiary bills the parent: sub Dr 1300 intercompany receivable / Cr 4900 intercompany service
    revenue; parent Dr 6900 intercompany service fees / Cr 2300 intercompany payable; settled in cash the same day
    (parent Dr 2300 / Cr 1000; sub Dr 1000 / Cr 1300)
Consolidation eliminates 1300/2300 and 4900/6900, so group numbers are unchanged; each entity's own books are real.
"""
import hashlib
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from finance_os.generator.seeds import read_seed

PARENT = "US01"
IC_ACCOUNTS = ("1300", "2300", "4900", "6900")
CENT = Decimal("0.01")


def entities():
    return {e["entity_id"]: e for e in read_seed("entities")}


def _assignment():
    out = defaultdict(list)
    for a in read_seed("entity_assignment"):
        out[a["title"]].append((a["entity_id"], Decimal(a["share"])))
    return out


_ASSIGN = None


def entity_of(employee_id, title):
    """The entity an employee is on payroll in: a stable pick by title share (same answer every run)."""
    global _ASSIGN
    if _ASSIGN is None:
        _ASSIGN = _assignment()
    u = Decimal(int(hashlib.md5(employee_id.encode()).hexdigest()[:8], 16)) / Decimal(16 ** 8)
    edge = Decimal(0)
    for entity_id, share in _ASSIGN.get(title, []):
        edge += share
        if u < edge:
            return entity_id
    return PARENT


def intercompany(post, day, costs):
    """Month-end service fees. costs: {(entity_id, department_id): cost of that entity's staff this month}. `post` is
    the ledger's post(entry_date, entry_type, memo, lines, ref) with lines (account, debit, credit, dims)."""
    ents = entities()
    for (ent, dept), cost in sorted(costs.items()):
        if ent == PARENT or cost <= 0:
            continue
        fee = (cost * (1 + Decimal(ents[ent]["markup_pct"]))).quantize(CENT, rounding=ROUND_HALF_UP)
        sub, par = {"entity_id": ent, "department_id": dept}, {"entity_id": PARENT, "department_id": dept}
        ref, name = f"IC-{ent}-{day:%Y%m}-{dept}", ents[ent]["entity_name"]
        post(day, "intercompany_charge", f"{name} services {day:%b %Y} {dept}",
             [("1300", fee, 0, sub), ("4900", 0, fee, sub), ("6900", fee, 0, par), ("2300", 0, fee, par)], ref)
        post(day, "intercompany_settlement", f"Settle {name} services {day:%b %Y} {dept}",
             [("2300", fee, 0, par), ("1000", 0, fee, par), ("1000", fee, 0, sub), ("1300", 0, fee, sub)], ref)
