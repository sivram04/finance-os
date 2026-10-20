"""HTTP API for the workspace (design §9.5).

    python -m finance_os.app            # http://127.0.0.1:8000, docs at /docs

POST /api/conversations/{id}/messages streams the agent's events as Server-Sent Events, one JSON object per
`data:` line (step, tool_result, proposal, validator_retry, answer, error, done). Approving, rejecting and
undoing actions happen only here, from the user's click; the assistant can only propose.
"""
import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from finance_os.app import tools
from finance_os.paths import ROOT
import base64

from fastapi.responses import FileResponse

from finance_os.app.agent import Agent
from finance_os.app.documents import Documents
from finance_os.app.history import replay
from finance_os.app.state import AppState


class MessageIn(BaseModel):
    text: str


class UploadIn(BaseModel):
    filename: str
    content_base64: str


class DecisionIn(BaseModel):
    note: str | None = None


def create_app(state: AppState | None = None, wh: tools.Warehouse | None = None, agent_factory=None):
    state = state or AppState()
    wh = wh or tools.Warehouse()
    agent_factory = agent_factory or (lambda: Agent(state, wh))
    app = FastAPI(title="Finance OS", version="0.1.0")
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["*"], allow_headers=["*"])

    @app.get("/api/health")
    def health():
        # the simulator's own date: quiet days post nothing, so the last journal entry can lag behind it
        world = ROOT / "data" / "live" / "world.json"
        live = json.loads(world.read_text(encoding="utf-8")).get("as_of") if world.exists() else None
        live = live or wh.query("select max(entry_date) as d from staging.stg_erp__journal_entries")[0]["d"]
        return {"ok": True, "data_through": wh.latest_month(), "live_through": live}

    @app.post("/api/conversations")
    def new_conversation():
        return {"id": state.new_conversation()}

    @app.get("/api/conversations")
    def list_conversations():
        return state.conversations()

    @app.get("/api/conversations/{cid}")
    def get_conversation(cid: str):
        """Past turns as the same events the UI renders live (steps, results, approval cards, answer, usage)."""
        if not state.conversation_exists(cid):
            raise HTTPException(404, "conversation not found")
        return {"id": cid, "turns": replay(state, cid)}

    @app.post("/api/conversations/{cid}/messages")
    def post_message(cid: str, body: MessageIn):
        if not state.conversation_exists(cid):
            raise HTTPException(404, "conversation not found")
        agent = agent_factory()

        def stream():
            for event in agent.run(cid, body.text):
                yield f"data: {json.dumps(event, default=str)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    class RecommendIn(BaseModel):
        kind: str          # kpi | variance | situation
        subject: str       # metric name, variance alert id, or the situation title
        context: str = ""  # optional extra the page knows (e.g. the evidence line)

    RECOMMEND_PROMPTS = {
        "kpi": ("The KPI '{subject}' is off its threshold. Using today's data (call get_decision_kpis and whatever tools "
                "explain its drivers), recommend what to do."),
        "variance": ("Budget variance {subject}. Call get_variance_case for it and any tools that explain the drivers, then "
                     "recommend what to do and which of the CFO's choices fits the evidence best."),
        "situation": ("Situation needing a leadership decision: '{subject}'. {context} Call the tools that hold the evidence "
                      "(get_decisions_needed and the relevant detail tools) and recommend what to do."),
    }

    @app.post("/api/recommend")
    def recommend(body: RecommendIn):
        """A recommendation reasoned by the assistant from today's data: not a stored template, so it changes when the
        data changes. Runs as a normal conversation (kept in History) and returns the answer with its evidence."""
        if body.kind not in RECOMMEND_PROMPTS:
            raise HTTPException(400, f"kind must be one of {', '.join(RECOMMEND_PROMPTS)}")
        prompt = (RECOMMEND_PROMPTS[body.kind].format(subject=body.subject, context=body.context) +
                  " Answer in this shape: one line on the situation now, with its key number; then two to four "
                  "recommended actions, each tied to a specific number from the tools, with an owner and the trade-off; "
                  "then what in the data would change this recommendation. Use only numbers the tools return.")
        cid = state.new_conversation()
        answer, steps = None, 0
        for event in agent_factory().run(cid, prompt):
            if event["type"] == "step":
                steps += 1
            if event["type"] == "answer":
                answer = event
            if event["type"] == "error" and answer is None:
                raise HTTPException(502, event["message"])
        if not answer:
            raise HTTPException(502, "no answer")
        return {"conversation_id": cid, "text": answer["text"], "evidence": answer.get("evidence"),
                "unverified_numbers": answer.get("unverified_numbers", []), "steps": steps}

    docs = Documents(state, wh)

    @app.post("/api/documents")
    def upload(body: UploadIn):
        """A vendor bill dropped into the chat: read it (text or OCR) and run the AP controls."""
        try:
            data = base64.b64decode(body.content_base64)
            doc = docs.upload(body.filename, data)
        except (ValueError, RuntimeError) as e:
            raise HTTPException(422, str(e))
        return {k: v for k, v in doc.items() if k != "path"}

    @app.get("/api/documents/{doc_id}")
    def get_document(doc_id: str):
        doc = docs.get(doc_id)
        if not doc:
            raise HTTPException(404, "document not found")
        return {k: v for k, v in doc.items() if k != "path"}

    @app.get("/api/documents/{doc_id}/file")
    def document_file(doc_id: str):
        doc = docs.get(doc_id)
        if not doc:
            raise HTTPException(404, "document not found")
        return FileResponse(doc["path"], filename=doc["filename"])

    @app.get("/api/actions")
    def list_actions(status: str | None = None):
        return state.actions(status=status)

    @app.get("/api/actions/{aid}/evidence")
    def action_evidence(aid: str):
        """What a reviewer needs to decide an approval card: checks, verdict, facts, required approver, links."""
        a = state.action(aid)
        if not a:
            raise HTTPException(404, "action not found")
        doc = None
        if str(a["target_id"]).startswith("UP-"):  # a bill uploaded in the chat: its checks live with the upload
            up = docs.get(a["target_id"])
            if up:
                f = up["fields"]
                doc = {"doc_file": up["id"], "vendor_name": f.get("vendor_name"), "vendor_id": up["vendor_id"],
                       "vendor_invoice_number": f.get("vendor_invoice_number"), "total": f.get("total"),
                       "lines_total": f.get("lines_total", f.get("total")), "erp_amount": None, "po_number": f.get("po_number"),
                       "issues": [i["code"] for i in up["issues"]], "route": up["route"]}
        return tools.get_approval_evidence(wh, a["kind"], a["target_id"], a["payload"], document=doc)

    def _decide(aid, new_status, note):
        try:
            return {"action": state.decide(aid, new_status, note), "audit": state.audit(aid)}
        except KeyError:
            raise HTTPException(404, "action not found")
        except ValueError as e:
            raise HTTPException(409, str(e))

    @app.post("/api/actions/{aid}/approve")
    def approve(aid: str, body: DecisionIn | None = None):
        return _decide(aid, "approved", body.note if body else None)

    @app.post("/api/actions/{aid}/reject")
    def reject(aid: str, body: DecisionIn | None = None):
        return _decide(aid, "rejected", body.note if body else None)

    @app.post("/api/actions/{aid}/undo")
    def undo(aid: str, body: DecisionIn | None = None):
        return _decide(aid, "reverted", body.note if body else None)

    class DisputeBody(BaseModel):
        rep_id: str
        month: str
        customer_id: str
        claim: str
        claimed_amount: float | None = None

    @app.post("/api/commission-disputes")
    def raise_dispute(body: DisputeBody):
        """A rep raises a dispute from the Commissions page; it becomes an approval card for Finance."""
        from finance_os.app.actions import propose_commission_dispute
        out = propose_commission_dispute(wh, state, None, **body.model_dump())
        if out.get("error"):
            raise HTTPException(400, out["error"])
        return out

    @app.get("/api/commission-disputes")
    def list_disputes():
        """Every dispute with its status and the reviewer's resolution note."""
        out = []
        for a in state.actions():
            if a["kind"] != "commission_dispute":
                continue
            payload = json.loads(a["payload"]) if isinstance(a["payload"], str) else a["payload"]
            trail = state.audit(a["id"])
            decided = [t for t in trail if t["event"] in ("approved", "rejected", "undone")]
            out.append({"id": a["id"], "status": a["status"], **payload,
                        "raised_at": a["created_at"].isoformat() if hasattr(a["created_at"], "isoformat") else a["created_at"],
                        "resolution": decided[-1]["note"] if decided else None,
                        "decided_by": a.get("decided_by")})
        return out[::-1]

    class VarianceDecision(BaseModel):
        alert_id: str
        decision: str
        note: str = ""
        actions: list[dict] = []

    @app.post("/api/variance-decisions")
    def record_variance_decision(body: VarianceDecision):
        """The CFO's decision on a variance: recorded as an action decided by the CFO, with the evidence summary and the
        owner actions it commits to, in the audit log. A later decision on the same variance supersedes it."""
        case = tools.get_variance_case(wh, body.alert_id)
        if not case.get("case"):
            raise HTTPException(404, "unknown variance")
        c = case["case"]
        preview = (f"CFO decision on {c['message']} ({c['month']}): {body.decision}."
                   + (f" {body.note}" if body.note else "")
                   + (f" Actions: {'; '.join(a.get('action', '') + ' (' + a.get('owner', '') + ')' for a in body.actions)}." if body.actions else ""))
        payload = {"alert_id": body.alert_id, "decision": body.decision, "note": body.note, "actions": body.actions,
                   "evidence": {"actual": c["actual"], "budget": c["budget"], "variance_favorable": c["variance_favorable"],
                                "fy_forecast_variance": c["fy_forecast_variance"], "root_cause": case["root_cause"].get("summary"),
                                "reconciled": all(x["status"] in ("pass", "no check") for x in case["reconciliation_chain"])}}
        aid = state.propose(None, "variance_decision", body.alert_id, payload, preview)
        state.decide(aid, "approved", f"Decided: {body.decision}")
        return {"action_id": aid, "preview": preview}

    @app.get("/api/variance-decisions/{alert_id}")
    def variance_decisions(alert_id: str):
        out = []
        for a in state.actions():
            if a["kind"] == "variance_decision" and a["target_id"] == alert_id:
                payload = json.loads(a["payload"]) if isinstance(a["payload"], str) else a["payload"]
                out.append({"id": a["id"], "decision": payload["decision"], "note": payload.get("note"), "actions": payload.get("actions", []),
                            "decided_at": a["decided_at"].isoformat() if hasattr(a["decided_at"], "isoformat") else a["decided_at"],
                            "decided_by": a.get("decided_by"), "audit": state.audit(a["id"])})
        return out[::-1]

    @app.get("/api/control-queue")
    def control_queue():
        """The control queue with resolution status from the workspace: a budget variance is resolved once the CFO has
        recorded a decision; AP bills, reminders and cash fixes once their approval card is decided."""
        token = tools.FULL_ROWS.set(True)
        try:
            q = tools.get_control_queue(wh)
        finally:
            tools.FULL_ROWS.reset(token)
        decided = {}
        for a in state.actions():
            if a["status"] in ("approved", "rejected"):
                payload = json.loads(a["payload"]) if isinstance(a["payload"], str) else a["payload"]
                note = payload.get("decision") or a["status"]
                decided[a["target_id"]] = {"resolution": note, "resolved_at": str(a["decided_at"])[:16]}
        for item in q["rows"]:
            d = decided.get(item["reference"])
            item["status"] = "resolved" if d else "open"
            item["resolution"] = d["resolution"] if d else None
        q["resolved"] = sum(1 for i in q["rows"] if i["status"] == "resolved")
        return q

    @app.get("/api/audit")
    def audit():
        return state.audit()

    class DealBody(BaseModel):
        customer: str
        lines: list[dict]
        discount_pct: float = 0
        term_months: int = 12
        monthly_commit: float = 0
        payment_terms_days: int = 30
        sla: str = "standard"
        unlimited_usage: bool = False
        prepaid_credits: bool = False
        free_months: int = 0
        custom_terms: str | None = None

    @app.post("/api/deals/evaluate")
    def evaluate_deal(body: DealBody):
        from finance_os import dealdesk
        return dealdesk.evaluate(wh, body.model_dump())

    @app.post("/api/deals")
    def submit_deal(body: DealBody):
        from finance_os.app.actions import submit_deal as submit
        return submit(wh, state, None, **body.model_dump())

    @app.get("/api/deals")
    def list_deals():
        return [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in d.items()} for d in state.deals()]

    @app.get("/api/deals/{did}/quote.pdf")
    def deal_quote(did: str):
        from finance_os import dealdesk
        d = state.deal(did)
        if not d:
            raise HTTPException(404, "deal not found")
        path = dealdesk.quote_pdf(did, d["evaluation"], ROOT / "data" / "quotes")
        return FileResponse(path, media_type="application/pdf", filename=f"{did}.pdf")

    @app.get("/api/invoices/{ref}/pdf")
    def invoice_pdf(ref: str, download: bool = False):
        """The customer invoice as a PDF, rendered from the warehouse so it always matches the books."""
        from finance_os.reports import invoice_pdf as ip
        token = tools.FULL_ROWS.set(True)
        try:
            d = tools.get_invoice_detail(wh, ref)
        finally:
            tools.FULL_ROWS.reset(token)
        if not d.get("header"):
            raise HTTPException(404, f"no invoice {ref}")
        path = ip.render(d, ROOT / "data" / "invoices")
        return FileResponse(path, media_type="application/pdf", filename=f"{d['header']['invoice_ref']}.pdf",
                            content_disposition_type="attachment" if download else "inline")

    @app.get("/api/reports")
    def reports():
        from finance_os.reports import scheduled
        return {"schedule": scheduled.schedule(), "saved": scheduled.list_reports()}

    @app.get("/api/reports/{period}/{report_id}")
    def report(period: str, report_id: str):
        from finance_os.reports import scheduled
        if report_id not in scheduled.REPORTS or "/" in period or ".." in period:
            raise HTTPException(404, "no such report")
        path = scheduled.OUT / period / f"{report_id}.md"
        if not path.exists():
            raise HTTPException(404, "not generated")
        text = path.read_text(encoding="utf-8")
        if text.startswith("<!--"):  # the header comment (name, recipients) is for the file, not the page
            text = text.split("\n", 1)[1]
        return {"period": period, "report_id": report_id, "markdown": text}

    @app.post("/api/reports/{report_id}/run")
    def run_report(report_id: str):
        from finance_os.reports import scheduled
        if report_id not in scheduled.REPORTS:
            raise HTTPException(404, "no such report")
        return {"sent": scheduled.run(only=report_id, force=True)}

    @app.get("/api/financials.xlsx")
    def financials_xlsx(period: str = "month", periods: int = 12):
        from fastapi.responses import Response
        from finance_os.reports import workbook
        if period not in ("month", "quarter", "year"):
            raise HTTPException(422, "period must be month, quarter or year")
        data = workbook.build(wh, period, max(1, min(periods, 36)))
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="echo_labs_financials_{period}.xlsx"'})

    @app.get("/api/dataroom.zip")
    def dataroom():
        from fastapi.responses import Response
        from finance_os.reports import dataroom as dr
        data, month = dr.build(wh)
        return Response(data, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="echo_labs_data_room_{month}.zip"'})

    class AckBody(BaseModel):
        alert_key: str
        who: str | None = None

    @app.get("/api/alerts")
    def alerts(status: str | None = None):
        from finance_os import alerts as alert_log
        return [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in a.items()} for a in alert_log.list_alerts(status)]

    @app.post("/api/alerts/ack")
    def ack_alert(body: AckBody):
        from finance_os import alerts as alert_log
        if not alert_log.acknowledge(body.alert_key, body.who or "finance"):
            raise HTTPException(409, "alert is not open (already acknowledged or resolved)")
        return {"acknowledged": body.alert_key}

    @app.post("/api/data/{tool}")
    def data(tool: str, args: dict | None = None):
        """The workspace reads through the same read-only tools as the assistant, so both show the same numbers."""
        if tool not in tools.TOOLS:
            raise HTTPException(404, f"unknown tool {tool}")
        token = tools.FULL_ROWS.set(True)  # pages show every row; the 40-row cap is for the assistant's context
        try:
            return tools.run_tool(wh, tool, args or {})
        except TypeError as e:
            raise HTTPException(422, f"bad arguments: {e}")
        finally:
            tools.FULL_ROWS.reset(token)

    @app.post("/api/ml/retrain")
    def ml_retrain():
        """Retrain the four ML models on the current warehouse (seconds); the daily job also does this."""
        from finance_os import ml
        return {name: r["card"]["headline"] for name, r in ml.train_all(wh, log=lambda m: None).items()}

    @app.get("/api/workspace/overview")
    def overview():
        kpis = tools.get_kpis(wh)
        needs_you = {
            "ap_bills_to_review": len({r["doc_file"] for r in tools.get_ap_review_queue(wh)["rows"]}),
            "collections_on_hold": len(tools.get_collections_queue(wh)["on_hold"]),
            "pending_approvals": len(state.actions(status="pending")),
            "recon_failures": len(tools.get_reconciliation_status(wh)["failures"]),
        }
        return {"month": kpis["month"], "kpis": kpis["rows"], "needs_you": needs_you}

    return app
