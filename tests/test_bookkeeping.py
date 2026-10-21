"""Bookkeeping: the bank statement reconciles to GL cash, and manual journal entries are controlled."""
from datetime import date
from decimal import Decimal

import pytest

from finance_os.app import tools
from finance_os.app.bookkeeping import Bookkeeping
from finance_os.app.state import AppState
from finance_os.ingestion import bank_feed


@pytest.fixture(scope="module")
def wh():
    return tools.Warehouse()


@pytest.fixture()
def books(wh, tmp_path):
    return Bookkeeping(AppState(tmp_path / "app.duckdb"), wh)


def test_transposed_amounts_swap_two_digits():
    assert bank_feed._transposed(Decimal("-4521.30")) == Decimal("-4251.30")
    assert bank_feed._transposed(Decimal("1200.00")) == Decimal("1020.00")


def test_business_days_skip_weekends():
    assert bank_feed._business_days(date(2026, 10, 16), 1) == date(2026, 10, 19)  # Friday + 1 = Monday
    assert bank_feed._business_days(date(2026, 10, 17), 0) == date(2026, 10, 19)  # booked Saturday clears Monday


def test_bank_reconciliation_ties_every_month(wh):
    rec = wh.query("select * from marts.fct_bank_reconciliation")
    if not rec:
        pytest.skip("no bank statements in this warehouse")
    for r in rec:
        bank = r["bank_balance"] + r["deposits_in_transit"] - r["outstanding_payments"]
        book = r["gl_balance"] + r["unrecorded_bank_items"] + r["ledger_errors"]
        assert bank == pytest.approx(r["adjusted_bank_balance"], abs=0.005), r
        assert book == pytest.approx(r["adjusted_book_balance"], abs=0.005), r
        assert r["unexplained_difference"] == 0, r


def test_bank_only_items_and_errors_need_an_entry(wh):
    items = wh.query("select item_type, needs_journal_entry from marts.fct_bank_reconciling_items")
    if not items:
        pytest.skip("no bank statements in this warehouse")
    for i in items:
        assert i["needs_journal_entry"] == (i["item_type"] in ("bank_fee", "interest", "unrecorded_bank_item", "ledger_error"))


def test_trial_balance_balances(wh):
    tb = tools.get_trial_balance(wh)
    assert tb["totals"]["debit"] == pytest.approx(tb["totals"]["credit"], abs=0.01)


def _entry(books, **over):
    first, _ = books.periods()
    e = {"entry_date": f"{first}-15", "memo": "Test entry",
         "lines": [{"account_id": "6700", "entity_id": "US01", "debit": "100.00", "credit": ""},
                   {"account_id": "1000", "entity_id": "US01", "debit": "", "credit": "100.00"}]}
    return {**e, **over}


def test_entry_controls(books):
    first, _ = books.periods()
    assert books.validate(_entry(books)) == []
    unbalanced = _entry(books, lines=[{"account_id": "6700", "entity_id": "US01", "debit": "100", "credit": ""},
                                      {"account_id": "1000", "entity_id": "US01", "debit": "", "credit": "90"}])
    assert any("differ" in e for e in books.validate(unbalanced))
    cross = _entry(books, lines=[{"account_id": "6700", "entity_id": "US01", "debit": "100", "credit": ""},
                                 {"account_id": "1000", "entity_id": "UK01", "debit": "", "credit": "100"}])
    assert any("each entity must balance" in e for e in books.validate(cross))
    y, m = int(first[:4]), int(first[5:7])
    locked = f"{y - (m == 1)}-{(m - 2) % 12 + 1:02d}-15"
    assert any("locked" in e for e in books.validate(_entry(books, entry_date=locked)))
    assert any("unknown account" in e for e in books.validate(_entry(books, lines=[
        {"account_id": "9999", "entity_id": "US01", "debit": "1", "credit": ""},
        {"account_id": "1000", "entity_id": "US01", "debit": "", "credit": "1"}])))


def test_entry_posts_only_after_approval_and_reverses(books):
    before = books.trial_balance()
    out = books.create(_entry(books))
    assert out["entry_id"].startswith("MJE-")
    assert books.entries()[0]["status"] == "awaiting approval"
    assert books.trial_balance()["rows"] == before["rows"]  # nothing posted yet
    books.state.decide(out["proposed_action_id"], "approved")
    after = books.trial_balance()
    assert after["balanced"]
    fees = {r["account_id"]: r for r in after["rows"]}["6700"]
    assert fees["manual_entries"] == pytest.approx(100)
    assert "MJE-" in books.export_csv()
    books.state.decide(out["proposed_action_id"], "reverted")
    assert books.entries()[0]["status"] == "reversed"
    assert "6700" not in {r["account_id"] for r in books.trial_balance()["rows"] if r["manual_entries"]}


def test_a_bank_item_is_booked_once(books):
    rec = books.bank_reconciliation()
    item = next((i for i in rec.get("items", []) if i["needs_journal_entry"] and i["suggested_entry"]
                 and all(l["account_id"] for l in i["suggested_entry"]["lines"])), None)
    if not item:
        pytest.skip("no bank items to book")
    assert books.validate(item["suggested_entry"]) == []
    books.create(item["suggested_entry"])
    assert any("already booked" in e for e in books.validate(item["suggested_entry"]))
    booked = next(i for i in books.bank_reconciliation()["items"] if i["statement_line_id"] == item["statement_line_id"])
    assert booked["booking"]["status"] == "awaiting approval"
