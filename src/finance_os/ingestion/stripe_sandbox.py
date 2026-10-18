"""Stripe sandbox integration: push Echo Labs billing into a Stripe test account, then pull it back the way an
ELT tool does (paginated list API → one JSON line per object → raw_stripe).

    python -m finance_os.ingestion.stripe_sandbox seed --customers 10 --months 2
    python -m finance_os.ingestion.stripe_sandbox pull --out data/stripe_sandbox
    python -m finance_os.ingestion.synthetic_loader ...   # load_stripe reads <out>/stripe/*.jsonl unchanged

Needs STRIPE_SECRET_KEY=sk_test_... in .env. Live keys are refused: this only ever talks to a sandbox.

Seed replays a slice of the generator's own Stripe invoices through the real API: customer (with a test card),
one invoice item per product line, the invoice, then the outcome (paid with the card, marked uncollectible, or
left open) and any refund. ERP ids ride along in `metadata`, so the dbt staging models read sandbox data exactly
like the synthetic files. What differs: Stripe stamps real "now" timestamps (the API cannot backdate), and fees
and payouts are Stripe's own, so the Stripe ↔ GL recons are meant for the synthetic data, not the sandbox.
Reruns are safe: customers are found by metadata search and invoices by their ERP ref before anything is created.
"""
import argparse
import json
import os
import time
from pathlib import Path

import httpx

from finance_os.generator.__main__ import generate
from finance_os.ingestion.ap_intake.__main__ import load_dotenv
from finance_os.ingestion.synthetic_loader import STRIPE_OBJECTS
from finance_os.paths import ROOT

API = "https://api.stripe.com/v1"
STRIPE_VERSION = "2024-06-20"


def client():
    load_dotenv(ROOT / ".env")
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key:
        raise SystemExit("STRIPE_SECRET_KEY is not set (put your sandbox key, sk_test_..., in .env)")
    if not key.startswith(("sk_test_", "rk_test_")):
        raise SystemExit("Refusing a non-test Stripe key: this integration only runs against a sandbox")
    # Pin the API version so object shapes (e.g. invoice.charge) don't change under the dbt models.
    return httpx.Client(base_url=API, auth=(key, ""), timeout=30, headers={"Stripe-Version": STRIPE_VERSION})


def form(params, prefix=""):
    """Nested dict → Stripe's form encoding: metadata[erp_id]=..., lines[0][x]=..."""
    out = {}
    for k, v in params.items():
        key = f"{prefix}[{k}]" if prefix else k
        if isinstance(v, dict):
            out.update(form(v, key))
        elif v is not None:
            out[key] = str(v).lower() if isinstance(v, bool) else str(v)
    return out


def call(http, method, path, params=None, idem=None):
    """One API call with retry on rate limits (sandbox allows ~25 requests/s)."""
    headers = {"Idempotency-Key": idem} if idem else {}
    for attempt in range(5):
        r = http.request(method, path, data=form(params or {}) if method == "POST" else None,
                         params=form(params or {}) if method == "GET" else None, headers=headers)
        if r.status_code != 429:
            break
        time.sleep(2 ** attempt)
    if r.status_code >= 400:
        raise RuntimeError(f"{method} {path}: {r.status_code} {r.json().get('error', {}).get('message')}")
    return r.json()


def search_one(http, resource, query):
    hits = call(http, "GET", f"/{resource}/search", {"query": query})["data"]
    return hits[0] if hits else None


def seed(n_customers=10, months=2):
    """Replay the generator's last `months` of invoices for the first `n_customers` billed customers."""
    tables = generate()
    invoices = tables["stripe_invoices"]
    erp_of = {c["id"]: c for c in tables["stripe_customers"]}
    refunds = {r["charge"]: r for r in tables["stripe_refunds"]}
    last_months = sorted({i["period_start"] for i in invoices})[-months:]
    picked = []
    for cid in dict.fromkeys(i["customer"] for i in invoices):
        if len(picked) == n_customers:
            break
        picked.append(cid)
    todo = [i for i in invoices if i["customer"] in picked and i["period_start"] in last_months]

    with client() as http:
        made = {}
        for cid in picked:
            c = erp_of[cid]
            erp_id = c["metadata"]["erp_customer_id"]
            found = search_one(http, "customers", f"metadata['erp_customer_id']:'{erp_id}'")
            if not found:
                found = call(http, "POST", "/customers", {"name": c["name"], "email": c["email"],
                                                         "metadata": c["metadata"]}, idem=f"cus-{erp_id}")
                pm = call(http, "POST", "/payment_methods/pm_card_visa/attach", {"customer": found["id"]})
                call(http, "POST", f"/customers/{found['id']}",
                     {"invoice_settings": {"default_payment_method": pm["id"]}})
            made[cid] = found["id"]
        print(f"customers: {len(made)}")

        counts = {"paid": 0, "open": 0, "uncollectible": 0, "refunded": 0, "skipped": 0}
        for inv in todo:
            ref = inv["metadata"]["erp_invoice_ref"]
            if search_one(http, "invoices", f"metadata['erp_invoice_ref']:'{ref}'"):
                counts["skipped"] += 1
                continue
            cus = made[inv["customer"]]
            auto = inv["collection_method"] == "charge_automatically"
            draft = call(http, "POST", "/invoices", {
                "customer": cus, "collection_method": inv["collection_method"],
                "days_until_due": None if auto else max(1, (inv["due_date"] - inv["created"]) // 86400),
                "auto_advance": False, "pending_invoice_items_behavior": "exclude",
                "metadata": inv["metadata"]}, idem=f"in-{ref}")
            for line in inv["lines"]["data"]:
                call(http, "POST", "/invoiceitems", {
                    "customer": cus, "invoice": draft["id"], "amount": line["amount"], "currency": "usd",
                    "description": line["description"], "metadata": line["metadata"]}, idem=f"ii-{line['id']}")
            final = call(http, "POST", f"/invoices/{draft['id']}/finalize")
            if inv["status"] == "paid":
                paid = call(http, "POST", f"/invoices/{final['id']}/pay")
                counts["paid"] += 1
                synthetic_refund = refunds.get(inv["charge"])
                if synthetic_refund:
                    call(http, "POST", "/refunds", {"charge": paid["charge"], "amount": synthetic_refund["amount"],
                                                    "reason": synthetic_refund["reason"]}, idem=f"re-{ref}")
                    counts["refunded"] += 1
            elif inv["status"] == "uncollectible":
                call(http, "POST", f"/invoices/{final['id']}/mark_uncollectible")
                counts["uncollectible"] += 1
            else:
                counts["open"] += 1
        print("invoices:", counts)


def list_all(http, resource, **params):
    """Every object of a type, newest first, following Stripe's cursor pagination."""
    after = None
    while True:
        page = call(http, "GET", f"/{resource}", {"limit": 100, "starting_after": after, **params})
        yield from page["data"]
        if not page["has_more"]:
            return
        after = page["data"][-1]["id"]


def pull(out: Path):
    """Extract every object type the warehouse stages into out/stripe/<object>.jsonl, as {"id", "data"} lines."""
    (out / "stripe").mkdir(parents=True, exist_ok=True)
    with client() as http:
        for obj in STRIPE_OBJECTS:
            rows = []
            for o in list_all(http, obj):
                if obj == "invoices" and o["lines"]["has_more"]:  # embedded lines stop at 10
                    o["lines"]["data"] = list(list_all(http, f"invoices/{o['id']}/lines"))
                    o["lines"]["has_more"] = False
                rows.append(o)
            with open(out / "stripe" / f"{obj}.jsonl", "w", encoding="utf-8", newline="\n") as f:
                for o in sorted(rows, key=lambda o: o["id"]):
                    f.write(json.dumps({"id": o["id"], "data": o}, separators=(",", ":")) + "\n")
            print(f"{obj}: {len(rows)}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed")
    s.add_argument("--customers", type=int, default=10)
    s.add_argument("--months", type=int, default=2)
    sub.add_parser("pull").add_argument("--out", default="data/stripe_sandbox")
    a = p.parse_args()
    seed(a.customers, a.months) if a.cmd == "seed" else pull(Path(a.out))


if __name__ == "__main__":
    main()
