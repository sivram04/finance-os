"""Draft collection reminders for the top of the collections queue (FR-8.4). Nothing is ever sent.

    python -m finance_os.collections.draft_reminders [--backend template|openai] [--top 10]

Each draft is written to reports/collections/<invoice>.md and to raw_ar.collection_drafts with status
'pending_approval'; a person reviews, edits and sends it. Disputed invoices are never drafted.

The facts (customer, invoice, amount, due date, days overdue, tone) come from the warehouse. The template
backend fills a fixed letter per tone. The OpenAI backend writes the prose from those facts; afterwards the
draft is checked to contain the exact invoice number and balance as given, and is marked 'failed_check' if
not, so a model can never change a number in a customer-facing email (design AIR-1, AIR-2).
"""
import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from finance_os.ingestion.ap_intake.__main__ import load_dotenv
from finance_os.paths import ROOT

TEMPLATES = {
    "friendly": ("Reminder: invoice {invoice_ref} is past due",
                 "Hi {customer_id} team,\n\nA quick reminder that invoice {invoice_ref} for {balance} was due on "
                 "{due_date} and is now {days_past_due} days past due. A copy is attached. If it's already on its way, "
                 "thank you, and please ignore this note.\n\nBest,\nEcho Labs Accounts Receivable"),
    "firm": ("Second notice: invoice {invoice_ref} is {days_past_due} days past due",
             "Hello {customer_id} team,\n\nInvoice {invoice_ref} for {balance}, due {due_date}, remains unpaid and is "
             "now {days_past_due} days past due. Could you confirm a payment date by the end of this week?\n\n"
             "Thank you,\nEcho Labs Accounts Receivable"),
    "final": ("Final notice: invoice {invoice_ref}",
              "Hello {customer_id} team,\n\nThis is a final notice for invoice {invoice_ref} for {balance}, due "
              "{due_date} and now {days_past_due} days past due. Please arrange payment or contact us within 7 days; "
              "otherwise we will escalate to your account owner.\n\nRegards,\nEcho Labs Accounts Receivable"),
    "escalation": ("Account on hold review: invoice {invoice_ref}",
                   "Hello {customer_id} team,\n\nInvoice {invoice_ref} for {balance} is {days_past_due} days past due "
                   "(due {due_date}). Your account is being reviewed for a credit hold. Please contact us today to "
                   "resolve the balance.\n\nRegards,\nEcho Labs Finance"),
}

SYSTEM = ("You write short, professional accounts-receivable emails for Echo Labs. Use only the facts given. "
          "Copy the invoice number and the balance exactly as given; never compute, round or change any amount or "
          "date. Match the requested tone. Return JSON with 'subject' and 'body'.")


def _facts(row):
    invoice_ref, customer_id, balance, due_date, days_past_due, tone = row
    return {"invoice_ref": invoice_ref, "customer_id": customer_id, "balance": f"${balance:,.2f}",
            "due_date": due_date.isoformat(), "days_past_due": days_past_due, "tone": tone}


def draft_template(f):
    subject, body = TEMPLATES[f["tone"]]
    return subject.format(**f), body.format(**f), "template-v1"


def draft_openai(f):
    key = os.environ["OPENAI_API_KEY"]
    model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    schema = {"type": "object", "additionalProperties": False, "required": ["subject", "body"],
              "properties": {"subject": {"type": "string"}, "body": {"type": "string"}}}
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps({"model": model, "temperature": 0.3,
                         "messages": [{"role": "system", "content": SYSTEM},
                                      {"role": "user", "content": json.dumps(f)}],
                         "response_format": {"type": "json_schema",
                                             "json_schema": {"name": "reminder", "schema": schema, "strict": True}}}).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read())
    out = json.loads(payload["choices"][0]["message"]["content"])
    return out["subject"], out["body"], payload.get("model", model)


def check(f, subject, body):
    """The draft must quote the invoice number and balance exactly as the warehouse gave them."""
    text = subject + "\n" + body
    return f["invoice_ref"] in text and f["balance"] in text


def run(backend, top, db: Path, out_dir: Path):
    con = duckdb.connect(str(db))
    rows = con.execute("""
        select invoice_ref, customer_id, balance, due_date, days_past_due, reminder_tone
        from marts.fct_collections_queue
        where not is_disputed and reminder_tone is not null
        order by queue_rank
        limit ?""", [top]).fetchall()
    draft = {"template": draft_template, "openai": draft_openai}[backend]
    now = datetime.now(timezone.utc).replace(microsecond=0)
    out_dir.mkdir(parents=True, exist_ok=True)
    con.execute("CREATE SCHEMA IF NOT EXISTS raw_ar")
    con.execute("""CREATE TABLE IF NOT EXISTS raw_ar.collection_drafts (
        invoice_ref VARCHAR, backend VARCHAR, model VARCHAR, tone VARCHAR, subject VARCHAR, body VARCHAR,
        status VARCHAR, drafted_at TIMESTAMP, approved_by VARCHAR, sent_at TIMESTAMP)""")
    con.execute("DELETE FROM raw_ar.collection_drafts WHERE backend = ? AND status IN ('pending_approval', 'failed_check')",
                [backend])
    for row in rows:
        f = _facts(row)
        subject, body, model = draft(f)
        status = "pending_approval" if check(f, subject, body) else "failed_check"
        con.execute("INSERT INTO raw_ar.collection_drafts VALUES (?,?,?,?,?,?,?,?,NULL,NULL)",
                    [f["invoice_ref"], backend, model, f["tone"], subject, body, status, now])
        (out_dir / f"{f['invoice_ref']}.md").write_text(
            f"<!-- DRAFT ({status}) — not sent. Review, edit and send manually. -->\n"
            f"**To:** {f['customer_id']} accounts payable\n**Subject:** {subject}\n\n{body}\n", encoding="utf-8")
        print(f"{status:17} {f['invoice_ref']} ({f['tone']})")
    con.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--backend", choices=["template", "openai"], default="template")
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--db", default=str(ROOT / "data" / "finance_os.duckdb"))
    p.add_argument("--out", default=str(ROOT / "reports" / "collections"))
    a = p.parse_args()
    load_dotenv(ROOT / ".env")
    if a.backend == "openai" and not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set. Add it to .env or use --backend template.")
    run(a.backend, a.top, Path(a.db), Path(a.out))


if __name__ == "__main__":
    main()
