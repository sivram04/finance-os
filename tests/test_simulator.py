"""Live simulator: AI events are validated, amounts come from the price book, cash follows terms (offline)."""
from datetime import date, timedelta
from decimal import Decimal

from finance_os.simulator.engine import Day, read
from finance_os.simulator.stripe_live import NoStripe
from finance_os.simulator.world import Customer, World

EVENT = dict.fromkeys(["customer_id", "segment", "products", "size", "multiplier", "days", "invoice_ref", "pct", "vendor_id", "category",
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
                           "terms_days": 30, "end": "2027-01-01", "is_federal": False, "project_id": "P-1"}}
    w.ops = {"cash": "100000.00", "employees": [{"employee_id": "E001", "department_id": "ENG", "annual_salary": "120000",
                                                 "title": "Engineer"}],
             "planned_hires": [{"role_id": "R-1", "department_id": "SAL", "title": "AE", "annual_salary": "90000",
                                "planned_start": "2026-10-03", "status": "open"}],
             "employee_seq": 1, "base_headcount": 1,
             "opex_template": [{"memo": "Rent", "account_id": "6300", "department_id": "GA", "amount": "1000.00"}],
             "vendor_cost_per_hour": [{"vendor_id": "gcp", "line_type": "cloud_services", "gpu_type": "", "per_hour": "0.01"},
                                      {"vendor_id": "nimbus", "line_type": "gpu_usage", "gpu_type": "H100", "per_hour": "0.05"}],
             "gpu_rates": {"H100": "3.40"}, "gcp_prod_share": "0.6", "price_factor": {"gcp": "1", "nimbus": "1"},
             "invoice_seq": {}, "accrued": {}, "pending_duplicates": [], "open_bills": {}}
    return w


def _run(w, day, events, live):
    return Day(w, day, NoStripe(), live, inbox=live / "inbox").run(decide=lambda s, tools: (events, {"total_tokens": 0}))


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
    assert "INV-SS-001-202609" in w.paid and "INV-MM-001-202609" in w.open_invoices  # card now, invoice on terms


def test_failed_card_retries_then_goes_uncollectible_and_churns(tmp_path):
    w = _world()
    _run(w, date(2026, 9, 30), [ev(type="payment_failure", customer_id="SS-001")], tmp_path)
    day = date(2026, 10, 1)
    while w.customers["SS-001"].status == "active" and day < date(2026, 10, 20):
        _run(w, day, [], tmp_path)
        day += timedelta(days=1)
    attempts = [a for a in read(tmp_path, "payment_attempts") if a["invoice_ref"] == "INV-SS-001-202609"]
    assert len(attempts) == 3 and w.customers["SS-001"].status == "churned"
    assert "INV-SS-001-202609" not in w.open_invoices and "INV-SS-001-202609" not in w.paid


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


def test_books_balance_and_cash_moves_with_every_entry(tmp_path):
    w = _world()
    start = Decimal(w.ops["cash"])
    day = date(2026, 9, 30)
    while day <= date(2026, 11, 10):
        _run(w, day, [], tmp_path)
        day += timedelta(days=1)
    lines = read(tmp_path, "journal_lines")
    by_entry = {}
    for l in lines:
        by_entry.setdefault(l["entry_id"], [0, 0])
        by_entry[l["entry_id"]][0] += Decimal(l["debit"])
        by_entry[l["entry_id"]][1] += Decimal(l["credit"])
    assert by_entry and all(d == c for d, c in by_entry.values())
    cash = sum(Decimal(l["debit"]) - Decimal(l["credit"]) for l in lines if l["account_id"] == "1000")
    assert Decimal(w.ops["cash"]) == start + cash
    types = {e["entry_type"] for e in read(tmp_path, "journal_entries")}
    assert {"revenue", "collection", "payroll", "opex", "vendor_bill", "vendor_payment"} <= types
    assert [e["employee_id"] for e in read(tmp_path, "employees")] == ["E002"]   # the planned hire started


def test_vendor_bill_arrives_as_pdf_is_trued_up_and_paid_with_discount(tmp_path):
    w = _world()
    _run(w, date(2026, 9, 30), [], tmp_path)                                       # month end: accrue Sept
    accrued = {r: a for r, a in w.ops["accrued"].items()}
    assert set(accrued) == {"BILL-GCP-202609", "BILL-NIMBUS-202609"}
    day = date(2026, 10, 1)
    while day < date(2026, 10, 5):
        _run(w, day, [], tmp_path)
        day += timedelta(days=1)
    _run(w, day, [ev(type="vendor_price_increase", vendor_id="nimbus", pct=0.10),
                  ev(type="duplicate_bill", vendor_id="gcp")], tmp_path)          # the 5th: bills arrive
    bills = {b["bill_id"]: b for b in read(tmp_path, "vendor_bills")}
    assert set(bills) == {"BILL-GCP-202609", "BILL-NIMBUS-202609"}
    true_ups = [e for e in read(tmp_path, "journal_entries") if "true-up" in e["memo"]]
    assert any("nimbus" in e["memo"] for e in true_ups)                          # billed 10% over the accrual
    pdfs = sorted(f.name for f in (tmp_path / "inbox").glob("*.pdf"))
    assert len(pdfs) == 3 and any("_copy2" in f for f in pdfs)                    # gcp sent twice
    while "BILL-NIMBUS-202609" in w.ops["open_bills"]:
        day += timedelta(days=1)
        _run(w, day, [], tmp_path)
    pay = next(p for p in read(tmp_path, "ap_payments") if p["bill_id"] == "BILL-NIMBUS-202609")
    assert day.weekday() == 3 and Decimal(pay["discount"]) > 0                    # first Thursday, inside 10 days


def test_one_off_bill_from_new_vendor_posts_to_ap(tmp_path):
    w = _world()
    _run(w, date(2026, 10, 2), [ev(type="wrong_po_bill", category="legal", size="medium")], tmp_path)
    (bill,) = [b for b in w.ops["open_bills"].values() if b["vendor_id"] == "lexpoint"]
    docs = read(tmp_path, "ap_documents")
    assert docs[0]["issue"] == "wrong_po" and Decimal(bill["amount"]) > 0


def test_provider_order_falls_through_to_the_next(monkeypatch):
    from finance_os.simulator import agent, claude_provider
    calls = []

    def quota_exceeded(summary, tools):
        calls.append("api")
        raise RuntimeError("HTTP Error 429: insufficient_quota")

    def claude(summary, tools=None):
        calls.append("claude_code")
        return [], {"total_tokens": 1}

    monkeypatch.setenv("SIM_PROVIDERS", "api,claude_code")
    monkeypatch.setattr(agent, "decide", quota_exceeded)
    monkeypatch.setattr(claude_provider, "decide", claude)
    events, usage = agent.decide_with_provider({}, {})
    assert calls == ["api", "claude_code"] and "insufficient_quota" in usage["fallback_from"]
