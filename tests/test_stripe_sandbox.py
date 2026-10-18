"""Stripe sandbox client: form encoding and the test-key guard (offline; no API calls)."""
import pytest

from finance_os.ingestion import stripe_sandbox


def test_nested_params_use_stripe_form_encoding():
    assert stripe_sandbox.form({"customer": "cus_1", "auto_advance": False, "due": None,
                                "metadata": {"erp_invoice_ref": "INV-1"},
                                "invoice_settings": {"default_payment_method": "pm_1"}}) == {
        "customer": "cus_1", "auto_advance": "false", "metadata[erp_invoice_ref]": "INV-1",
        "invoice_settings[default_payment_method]": "pm_1"}


@pytest.mark.parametrize("key", ["sk_live_abc", "pk_test_abc"])
def test_only_sandbox_secret_keys_are_accepted(monkeypatch, key):
    monkeypatch.setattr(stripe_sandbox, "load_dotenv", lambda p: None)
    monkeypatch.setenv("STRIPE_SECRET_KEY", key)
    with pytest.raises(SystemExit, match="non-test"):
        stripe_sandbox.client()
