"""Actions the assistant may *propose* (design §9.5). A proposal records a pending action with a preview;
nothing changes until the user approves it in the UI. These are the only state changes the assistant can
reach, and each one validates that its target exists before it is proposed.
"""
from finance_os.app.state import AppState
from finance_os.app.tools import Warehouse, _p


def _existing(state, cid, kind, target):
    for a in state.actions(status="pending", cid=cid):
        if a["kind"] == kind and a["target_id"] == target:
            return a
    return None


def _proposed(state, cid, kind, target, payload, preview):
    existing = _existing(state, cid, kind, target)
    aid = existing["id"] if existing else state.propose(cid, kind, target, payload, preview)
    return {"proposed_action_id": aid, "kind": kind, "target_id": target, "preview": preview,
            "status": "pending: shown to the user with Approve / Reject; not executed"}


def propose_ap_document_decision(wh: Warehouse, state: AppState, cid, doc_file, decision, reason):
    if doc_file.startswith("UP-"):  # a document uploaded in the chat
        from finance_os.app.documents import Documents
        up = Documents(state, wh).get(doc_file)
        if not up:
            return {"error": f"No uploaded document {doc_file}."}
        doc = [{"doc_file": doc_file, "vendor_id": up["vendor_id"] or up["fields"].get("vendor_name"),
                "vendor_invoice_number": up["fields"].get("vendor_invoice_number"), "total": up["fields"].get("total") or 0,
                "route": up["route"], "issues": [i["code"] for i in up["issues"]]}]
    else:
        doc = wh.query("""select doc_file, vendor_id, vendor_invoice_number, total, route, issues
                          from marts.fct_ap_documents where doc_file = ?""", [doc_file])
    if not doc:
        return {"error": f"No AP document {doc_file}. Use get_ap_review_queue to list documents."}
    d = doc[0]
    issues = ", ".join(d["issues"]) if d["issues"] else "none"
    preview = (f"{decision.title()} vendor bill {d['vendor_invoice_number']} from {d['vendor_id']} "
               f"for ${d['total']:,.2f} (open issues: {issues}). Reason: {reason}")
    return _proposed(state, cid, f"ap_{decision}", doc_file, {"decision": decision, "reason": reason, **d}, preview)


def propose_reminder_decision(wh: Warehouse, state: AppState, cid, invoice_ref, decision, reason):
    draft = wh.query("""select invoice_ref, backend, tone, subject, status from raw_ar.collection_drafts
                        where invoice_ref = ? order by drafted_at desc limit 1""", [invoice_ref])
    if not draft:
        return {"error": f"No reminder draft for {invoice_ref}. Drafts are created by the reminder drafter."}
    d = draft[0]
    if d["status"] != "pending_approval":
        return {"error": f"The draft for {invoice_ref} is '{d['status']}', not awaiting approval."}
    preview = f"{decision.title()} the {d['tone']} reminder for {invoice_ref}: \"{d['subject']}\". Reason: {reason}"
    return _proposed(state, cid, f"reminder_{decision}", invoice_ref, {"decision": decision, "reason": reason, **d}, preview)


def propose_cash_application_fix(wh: Warehouse, state: AppState, cid, payment_id, correct_invoice_ref, note):
    pay = wh.query("""select payment_id, customer_id, amount, remittance_ref, applied_ref
                      from staging.stg_erp__customer_payments where payment_id = ?""", [payment_id])
    if not pay:
        return {"error": f"No payment {payment_id}. Use get_ar_exceptions to list cash-application exceptions."}
    inv = wh.query("select invoice_ref, customer_id from marts.fct_ar_invoices where invoice_ref = ?", [correct_invoice_ref])
    if not inv:
        return {"error": f"No invoice {correct_invoice_ref}."}
    p = pay[0]
    if inv[0]["customer_id"] != p["customer_id"]:
        return {"error": f"{correct_invoice_ref} belongs to {inv[0]['customer_id']}, not {p['customer_id']}."}
    preview = (f"Re-apply payment {payment_id} (${p['amount']:,.2f} from {p['customer_id']}) from "
               f"{p['applied_ref']} to {correct_invoice_ref}. Note: {note}")
    return _proposed(state, cid, "cash_application_fix", payment_id,
                     {"correct_invoice_ref": correct_invoice_ref, "note": note, **p}, preview)


def submit_deal(wh: Warehouse, state: AppState, cid, customer, lines, discount_pct, term_months, monthly_commit,
                note="Submitted from the deal desk"):
    """Price the deal, store it, and route it: inside the guardrails it is approved by the rules (audited);
    outside them it becomes a pending approval card for Finance with the reasons."""
    from finance_os import dealdesk
    deal = {"customer": customer, "lines": lines, "discount_pct": discount_pct, "term_months": term_months,
            "monthly_commit": monthly_commit}
    ev = dealdesk.evaluate(wh, deal)
    if ev.get("error"):
        return ev
    did = state.save_deal(customer, deal, ev)
    preview = (f"Deal {did} for {customer}: {ev['discount_pct']:.1%} off, {ev['term_months']} months, "
               f"${ev['monthly_revenue']:,.2f}/month at {ev['gross_margin_pct']:.1%} gross margin. "
               + ("Inside all guardrails." if ev["route"] == "auto_approve" else "Needs Finance: " + "; ".join(ev["reasons"])))
    aid = state.propose(cid, "deal_approval", did, {"evaluation": ev, "note": note}, preview)
    state.link_deal_action(did, aid)
    if ev["route"] == "auto_approve":
        state.decide(aid, "approved", "auto-approved by the deal desk rules: inside every guardrail")
    return {"deal_id": did, "route": ev["route"], "reasons": ev["reasons"], "evaluation": ev,
            "status": "approved by the rules" if ev["route"] == "auto_approve" else "pending: approval card shown to Finance"}


def propose_commission_dispute(wh: Warehouse, state: AppState, cid, rep_id, month, customer_id, claim):
    """A rep disputes a statement line (FR-10.3): recorded as an approval card for Finance to resolve."""
    rows = wh.query("""select rep_id, month, commission_total from marts.fct_commission_statement_monthly
                       where rep_id = ? and month = ?::date""", [rep_id, f"{month}-01" if len(month) == 7 else month])
    if not rows:
        return {"error": f"No statement for {rep_id} in {month}. Use get_commissions to list statements."}
    preview = f"Commission dispute from {rep_id} for {month} on {customer_id}: {claim}"
    return _proposed(state, cid, "commission_dispute", f"{rep_id}/{month}/{customer_id}",
                     {"rep_id": rep_id, "month": month, "customer_id": customer_id, "claim": claim,
                      "statement_total": rows[0]["commission_total"]}, preview)


DECISION = {"type": "string", "enum": ["approve", "reject"]}
REASON = {"type": "string", "description": "One sentence the user will see on the approval card."}

DEAL_LINES = {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                        "properties": {"product_id": {"type": "string", "enum": ["batch_base", "batch_pro", "stream"]},
                                                       "hours_per_month": {"type": "number"}},
                                        "required": ["product_id", "hours_per_month"]}}
DEAL_PROPS = {"customer": {"type": "string"}, "lines": DEAL_LINES,
              "discount_pct": {"type": "number", "description": "0.15 = 15% off list"},
              "term_months": {"type": "integer"}, "monthly_commit": {"type": "number", "description": "Monthly minimum commit in $"}}

ACTIONS = {
    "propose_commission_dispute": (
        propose_commission_dispute,
        "Log a rep's dispute of a commission statement line (rep, month YYYY-MM, customer, what they claim) as an "
        "approval card for Finance; resolving it is the decision.",
        _p({"rep_id": {"type": "string"}, "month": {"type": "string"}, "customer_id": {"type": "string"},
            "claim": REASON}, ["rep_id", "month", "customer_id", "claim"])),
    "submit_deal": (
        submit_deal,
        "Submit a deal to the deal desk: prices it, checks guardrails, stores it, and either approves it by the rules "
        "or creates an approval card for Finance. Use price_deal first to check it.",
        _p(DEAL_PROPS, ["customer", "lines", "discount_pct", "term_months", "monthly_commit"])),
    "propose_ap_document_decision": (
        propose_ap_document_decision,
        "Propose approving or rejecting a vendor bill: an AP inbox file (e.g. AC-2025-0010.pdf) or a document uploaded "
        "in this chat (id UP-…). Creates an approval card; does not execute.",
        _p({"doc_file": {"type": "string"}, "decision": DECISION, "reason": REASON}, ["doc_file", "decision", "reason"])),
    "propose_reminder_decision": (
        propose_reminder_decision,
        "Propose approving or rejecting a drafted collection reminder. Creates an approval card; nothing is sent.",
        _p({"invoice_ref": {"type": "string"}, "decision": DECISION, "reason": REASON}, ["invoice_ref", "decision", "reason"])),
    "propose_cash_application_fix": (
        propose_cash_application_fix,
        "Propose re-applying a misapplied customer payment to the correct invoice. Creates an approval card.",
        _p({"payment_id": {"type": "string"}, "correct_invoice_ref": {"type": "string"}, "note": REASON},
           ["payment_id", "correct_invoice_ref", "note"])),
}


def action_specs():
    return [{"type": "function", "function": {"name": n, "description": d, "parameters": p}}
            for n, (_, d, p) in ACTIONS.items()]
