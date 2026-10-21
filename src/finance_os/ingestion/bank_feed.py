"""Bank statement feed: what the bank shows for each operating account, loaded into raw_bank.

    python -m finance_os.ingestion.bank_feed [--db data/finance_os.duckdb]

The bank is an independent record of every cash movement, so the ledger's cash can be reconciled to it. The
statement is built from the cash the company actually moved, the way the bank sees it:

  - timing: deposits clear 0-2 business days after they are booked, card and ACH payments 0-1, and vendor
    cheques 2-9, so cheques written near month end are still outstanding on the statement;
  - Stripe payouts arrive net of processing fees (one deposit for a payment and its fee);
  - items only the bank knows about, from the feed's start: a monthly service fee on every account and interest
    on the US operating account, which the ledger has not recorded until someone books them;
  - one keying error a month on the US account: the payment cleared at its true amount, but the ledger has two
    digits transposed.

Deterministic: the same ledger gives the same statement on every run (full replace, safe to rerun).
"""
import argparse
import hashlib
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import duckdb

from finance_os.paths import ROOT

FEED_FROM = date(2026, 7, 1)  # the bank feed was connected in July 2026; earlier months were reconciled on paper
INTEREST_APY = Decimal("0.01")  # US operating account
ACCOUNTS = [  # bank_account_id, entity, bank, monthly service fee
    ("CHK-US01-4471", "US01", "First Republic Operating", Decimal("185.00")),
    ("CHK-UK01-2208", "UK01", "Barclays Business", Decimal("95.00")),
    ("CHK-IN01-9034", "IN01", "HDFC Current Account", Decimal("40.00")),
]
LAG = {  # business days from booking to clearing (min, max)
    "collection": (1, 2), "payment_fee": (1, 2), "refund": (1, 1), "project_collection": (0, 1),
    "payroll": (0, 0), "payroll_remittance": (0, 0), "opex": (0, 1), "capex": (0, 1), "one_off": (0, 1),
    "funding": (0, 0), "intercompany_settlement": (0, 1), "project_odc": (1, 3),
    "vendor_payment": (2, 9), "subcontractor_payment": (2, 9),
}
CHEQUES = {"vendor_payment", "subcontractor_payment"}

GL_CASH = """
select coalesce(s.externalid, 'US01') as entity_id, cast(t.trandate as date) as entry_date,
       coalesce(t.custbody_echo_source_ref, t.tranid) as reference, min(t.custbody_echo_entry_type) as entry_type,
       string_agg(distinct t.memo, '; ') as memo, sum(l.debit - l.credit) as amount
from raw_netsuite.transactionline l
join raw_netsuite.transaction t on t.id = l.transaction
join raw_netsuite.account a on a.id = l.account
left join raw_netsuite.subsidiary s on s.id = l.subsidiary
where l.posting = 'T' and t.posting = 'T' and a.acctnumber = '1000'
group by 1, 2, 3
having sum(l.debit - l.credit) <> 0
order by 2, 1, 3
"""


def _h(*parts) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12], 16)


def _business_days(d: date, n: int) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def _last_business_day(year: int, month: int) -> date:
    d = date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _transposed(amount: Decimal) -> Decimal:
    """Swap the hundreds and tens digits of the dollar amount (4,521.30 -> 4,512.30); keep it if they match."""
    sign = -1 if amount < 0 else 1
    cents = int(abs(amount) * 100)
    dollars, c = divmod(cents, 100)
    s = list(f"{dollars:04d}")
    s[-3], s[-2] = s[-2], s[-3]
    return Decimal(sign * (int("".join(s)) * 100 + c)) / 100


def _description(entry_type, amount, reference, memo, cheque_no):
    if entry_type in ("collection", "payment_fee", "refund"):
        return f"ACH CREDIT STRIPE PAYOUT {reference}" if amount > 0 else f"ACH DEBIT STRIPE {reference}"
    if entry_type in CHEQUES:
        return f"CHECK #{cheque_no} PAID"
    if entry_type in ("payroll", "payroll_remittance"):
        return f"ACH DEBIT PAYROLL {memo[:40].upper()}"
    if entry_type in ("project_collection", "funding"):
        return f"WIRE IN {memo[:40].upper()}"
    if entry_type == "intercompany_settlement":
        return f"BOOK TRANSFER {'IN' if amount > 0 else 'OUT'} INTERCOMPANY"
    return f"{'ACH CREDIT' if amount > 0 else 'ACH DEBIT'} {memo[:40].upper()}"


def build(con) -> list[tuple]:
    items = con.execute(GL_CASH).fetchall()
    if not items:
        return []
    as_of = max(r[1] for r in items)  # the statement runs through the last day anything was booked
    accounts = {e: (acct, fee) for acct, e, _, fee in ACCOUNTS}

    # one keying error a month on the US account, from the feed's start: the largest-hash ACH/cheque payment
    wrong = {}
    for ent, d, ref, typ, memo, amt in items:
        if ent == "US01" and d >= FEED_FROM and typ in ("opex", "vendor_payment") and abs(amt) >= 1000:
            key = (d.year, d.month)
            h = _h("transpose", ref, d)
            if key not in wrong or h > wrong[key][0]:
                wrong[key] = (h, ref, d)
    wrong_refs = {(ref, d) for _, ref, d in wrong.values()}

    lines, cheque = [], 10230
    for ent, d, ref, typ, memo, amt in items:
        acct = accounts.get(ent, accounts["US01"])[0]
        lo, hi = LAG.get(typ, (0, 1))
        posted = _business_days(d, lo + _h("lag", ref, d, ent) % (hi - lo + 1))
        if posted > as_of:
            continue  # not cleared yet: the ledger shows it, the bank doesn't
        bank_amt = Decimal(amt)
        if (ref, d) in wrong_refs:
            t = _transposed(bank_amt)
            # the bank is right; the ledger has the digits swapped, so the bank amount is the transposed ledger amount
            bank_amt = t if t != bank_amt else bank_amt + Decimal("9.00")
        if typ in CHEQUES:
            cheque += 1
        lines.append([acct, ent, posted, bank_amt, _description(typ, amt, ref, memo or "", cheque), ref, typ or "other"])

    # bank-only items from the feed's start: service fee every month, interest on the US account
    month = date(FEED_FROM.year, FEED_FROM.month, 1)
    while True:
        eom = _last_business_day(month.year, month.month)
        if eom > as_of:
            break
        for acct, ent, _, fee in ACCOUNTS:
            lines.append([acct, ent, eom, -fee, "MONTHLY ACCOUNT SERVICE FEE", f"FEE-{acct}-{month:%Y%m}", "bank_fee"])
        us = accounts["US01"][0]
        balance = sum(l[3] for l in lines if l[0] == us and l[2] <= eom)
        interest = (balance * INTEREST_APY / 12).quantize(Decimal("0.01"))
        if interest > 0:
            lines.append([us, "US01", eom, interest, "INTEREST PAID", f"INT-{us}-{month:%Y%m}", "interest"])
        month = date(month.year + month.month // 12, month.month % 12 + 1, 1)

    lines.sort(key=lambda l: (l[0], l[2], -l[3], l[5]))
    out, seq = [], {}
    for acct, ent, posted, amt, desc, ref, typ in lines:
        seq[acct] = seq.get(acct, 0) + 1
        out.append((f"{acct}-{seq[acct]:06d}", acct, ent, posted, amt, desc, ref, typ))
    return out


def load(db: Path) -> int:
    con = duckdb.connect(str(db))
    try:
        rows = build(con)
        con.execute("create schema if not exists raw_bank")
        con.execute("""create or replace table raw_bank.accounts (bank_account_id varchar, entity_id varchar,
                       bank_name varchar, currency varchar, monthly_fee decimal(18,2))""")
        con.executemany("insert into raw_bank.accounts values (?, ?, ?, 'USD', ?)",
                        [(a, e, b, f) for a, e, b, f in ACCOUNTS])
        con.execute("""create or replace table raw_bank.statement_lines (statement_line_id varchar, bank_account_id varchar,
                       entity_id varchar, posted_date date, amount decimal(18,2), description varchar,
                       bank_reference varchar, transaction_code varchar)""")
        con.executemany("insert into raw_bank.statement_lines values (?, ?, ?, ?, ?, ?, ?, ?)", rows)
        return len(rows)
    finally:
        con.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=str(ROOT / "data" / "finance_os.duckdb"))
    a = p.parse_args()
    print(f"bank feed: {load(Path(a.db))} statement lines")


if __name__ == "__main__":
    main()
