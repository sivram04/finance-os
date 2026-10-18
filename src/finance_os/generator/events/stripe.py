"""Stripe API objects for usage billing (raw_stripe), built from the ledger's billing records.

Shapes follow Stripe's API: ids with type prefixes, amounts in integer cents, Unix timestamps, invoices with a
nested `lines` list, charges (succeeded, or failed attempts on invoices that end uncollectible), refunds,
balance transactions with `fee_details`, and daily payouts (in_transit at the end of the data). Each object is
written as one JSON line, the way an ELT tool lands Stripe data: {"id": ..., "data": {...}}.

Because they are built from the same billing records the ledger posts, Stripe ↔ GL reconciles exactly:
invoices ↔ usage revenue, and balance-transaction net ↔ the cash the ledger booked for usage billing. What
does *not* match is the ERP's own mistake (the misapplied payment): Stripe pays the invoice the customer paid.
"""
import calendar
import hashlib
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal

TERMS_DAYS = {"self_serve": 0, "mid_market": 30, "enterprise": 45}


def _id(prefix, key):
    return f"{prefix}_{hashlib.sha256(key.encode()).hexdigest()[:24]}"


def _ts(d, seconds=0):
    """Unix timestamp for a date (UTC midnight) plus seconds."""
    return calendar.timegm(datetime.combine(d, time()).timetuple()) + seconds


def _cents(x):
    return int((Decimal(x) * 100).to_integral_value())


def _secs(key, span=86400):
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % span


def build_stripe(cfg, customers, billing):
    end = cfg["window"]["end"]
    delay = cfg["stripe"]["payout_delay_days"]
    attempts = cfg["stripe"]["failed_attempts"]
    out = defaultdict(list)
    cus = {c["customer_id"]: _id("cus", c["customer_id"]) for c in customers}
    delinquent = {b["customer_id"] for b in billing if b["status"] == "uncollectible"}

    for c in customers:
        out["customers"].append({
            "id": cus[c["customer_id"]], "object": "customer", "created": _ts(c["signup_date"], _secs(c["customer_id"])),
            "email": f"billing@{c['customer_id'].lower()}.example.com", "name": c["customer_name"], "currency": "usd",
            "delinquent": c["customer_id"] in delinquent, "address": {"country": "US"},
            "metadata": {"erp_customer_id": c["customer_id"], "segment": c["segment"]}})

    txns = []  # (available_date, txn) for payouts
    for n, b in enumerate(sorted(billing, key=lambda r: (r["invoice_date"], r["customer_id"])), 1):
        ref, cid, seg = b["invoice_ref"], b["customer_id"], b["segment"]
        inv_id = _id("in", ref)
        amount = _cents(b["amount"])
        created = _ts(b["invoice_date"], 3600 + _secs(ref, 3600))
        month_start, next_month = b["month"], b["invoice_date"] + timedelta(days=1)
        auto = seg == "self_serve"
        lines = [{
            "id": _id("il", f"{ref}|{p}"), "object": "line_item", "amount": _cents(a), "currency": "usd",
            "description": f"{p} audio transcription", "quantity": int(round(h)),
            "period": {"start": _ts(month_start), "end": _ts(next_month)},
            "price": {"id": _id("price", p), "object": "price", "product": _id("prod", p), "currency": "usd",
                      "unit_amount_decimal": str((unit * 100).quantize(Decimal("0.000001"))),
                      "billing_scheme": "per_unit", "recurring": {"interval": "month", "usage_type": "metered"}},
            "metadata": {"product_id": p, "audio_hours": str(h)}} for p, h, unit, a in b["lines"]]
        paid = b["status"] == "paid"
        charge_id = _id("ch", ref) if paid else None
        paid_at = _ts(b["paid_date"], _secs(ref + "|paid")) if paid else None
        out["invoices"].append({
            "id": inv_id, "object": "invoice", "number": f"ECHO-{n:06d}", "customer": cus[cid], "currency": "usd",
            "created": created, "period_start": _ts(month_start), "period_end": _ts(next_month),
            "collection_method": "charge_automatically" if auto else "send_invoice",
            "due_date": None if auto else created + TERMS_DAYS[seg] * 86400,
            "status": b["status"], "paid": paid, "attempted": paid or b["status"] == "uncollectible",
            "attempt_count": 1 if paid else (attempts if b["status"] == "uncollectible" else 0),
            "subtotal": amount, "total": amount, "amount_due": amount, "amount_paid": amount if paid else 0,
            "amount_remaining": 0 if paid else amount, "charge": charge_id,
            "status_transitions": {"finalized_at": created, "paid_at": paid_at,
                                   "marked_uncollectible_at": created + 21 * 86400 if b["status"] == "uncollectible" else None},
            "lines": {"object": "list", "has_more": False, "total_count": len(lines), "data": lines},
            "metadata": {"erp_invoice_ref": ref}})

        if b["status"] == "uncollectible":
            for k in range(attempts):
                out["charges"].append({
                    "id": _id("ch", f"{ref}|fail{k}"), "object": "charge", "amount": amount, "amount_captured": 0,
                    "amount_refunded": 0, "currency": "usd", "customer": cus[cid], "invoice": inv_id,
                    "created": created + (1 + 3 * k) * 86400, "paid": False, "captured": False, "status": "failed",
                    "failure_code": "card_declined", "failure_message": "Your card was declined.",
                    "payment_method_details": {"type": "card", "card": {"brand": "visa", "last4": "0341"}},
                    "balance_transaction": None, "refunded": False})
        if not paid:
            continue

        fee = _cents(b["fee"])
        refund = b["refund"]
        txn_id = _id("txn", ref)
        out["charges"].append({
            "id": charge_id, "object": "charge", "amount": amount, "amount_captured": amount,
            "amount_refunded": _cents(refund["amount"]) if refund else 0, "currency": "usd", "customer": cus[cid],
            "invoice": inv_id, "created": paid_at, "paid": True, "captured": True, "status": "succeeded",
            "refunded": bool(refund), "outcome": {"type": "authorized", "network_status": "approved_by_network"},
            "payment_method_details": ({"type": "card", "card": {"brand": "visa", "last4": "4242"}} if auto
                                       else {"type": "us_bank_account", "us_bank_account": {"bank_name": "STRIPE TEST BANK", "last4": "6789"}}),
            "balance_transaction": txn_id})
        available = b["paid_date"] + timedelta(days=delay)
        charge_txn = {
            "id": txn_id, "object": "balance_transaction", "amount": amount, "fee": fee, "net": amount - fee,
            "currency": "usd", "exchange_rate": None, "type": "charge", "reporting_category": "charge",
            "source": charge_id, "created": paid_at, "available_on": _ts(available),
            "status": "available" if available <= end else "pending",
            "fee_details": [{"amount": fee, "currency": "usd", "type": "stripe_fee", "description": "Stripe processing fees"}]}
        out["balance_transactions"].append(charge_txn)
        txns.append((available, charge_txn))
        if refund:
            re_id, rtxn_id = _id("re", ref), _id("txn", ref + "|refund")
            r_amount = _cents(refund["amount"])
            r_created = _ts(refund["date"], _secs(ref + "|refund"))
            out["refunds"].append({
                "id": re_id, "object": "refund", "amount": r_amount, "charge": charge_id, "currency": "usd",
                "created": r_created, "reason": refund["reason"], "status": "succeeded", "balance_transaction": rtxn_id})
            r_available = refund["date"]  # refunds debit the balance immediately
            rtxn = {"id": rtxn_id, "object": "balance_transaction", "amount": -r_amount, "fee": 0, "net": -r_amount,
                    "currency": "usd", "exchange_rate": None, "type": "refund", "reporting_category": "refund",
                    "source": re_id, "created": r_created, "available_on": _ts(r_available), "status": "available",
                    "fee_details": []}
            out["balance_transactions"].append(rtxn)
            txns.append((r_available, rtxn))

    # Daily automatic payouts of the available balance; a negative day carries over.
    by_day = defaultdict(int)
    for day, t in txns:
        if day <= end:
            by_day[day] += t["net"]
    carry = 0
    for day in sorted(by_day):
        balance = carry + by_day[day]
        if balance <= 0:
            carry = balance
            continue
        carry = 0
        po_id = _id("po", day.isoformat())
        arrival = day + timedelta(days=1)
        out["payouts"].append({
            "id": po_id, "object": "payout", "amount": balance, "currency": "usd", "created": _ts(day, 7200),
            "arrival_date": _ts(arrival), "status": "paid" if arrival <= end else "in_transit", "method": "standard",
            "type": "bank_account", "balance_transaction": _id("txn", "payout|" + day.isoformat())})
        out["balance_transactions"].append({
            "id": _id("txn", "payout|" + day.isoformat()), "object": "balance_transaction", "amount": -balance,
            "fee": 0, "net": -balance, "currency": "usd", "exchange_rate": None, "type": "payout",
            "reporting_category": "payout", "source": po_id, "created": _ts(day, 7200), "available_on": _ts(day, 7200),
            "status": "available", "fee_details": []})
    return {f"stripe_{k}": v for k, v in out.items()}
