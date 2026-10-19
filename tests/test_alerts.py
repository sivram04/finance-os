"""Alert delivery: new keys go out once, repeats stay quiet, acknowledged stay quiet, cleared ones resolve."""
from finance_os import alerts


def _a(key, sev="high"):
    return {"alert_key": key, "rule_id": key.split("|")[0], "severity": sev, "entity_id": "x", "period": None,
            "message": f"msg {key}", "recipients": "Controller", "page": "cash"}


def test_new_once_then_quiet_then_resolved(tmp_path, monkeypatch):
    monkeypatch.setattr(alerts, "LOG_DB", tmp_path / "alerts.duckdb")
    new, resolved = alerts.reconcile([_a("COVENANT|LIQ-1|-"), _a("AR-60|INV-1|-", "medium")])
    assert len(new) == 2 and not resolved
    new, resolved = alerts.reconcile([_a("COVENANT|LIQ-1|-"), _a("AR-60|INV-1|-", "medium")])
    assert not new and not resolved                                    # no repeat pings
    assert alerts.acknowledge("AR-60|INV-1|-")
    new, resolved = alerts.reconcile([_a("COVENANT|LIQ-1|-")])          # AR invoice got paid
    assert not new and [r["alert_key"] for r in resolved] == ["AR-60|INV-1|-"]
    text = alerts.digest([_a("MIN-CASH-13W|cash|-")], resolved, "http://app")
    assert text.index("[HIGH]") < text.index("resolved") and "http://app/#cash" in text


def test_nothing_is_sent_without_a_configured_channel(monkeypatch):
    for k in ("SLACK_WEBHOOK_URL", "TELEGRAM_BOT_TOKEN", "SMTP_HOST"):
        monkeypatch.delenv(k, raising=False)
    assert alerts.send("hello") == []
