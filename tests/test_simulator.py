"""Live simulator: AI events are validated, amounts come from the price book, cash follows terms (offline)."""
from datetime import date, timedelta
from decimal import Decimal

from finance_os.simulator.engine import Day, read
from finance_os.simulator.stripe_live import NoStripe
from finance_os.simulator.world import Customer, World

EVENT = dict.fromkeys(["customer_id", "segment", "products", "size", "multiplier", "days", "invoice_ref", "pct",
                       "contract_id", "milestone_name"])


def ev(**kw):
    return {**EVENT, "reason": "test", **kw}


def _world():
    w = World(as_of="2026-09-29")
    w.customers = {
        "SS-001": Customer("SS-001", "Small", "self_serve", "active", {"batch_base": "10.0000"}, "0.0000"),
        "MM-001": Customer("MM-001", "Mid", "mid_market", "active", {"stream": "500.0000"}, "0.0000"),
    }
    w.contracts = {"C-1": {"customer_id": "MM-001", "type": "fixed_fee", "funded": "1000.00", "invoiced": "900.00",
                           "terms_days": 30, "end": "2027-01-01", "is_federal": False}}
    return w


def _run(w, day, events, live):
    return Day(w, day, NoStripe(), live).run(decide=lambda s, tools: (events, {"total_tokens": 0}))


def test_bad_events_are_rejected_and_good_ones_applied(tmp_path):
    w = _world()
    out = _run(w, date(2026, 9, 30), [
        ev(type="expansion", customer_id="MM-001", multiplier=1.5),
        ev(type="expansion", customer_id="MM-001", multiplier=9),            # outside bounds
        ev(type="churn", customer_id="XX-404"),                               # unknown customer
        ev(type="project_milestone", contract_id="C-1", milestone_name="M3", pct=0.5),
        ev(type="payment_failure", customer_id="MM-001")], tmp_path)          # not a card customer (5th: over cap)
    status = [d["status"] for d in out["decisions"]]
    assert status == ["applied", "rejected", "rejected", "applied"]
    assert Decimal(w.customers["MM-001"].daily_hours["stream"]) == Decimal("750.0000")
    assert out["project_invoices"][0]["amount"] == "50.00" and w.contracts["C-1"]["invoiced"] == "950.00"


def test_month_start_bills_last_months_usage_at_list_price(tmp_path):
    w = _world()
    _run(w, date(2026, 9, 30), [], tmp_path)
    out = _run(w, date(2026, 10, 1), [], tmp_path)
    sept = {u["customer_id"]: Decimal(u["audio_hours"]) for u in read(tmp_path, "usage_daily") if u["usage_date"] == "2026-09-30"}
    inv = {i["customer_id"]: Decimal(i["amount"]) for i in out["invoices"]}
    assert inv["MM-001"] == (sept["MM-001"] * Decimal("0.47")).quantize(Decimal("0.01"))
    assert "LIVE-202609-SS-001" in w.paid and "LIVE-202609-MM-001" in w.open_invoices  # card now, invoice on terms


def test_failed_card_retries_then_goes_uncollectible_and_churns(tmp_path):
    w = _world()
    _run(w, date(2026, 9, 30), [ev(type="payment_failure", customer_id="SS-001")], tmp_path)
    day = date(2026, 10, 1)
    while w.customers["SS-001"].status == "active" and day < date(2026, 10, 20):
        _run(w, day, [], tmp_path)
        day += timedelta(days=1)
    attempts = [a for a in read(tmp_path, "payment_attempts") if a["invoice_ref"] == "LIVE-202609-SS-001"]
    assert len(attempts) == 3 and w.customers["SS-001"].status == "churned"
    assert "LIVE-202609-SS-001" not in w.open_invoices and "LIVE-202609-SS-001" not in w.paid


def test_memory_filters_exactly_then_ranks_by_meaning(tmp_path):
    from finance_os.simulator.memory import Memory, history_chunks
    vocab = ["churn", "expansion", "price", "growth"]
    fake_embed = lambda texts: [[float(w in t.lower()) + 0.01 for w in vocab] for t in texts]
    m = Memory(tmp_path / "m.duckdb", embedder=fake_embed)
    rows = [{"event_id": "1", "event_date": "2025-03-01", "event_type": "churn", "customer_id": "SS-001", "multiplier": "0", "reason": "price"},
            {"event_id": "2", "event_date": "2025-04-01", "event_type": "expansion", "customer_id": "MM-001", "multiplier": "1.3", "reason": "organic_growth"},
            {"event_id": "3", "event_date": "2026-01-01", "event_type": "churn", "customer_id": "MM-002", "multiplier": "0", "reason": "built_in_house"}]
    assert m.add(history_chunks(rows, {"SS-001": "self_serve", "MM-001": "mid_market", "MM-002": "mid_market"})) == 3
    assert m.add(history_chunks(rows, {})) == 0                       # idempotent
    assert [r["text"][:10] for r in m.search("growth", k=1)] == ["2025-04-01"]
    assert [r["date"] for r in m.search("churn", event_type="churn", since="2025-06-01")] == ["2026-01-01"]
    assert m.search("anything", customer_id="SS-001")[0]["text"].endswith("Reason: price.")
