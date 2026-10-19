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

    @app.get("/api/audit")
    def audit():
        return state.audit()

    class DealBody(BaseModel):
        customer: str
        lines: list[dict]
        discount_pct: float = 0
        term_months: int = 12
        monthly_commit: float = 0

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
