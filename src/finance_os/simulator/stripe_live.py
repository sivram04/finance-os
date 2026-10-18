"""What the simulator does in Stripe (sandbox only): customers, invoices, card charges, failures, refunds.

`NoStripe` stands in when running offline (--no-stripe, tests): same calls, nothing sent.
"""
from decimal import Decimal

from finance_os.ingestion.stripe_sandbox import call, client, search_one


def _cents(x):
    return int(x * 100)


class SandboxStripe:
    def __init__(self):
        self.http = client()

    def close(self):
        self.http.close()

    def ensure_customer(self, c):
        if c.stripe_id:
            return c.stripe_id
        found = search_one(self.http, "customers", f"metadata['erp_customer_id']:'{c.customer_id}'")
        if not found:
            found = call(self.http, "POST", "/customers", {
                "name": c.name, "email": f"billing@{c.customer_id.lower()}.example.com",
                "metadata": {"erp_customer_id": c.customer_id, "segment": c.segment}}, idem=f"cus-{c.customer_id}")
            pm = call(self.http, "POST", "/payment_methods/pm_card_visa/attach", {"customer": found["id"]})
            call(self.http, "POST", f"/customers/{found['id']}", {"invoice_settings": {"default_payment_method": pm["id"]}})
        c.stripe_id = found["id"]
        return c.stripe_id

    def invoice(self, c, ref, month, today, lines, terms_days):
        cus = self.ensure_customer(c)
        auto = terms_days == 0
        inv = call(self.http, "POST", "/invoices", {
            "customer": cus, "collection_method": "charge_automatically" if auto else "send_invoice",
            "days_until_due": None if auto else terms_days, "auto_advance": False,
            "pending_invoice_items_behavior": "exclude",
            "metadata": {"erp_invoice_ref": ref, "service_month": month.isoformat()}}, idem=f"in-{ref}")
        for p, hours, unit, amount in lines:
            call(self.http, "POST", "/invoiceitems", {
                "customer": cus, "invoice": inv["id"], "amount": _cents(amount), "currency": "usd",
                "description": f"{p} audio transcription ({month:%B %Y})",
                "metadata": {"product_id": p, "audio_hours": str(hours)}}, idem=f"ii-{ref}-{p}")
        return call(self.http, "POST", f"/invoices/{inv['id']}/finalize", idem=f"fin-{ref}")["id"]

    def pay(self, invoice_id):
        """Collect an invoice; returns (charge id, Stripe's actual processing fee in dollars)."""
        charge = call(self.http, "POST", f"/invoices/{invoice_id}/pay", idem=f"pay-{invoice_id}").get("charge")
        if not charge:
            return None, None
        txn = call(self.http, "GET", f"/charges/{charge}", {"expand[]": "balance_transaction"}).get("balance_transaction")
        fee = Decimal(txn["fee"]) / 100 if isinstance(txn, dict) else None
        return charge, fee

    def fail(self, c, invoice_id):
        """Attempt the charge with Stripe's always-declined test card: a real failed charge in the sandbox."""
        pm = call(self.http, "POST", "/payment_methods/pm_card_chargeCustomerFail/attach", {"customer": c.stripe_id})
        try:
            call(self.http, "POST", f"/invoices/{invoice_id}/pay", {"payment_method": pm["id"]})
        except RuntimeError:
            pass  # the decline is the point

    def uncollectible(self, invoice_id):
        call(self.http, "POST", f"/invoices/{invoice_id}/mark_uncollectible")

    def refund(self, charge_id, amount, ref):
        return call(self.http, "POST", "/refunds", {"charge": charge_id, "amount": _cents(amount)}, idem=f"re-{ref}")["id"]


class NoStripe:
    def close(self):
        pass

    def invoice(self, *a):
        return None

    def pay(self, invoice_id):
        return None, None

    def fail(self, c, invoice_id):
        pass

    def uncollectible(self, invoice_id):
        pass

    def refund(self, *a):
        return None
