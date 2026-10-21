"""Bookkeeping: manual journal entries, and the bank reconciliation items they clear (design §9.5).

A bookkeeper keys an entry (or drafts one from a bank reconciliation item); it is validated, then waits on an
approval card like every other change: approved = posted, rejected = never posted, undone = reversed. Entries live
in the app state next to the other decisions, so a warehouse rebuild never loses them; posted entries adjust the
trial balance here and are exported in the ERP's journal import layout.

Controls on every entry: at least two lines, each a debit or a credit (not both), cents only, known accounts and
entities, debits equal credits for each legal entity, a memo, and an open period (the month being closed or later,
not after the current month). One bank item can be booked by one entry.
"""
import calendar
import csv
import io
import json
from datetime import date
from decimal import Decimal, InvalidOperation

from finance_os.app import tools

KIND = "journal_entry"
STATUS = {"pending": "awaiting approval", "approved": "posted", "rejected": "rejected", "reverted": "reversed"}
CENT = Decimal("0.01")


def _d(v) -> Decimal:
    try:
        return Decimal(str(v if v not in (None, "") else 0))
    except InvalidOperation:
        raise ValueError(f"not an amount: {v!r}")


def _payload(a):
    return json.loads(a["payload"]) if isinstance(a["payload"], str) else a["payload"]


class Bookkeeping:
    def __init__(self, state, wh):
        self.state, self.wh = state, wh

    # reference data
    def chart(self):
        return tools.get_chart_of_accounts(self.wh)

    def periods(self):
        """Open periods: from the month being closed (the last month with posted usage invoices) through the current
        month. Earlier months are locked."""
        q = self.wh.query("""select max(case when entry_type = 'revenue' then entry_month end) as closing,
                                    max(entry_month) as current from staging.stg_erp__journal_entries""")[0]
        return str(q["closing"])[:7], str(q["current"])[:7]

    # entries
    def validate(self, entry):
        errors, chart = [], self.chart()
        accounts = {a["account_id"]: a for a in chart["rows"]}
        entities = set(chart["entities"])
        try:
            d = date.fromisoformat(str(entry.get("entry_date", ""))[:10])
        except ValueError:
            return ["Entry date must be YYYY-MM-DD."]
        first, last = self.periods()
        if f"{d:%Y-%m}" < first:
            errors.append(f"{d:%Y-%m} is locked: the books are closed through {self._prev(first)}. Date it {first} or later.")
        if f"{d:%Y-%m}" > last:
            errors.append(f"{d:%Y-%m} is a future period; the latest open period is {last}.")
        if not str(entry.get("memo") or "").strip():
            errors.append("Add a memo saying what the entry is for.")
        lines = entry.get("lines") or []
        if len(lines) < 2:
            errors.append("An entry needs at least two lines.")
        per_entity = {}
        for i, l in enumerate(lines, 1):
            try:
                dr, cr = _d(l.get("debit")), _d(l.get("credit"))
            except ValueError as e:
                errors.append(f"Line {i}: {e}")
                continue
            if l.get("account_id") not in accounts:
                errors.append(f"Line {i}: unknown account {l.get('account_id')!r}.")
            if l.get("entity_id") not in entities:
                errors.append(f"Line {i}: unknown entity {l.get('entity_id')!r}.")
            if dr < 0 or cr < 0:
                errors.append(f"Line {i}: amounts must be positive; use the other column instead of a minus sign.")
            if (dr > 0) == (cr > 0):
                errors.append(f"Line {i}: enter a debit or a credit, not {'both' if dr > 0 else 'neither'}.")
            if dr != dr.quantize(CENT) or cr != cr.quantize(CENT):
                errors.append(f"Line {i}: amounts are in cents (two decimals).")
            per_entity[l.get("entity_id")] = per_entity.get(l.get("entity_id"), Decimal(0)) + dr - cr
        for ent, diff in per_entity.items():
            if diff != 0:
                errors.append(f"Debits and credits differ by ${abs(diff):,.2f} for {ent}; each entity must balance.")
        for item in entry.get("source_items") or []:
            other = self._booked().get(item)
            if other:
                errors.append(f"Bank item {item} is already booked by {other['entry_id']} ({other['status']}).")
        return errors

    @staticmethod
    def _prev(m):
        y, mo = int(m[:4]), int(m[5:7])
        return f"{y - (mo == 1)}-{(mo - 2) % 12 + 1:02d}"

    def create(self, entry, cid=None, prepared_by="you"):
        errors = self.validate(entry)
        if errors:
            return {"errors": errors}
        lines = [{"account_id": l["account_id"], "entity_id": l["entity_id"], "debit": f"{_d(l.get('debit')):.2f}",
                  "credit": f"{_d(l.get('credit')):.2f}", "memo": (l.get("memo") or "").strip()} for l in entry["lines"]]
        total = sum(_d(l["debit"]) for l in lines)
        d = str(entry["entry_date"])[:10]
        n = sum(1 for a in self.state.actions() if a["kind"] == KIND) + 1
        eid = f"MJE-{d[:4]}{d[5:7]}-{n:04d}"
        payload = {"entry_id": eid, "entry_date": d, "memo": entry["memo"].strip(), "lines": lines, "total": f"{total:.2f}",
                   "source_items": entry.get("source_items") or [], "prepared_by": prepared_by}
        names = {a["account_id"]: a["account_name"] for a in self.chart()["rows"]}
        legs = "; ".join(f"{'Dr' if _d(l['debit']) else 'Cr'} {l['account_id']} {names.get(l['account_id'], '')} "
                         f"${max(_d(l['debit']), _d(l['credit'])):,.2f} ({l['entity_id']})" for l in lines)
        preview = f"Post journal entry {eid} dated {d} for ${total:,.2f}: {payload['memo']}. {legs}"
        aid = self.state.propose(cid, KIND, eid, payload, preview)
        return {"proposed_action_id": aid, "entry_id": eid, "status": "pending: approval card created; nothing posted yet",
                "preview": preview}

    def entries(self):
        out = []
        for a in self.state.actions():
            if a["kind"] != KIND:
                continue
            p = _payload(a)
            out.append({**p, "total": float(p["total"]), "action_id": a["id"], "status": STATUS.get(a["status"], a["status"]),
                        "created_at": str(a["created_at"])[:16], "decided_at": str(a["decided_at"] or "")[:16] or None})
        return out[::-1]

    def _booked(self):
        """bank item -> the live entry (awaiting approval or posted) that books it"""
        return {item: e for e in self.entries() if e["status"] in ("awaiting approval", "posted") for item in e["source_items"]}

    def posted_lines(self):
        return [{**l, "entry_id": e["entry_id"], "entry_date": e["entry_date"]}
                for e in self.entries() if e["status"] == "posted" for l in e["lines"]]

    # views that combine the ledger with posted manual entries
    def trial_balance(self, month=None):
        tb = tools.get_trial_balance(self.wh, month)
        m = tb["month"]
        year = m[:4]
        rows = {r["account_id"]: {**r, "ledger_balance": float(r["balance"] or 0), "manual": 0.0} for r in tb["rows"]}
        chart = {a["account_id"]: a for a in self.chart()["rows"]}
        for l in self.posted_lines():
            if l["entry_date"][:7] > m:
                continue
            a = chart.get(l["account_id"], {})
            if a.get("statement") == "income_statement" and l["entry_date"][:4] != year:
                acct = "3900"  # a prior year's result sits in retained earnings
            else:
                acct = l["account_id"]
            r = rows.setdefault(acct, {"account_id": acct, "account_name": a.get("account_name", acct),
                                       "account_type": a.get("account_type"), "statement": a.get("statement"),
                                       "ledger_balance": 0.0, "manual": 0.0, "month_activity": 0})
            r["manual"] += float(_d(l["debit"]) - _d(l["credit"]))
        out = []
        for r in sorted(rows.values(), key=lambda r: r["account_id"]):
            b = round(r["ledger_balance"] + r["manual"], 2)
            out.append({"account_id": r["account_id"], "account_name": r["account_name"], "statement": r.get("statement"),
                        "ledger_balance": round(r["ledger_balance"], 2), "manual_entries": round(r["manual"], 2),
                        "debit": b if b > 0 else 0.0, "credit": -b if b < 0 else 0.0})
        totals = {"debit": round(sum(r["debit"] for r in out), 2), "credit": round(sum(r["credit"] for r in out), 2)}
        return {"source": "posted ledger + posted manual entries", "month": m, "row_count": len(out), "rows": out,
                "totals": totals, "balanced": abs(totals["debit"] - totals["credit"]) < 0.005}

    def bank_reconciliation(self, month=None):
        """The bank reconciliation with each book-side item's status (to book, awaiting approval, booked) and a
        suggested entry for it."""
        token = tools.FULL_ROWS.set(True)
        try:
            rec = tools.get_bank_reconciliation(self.wh, month)
        finally:
            tools.FULL_ROWS.reset(token)
        if not rec.get("rows"):
            return rec
        booked = self._booked()
        first, _ = self.periods()
        offsets = self._offsets([i["entry_id"] for i in rec["items"] if i["item_type"] == "ledger_error"])
        remaining = {}
        for i in rec["items"]:
            if not i["needs_journal_entry"]:
                continue
            key = i["statement_line_id"]
            e = booked.get(key)
            i["booking"] = {"entry_id": e["entry_id"], "status": e["status"]} if e else None
            i["suggested_entry"] = None if e else self.suggest(i, first, offsets)
            if not e or e["status"] != "posted":
                remaining[i["entity_id"]] = remaining.get(i["entity_id"], 0.0) + float(i["amount"])
        for r in rec["rows"]:
            left = round(remaining.get(r["entity_id"], 0.0), 2)
            r["still_to_book"] = left
            r["book_balance_after_entries"] = round(float(r["adjusted_book_balance"]) - left, 2)
        return rec

    def _offsets(self, entry_ids):
        if not entry_ids:
            return {}
        marks = ", ".join("?" for _ in entry_ids)
        rows = self.wh.query(f"""select entry_id, min(account_id) as account_id from staging.stg_erp__journal_lines
                                 where entry_id in ({marks}) and account_id <> '1000' group by 1""", entry_ids)
        return {r["entry_id"]: r["account_id"] for r in rows}

    @staticmethod
    def suggest(item, first_open, offsets):
        """The entry that books a bank item, dated in an open period (an item from a locked month is booked at the
        end of the first open month)."""
        amt, ent, d = Decimal(str(item["amount"])), item["entity_id"], str(item["item_date"])[:10]
        if d[:7] < first_open:
            y, m = int(first_open[:4]), int(first_open[5:7])
            d = f"{first_open}-{calendar.monthrange(y, m)[1]:02d}"
        a = f"{abs(amt):.2f}"
        cash_dr = amt > 0
        if item["item_type"] == "bank_fee":
            other, memo = "6700", f"Bank service fee {item['item_date']} ({item['reference']})"
        elif item["item_type"] == "interest":
            other, memo = "7000", f"Interest earned {item['item_date']} ({item['reference']})"
        elif item["item_type"] == "ledger_error":
            other = offsets.get(item["entry_id"], "")
            memo = f"Correct {item['entry_id']} to the cleared amount ({item['reference']}): bank {'+' if amt > 0 else '-'}${abs(amt):,.2f}"
        else:
            other, memo = "", f"Bank item {item['reference']}: {item['description']}"
        lines = [{"account_id": "1000", "entity_id": ent, "debit": a if cash_dr else "", "credit": "" if cash_dr else a, "memo": ""},
                 {"account_id": other, "entity_id": ent, "debit": "" if cash_dr else a, "credit": a if cash_dr else "", "memo": ""}]
        return {"entry_date": d, "memo": memo, "lines": lines, "source_items": [item["statement_line_id"]]}

    def export_csv(self):
        """Posted entries in the ERP's journal import layout (one row per line)."""
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["external_id", "tran_date", "subsidiary", "account", "debit", "credit", "memo", "line_memo", "approved_at"])
        for e in self.entries():
            if e["status"] != "posted":
                continue
            for l in e["lines"]:
                w.writerow([e["entry_id"], e["entry_date"], l["entity_id"], l["account_id"], l["debit"] if _d(l["debit"]) else "",
                            l["credit"] if _d(l["credit"]) else "", e["memo"], l.get("memo", ""), e["decided_at"]])
        return buf.getvalue()
