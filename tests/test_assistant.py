"""Assistant backend tests. The model is a scripted fake (no network); the warehouse is the real local build,
so these are skipped until `dbt build` has produced data/finance_os.duckdb."""
import json

import pytest
from fastapi.testclient import TestClient

from finance_os.app.agent import MAX_STEPS, Agent
from finance_os.app.api import create_app
from finance_os.app.state import AppState
from finance_os.app.tools import WAREHOUSE, Warehouse
from finance_os.app.validator import unverified_numbers

needs_warehouse = pytest.mark.skipif(not WAREHOUSE.exists(), reason="build the warehouse first")


# ---- validator -------------------------------------------------------------------------------------

def test_validator_accepts_rounded_and_scaled_numbers():
    results = [{"rows": [{"value": 30335.85}, {"value": 0.4638}, {"value": 2547908.96}, {"days": 58.9}]}]
    text = "EN-001 owes $30,335.85 (about $30.3K). Gross margin is 46.4%, ARR $2.55M, DSO 58.9 days."
    assert unverified_numbers(text, results) == []


def test_validator_flags_invented_numbers_and_ignores_ids_and_dates():
    results = [{"rows": [{"value": 30335.85}]}]
    text = "Invoice INV-EN-001-202606 from 2026-06 (P-103, PO00001, September 2026) is $30,335.85; total due is $41,200."
    assert unverified_numbers(text, results) == ["$41,200"]


# ---- fake model --------------------------------------------------------------------------------------

def call(name, args, cid="c1"):
    return {"id": f"call_{name}_{cid}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def scripted(*replies):
    """A fake `complete`: each reply is a list of tool calls or a final text answer."""
    replies = list(replies)
    seen = []

    def complete(messages, specs, model):
        seen.append(messages)
        reply = replies.pop(0) if replies else "done"
        msg = {"role": "assistant", "content": None}
        if isinstance(reply, list):
            msg["tool_calls"] = reply
        else:
            msg["content"] = reply
        return {"choices": [{"message": msg}], "usage": {"prompt_tokens": 100, "completion_tokens": 10}}

    complete.seen = seen
    return complete


@pytest.fixture
def state(tmp_path):
    return AppState(tmp_path / "app.duckdb")


@needs_warehouse
def test_agent_calls_tools_and_answers_with_verified_numbers(state):
    wh = Warehouse()
    runway = wh.query("select value from marts.fct_kpi_monthly where metric_name = 'runway_months' "
                      "and month = (select max(month) from marts.fct_kpi_monthly)")[0]["value"]
    fake = scripted([call("get_kpis", {"metrics": ["runway_months"]})], f"Runway is {runway:.1f} months.")
    cid = state.new_conversation()
    events = list(Agent(state, wh, complete=fake).run(cid, "What's our runway?"))
    kinds = [e["type"] for e in events]
    assert kinds == ["step", "tool_result", "answer", "done"]
    assert events[2]["unverified_numbers"] == []
    assert events[1]["source"].startswith("marts.fct_kpi_monthly")
    assert "Reconciliation: all" in fake.seen[0][0]["content"]  # recon status reaches the system prompt


@needs_warehouse
def test_invented_number_triggers_one_retry_then_is_flagged(state):
    fake = scripted([call("get_kpis", {"metrics": ["runway_months"]})], "Runway is 99.9 months.", "Runway is 77.7 months.")
    cid = state.new_conversation()
    events = list(Agent(state, Warehouse(), complete=fake).run(cid, "Runway?"))
    kinds = [e["type"] for e in events]
    assert kinds.count("validator_retry") == 1
    answer = next(e for e in events if e["type"] == "answer")
    assert answer["unverified_numbers"] == ["77.7"]


@needs_warehouse
def test_step_limit_stops_a_runaway_loop(state):
    fake = scripted(*[[call("get_reconciliation_status", {}, cid=str(i))] for i in range(MAX_STEPS + 5)])
    cid = state.new_conversation()
    events = list(Agent(state, Warehouse(), complete=fake).run(cid, "loop"))
    assert sum(e["type"] == "step" for e in events) == MAX_STEPS
    assert events[-1]["stopped"] == "step_limit"


@needs_warehouse
def test_proposal_then_approve_and_undo_through_the_api(state):
    wh = Warehouse()
    pay = wh.query("select payment_id, remittance_ref from staging.stg_erp__customer_payments "
                   "where remittance_ref <> applied_ref limit 1")[0]
    fake = scripted([call("propose_cash_application_fix", {"payment_id": pay["payment_id"],
                                                           "correct_invoice_ref": pay["remittance_ref"],
                                                           "note": "Remittance names this invoice."})],
                    "I've prepared the fix for your approval.")
    client = TestClient(create_app(state, wh, agent_factory=lambda: Agent(state, wh, complete=fake)))
    cid = client.post("/api/conversations").json()["id"]
    body = client.post(f"/api/conversations/{cid}/messages", json={"text": "fix the misapplied payment"}).text
    events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    proposal = next(e for e in events if e["type"] == "proposal")["action"]
    assert proposal["status"] == "pending"  # proposing executes nothing

    aid = proposal["id"]
    assert client.post(f"/api/actions/{aid}/approve").json()["action"]["status"] == "approved"
    undone = client.post(f"/api/actions/{aid}/undo").json()
    assert undone["action"]["status"] == "reverted"
    assert [a["event"] for a in undone["audit"]] == ["proposed", "approved", "undone"]
    assert client.post(f"/api/actions/{aid}/undo").status_code == 409  # history is never rewritten


@needs_warehouse
def test_proposal_refuses_targets_that_do_not_exist(state):
    fake = scripted([call("propose_ap_document_decision", {"doc_file": "NOPE.pdf", "decision": "approve", "reason": "x"})],
                    "That document doesn't exist.")
    cid = state.new_conversation()
    events = list(Agent(state, Warehouse(), complete=fake).run(cid, "approve NOPE"))
    assert next(e for e in events if e["type"] == "tool_result")["error"].startswith("No AP document")
    assert state.actions() == []


@needs_warehouse
def test_metric_names_in_tool_schema_match_the_catalog():
    from finance_os.app.tools import METRIC_NAMES
    catalog = {r["metric_name"] for r in Warehouse().query("select metric_name from seeds.metric_catalog")}
    assert set(METRIC_NAMES) == catalog


@needs_warehouse
def test_answer_without_tools_is_sent_back_once(state):
    fake = scripted("There are no billing exceptions.", [call("get_billing_status", {})], "PINV00014 has a rate mismatch.")
    cid = state.new_conversation()
    events = list(Agent(state, Warehouse(), complete=fake).run(cid, "Any wrong rates?"))
    retries = [e for e in events if e["type"] == "validator_retry"]
    assert [r["reason"] for r in retries] == ["no_tools"]
    assert next(e for e in events if e["type"] == "step")["tool"] == "get_billing_status"


def test_validator_accepts_thresholds_named_in_fields():
    assert unverified_numbers("Over 75% funded, not yet 90%.", [{"is_funding_alert_75": True, "is_funding_alert_90": False}]) == []


@needs_warehouse
def test_conversation_replays_as_the_same_events(state):
    wh = Warehouse()
    fake = scripted([call("get_kpis", {"metrics": ["arr"]})], "ARR is shown above.")
    client = TestClient(create_app(state, wh, agent_factory=lambda: Agent(state, wh, complete=fake)))
    cid = client.post("/api/conversations").json()["id"]
    client.post(f"/api/conversations/{cid}/messages", json={"text": "What's ARR?"})
    turns = client.get(f"/api/conversations/{cid}").json()["turns"]
    assert [t["text"] for t in turns] == ["What's ARR?"]
    assert [e["type"] for e in turns[0]["events"]] == ["step", "tool_result", "answer", "done"]
    assert client.get("/api/conversations").json()[0]["title"] == "What's ARR?"


@needs_warehouse
def test_upload_checks_catch_duplicates_po_problems_and_vendor_name_variants(state):
    from finance_os.app.documents import Documents, check
    Documents(state, Warehouse())  # creates the uploads table
    wh = Warehouse()
    posted = wh.query("""select b.vendor_invoice_number, b.po_id from staging.stg_projects__subcontractor_bills b
                         join staging.stg_projects__purchase_orders po using (po_id)
                         where b.vendor_id = 'annotate_co'
                           and po.amount - (select sum(amount) from staging.stg_projects__subcontractor_bills x
                                            where x.po_id = po.po_id) > 100
                         limit 1""")[0]
    base = {"vendor_name": "ANNOTATE CO.", "vendor_invoice_number": "AC-2099-0001", "po_number": posted["po_id"],
            "total": 10.0, "lines": [{"amount": 10.0}]}
    vendor, issues = check(wh, state, "UP-TEST", base)
    assert vendor == "annotate_co" and issues == []  # case and punctuation don't matter

    codes = lambda f: [i["code"] for i in check(wh, state, "UP-TEST", {**base, **f})[1]]
    assert codes({"vendor_invoice_number": posted["vendor_invoice_number"]}) == ["duplicate_invoice"]
    assert codes({"total": 11.0}) == ["arithmetic_mismatch"]
    assert codes({"po_number": "PO99999"}) == ["po_not_found"]
    assert codes({"po_number": None}) == ["missing_po"]
    assert codes({"vendor_name": "Unknown Vendor Ltd"}) == ["unknown_vendor"]
    assert codes({"total": 999999.0, "lines": [{"amount": 999999.0}]}) == ["po_over_remaining"]


@needs_warehouse
def test_every_read_tool_runs_against_the_warehouse():
    """Each read tool must return without error on today's data (the Home page and 'what needs attention' depend
    on them; one bad format string once took the whole attention list down)."""
    from finance_os.app.tools import TOOLS, run_tool
    wh = Warehouse()
    needs = {"get_kpi_trend": {"metric": "revenue"}, "get_metric_definition": {"metric": "arr"},
             "get_variance_drivers": {"alert_id": "none"}, "get_customer_detail": {"customer_id": "EN-001"},
             "get_vendor_detail": {"vendor_id": "gcp"}, "get_project_detail": {"project_id": "P-101"},
             "price_deal": {"customer": "Test", "lines": [{"product_id": "stream", "hours_per_month": 1000}]}}
    for name in TOOLS:
        result = run_tool(wh, name, needs.get(name, {}))
        assert "source" in result, name
