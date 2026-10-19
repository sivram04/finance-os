"""The general ledger as a NetSuite data export lands (raw_netsuite): transaction, transactionline, account,
accountingperiod, department, entity, with NetSuite internal ids and transaction types.

The generator (and the live loader, for each simulated day) produce the ledger as journal entries; this
module renders them the way NetSuite's SuiteAnalytics / data export would give them to the warehouse:
  - every entry is a transaction of a NetSuite type (CustInvc, CustPymt, CustRfnd, VendBill, VendPymt, Check,
    Deposit, Journal) with a document number (tranid), a posting period and the main entity;
  - lines reference internal ids for account, department and entity;
  - what NetSuite has no native field for travels in custom body fields, as an implementation would set them up:
    custbody_echo_entry_type (our posting rule) and custbody_echo_source_ref (the source document reference).
The warehouse's ERP staging models read these tables and map ids back to account numbers and codes.
"""
import calendar
from datetime import date, datetime, time, timedelta

TYPE = {"revenue": "CustInvc", "project_invoice": "CustInvc", "collection": "CustPymt", "project_collection": "CustPymt",
        "refund": "CustRfnd", "vendor_bill": "VendBill", "subcontractor_bill": "VendBill",
        "vendor_payment": "VendPymt", "subcontractor_payment": "VendPymt", "payroll": "Journal",
        "payment_fee": "Journal", "payroll_remittance": "Check", "opex": "Check", "one_off": "Check",
        "project_odc": "Check", "funding": "Deposit", "capex": "Check", "depreciation": "Journal"}
ACCT_TYPE = {"1000": "Bank", "1200": "AcctRec", "1500": "FixedAsset", "1510": "FixedAsset", "2000": "AcctPay", "3000": "Equity"}
BY_CLASS = {"asset": "OthCurrAsset", "liability": "OthCurrLiab", "equity": "Equity", "revenue": "Income",
            "cogs": "COGS", "opex": "Expense"}
LIVE_TXN_OFFSET = 1_000_000   # live entries (LJE000001…) get internal ids above the history's


def txn_id(entry_id):
    """Internal transaction id from our entry id: JE000123 -> 123, LJE000045 -> 1000045."""
    n = int("".join(ch for ch in entry_id if ch.isdigit()))
    return LIVE_TXN_OFFSET + n if entry_id.startswith("LJE") else n


def period_id(d):
    return (d.year - 2024) * 12 + d.month   # Jan 2024 = 13; stable for any date


def reference_tables(gl_accounts, departments, customers, vendors, first, last):
    """account, department, entity, accountingperiod rows (internal ids are stable: sorted codes)."""
    accounts = [{"id": 100 + i, "acctnumber": a["account_id"], "fullname": f"{a['account_id']} {a['account_name']}",
                 "accttype": ACCT_TYPE.get(a["account_id"], BY_CLASS[a["account_type"]]), "isinactive": "F"}
                for i, a in enumerate(sorted(gl_accounts, key=lambda a: a["account_id"]))]
    depts = [{"id": 10 + i, "name": d["department_name"], "externalid": d["department_id"], "isinactive": "F"}
             for i, d in enumerate(sorted(departments, key=lambda d: d["department_id"]))]
    entities = entity_rows([("customer", c) for c in sorted(customers)] + [("vendor", v) for v in sorted(vendors)])
    periods, d = [], first.replace(day=1)
    while d <= last:
        end = d.replace(day=calendar.monthrange(d.year, d.month)[1])
        periods.append({"id": period_id(d), "periodname": d.strftime("%b %Y"), "startdate": d, "enddate": end,
                        "isquarter": "F", "isyear": "F", "isadjust": "F"})
        d = end + timedelta(days=1)
    return {"netsuite_account": accounts, "netsuite_department": depts, "netsuite_entity": entities,
            "netsuite_accountingperiod": periods}


def entity_rows(typed_codes, start_id=1000):
    return [{"id": start_id + i, "entityid": code, "type": kind, "isinactive": "F"}
            for i, (kind, code) in enumerate(typed_codes)]


def transactions(entries, lines, account_id, dept_id, entity_id):
    """transaction + transactionline rows. *_id map our codes to internal ids (dicts)."""
    by_entry = {}
    for l in lines:
        by_entry.setdefault(l["entry_id"], []).append(l)
    txns, tlines = [], []
    for e in entries:
        tid = txn_id(e["entry_id"])
        d = e["entry_date"] if isinstance(e["entry_date"], date) else date.fromisoformat(str(e["entry_date"]))
        ls = by_entry.get(e["entry_id"], [])
        main = next((l.get("customer_id") or l.get("vendor_id") for l in ls if l.get("customer_id") or l.get("vendor_id")), None)
        created = datetime.combine(d, time(9, 0)) + timedelta(days=1)
        txns.append({"id": tid, "tranid": e["entry_id"], "type": TYPE.get(e["entry_type"], "Journal"), "trandate": d,
                     "postingperiod": period_id(d), "memo": e["memo"], "entity": entity_id.get(main),
                     "currency": 1, "exchangerate": "1.0", "posting": "T", "status": "posted",
                     "custbody_echo_entry_type": e["entry_type"], "custbody_echo_source_ref": e.get("source_ref"),
                     "createddate": created, "lastmodifieddate": created})
        for l in ls:
            debit, credit = str(l["debit"]), str(l["credit"])
            ent = l.get("customer_id") or l.get("vendor_id")
            tlines.append({"transaction": tid, "id": int(l["line_no"]), "account": account_id[str(l["account_id"])],
                           "department": dept_id.get(l.get("department_id")), "entity": entity_id.get(ent),
                           "subsidiary": 1, "location": 1, "memo": e["memo"], "debit": debit, "credit": credit,
                           "posting": "T"})
    return txns, tlines


def build_netsuite(gl_accounts, departments, customers, vendors, entries, lines, first, last):
    ref = reference_tables(gl_accounts, departments, customers, vendors, first, last)
    account_id = {a["acctnumber"]: a["id"] for a in ref["netsuite_account"]}
    dept_id = {d["externalid"]: d["id"] for d in ref["netsuite_department"]}
    entity_id = {e["entityid"]: e["id"] for e in ref["netsuite_entity"]}
    txns, tlines = transactions(entries, lines, account_id, dept_id, entity_id)
    return {**ref, "netsuite_transaction": txns, "netsuite_transactionline": tlines}
