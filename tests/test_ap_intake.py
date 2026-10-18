import yaml

from finance_os.generator.__main__ import CONFIG, generate
from finance_os.generator.documents.ap_bills import render_ap_pdfs
from finance_os.ingestion.ap_intake import text_extractor


def test_text_extractor_reads_every_layout_exactly(tmp_path):
    """One document per vendor layout, rendered and read back: every field must match the truth."""
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    t = generate()
    sample = {}
    for d in t["ap_document_truth"]:
        sample.setdefault(d["vendor_id"], d)
    docs = list(sample.values())
    lines = [l for l in t["ap_document_truth_lines"] if l["doc_file"] in {d["doc_file"] for d in docs}]
    render_ap_pdfs(cfg, docs, lines, tmp_path)
    for d in docs:
        r = text_extractor.extract(tmp_path / d["doc_file"])
        assert r["vendor_name"] == d["vendor_name"]
        assert r["vendor_invoice_number"] == d["vendor_invoice_number"]
        assert r["invoice_date"] == d["invoice_date"].isoformat()
        assert r["po_number"] == d["po_number"]
        assert r["total"] == d["total"]
        expected = [l for l in lines if l["doc_file"] == d["doc_file"]]
        assert [(l["amount"], l["quantity"]) for l in r["lines"]] == [(l["amount"], l["quantity"]) for l in expected]


def test_document_issues_are_injected_once_each():
    issues = [d["doc_issue"] for d in generate()["ap_document_truth"] if d["doc_issue"]]
    assert sorted(issues) == ["arithmetic_error", "duplicate_submission", "wrong_po"]


def test_openai_extractor_request_and_parsing(tmp_path, monkeypatch):
    """No network: the API call is mocked. Checks the request is a strict-schema call and that
    printed values come back as exact Decimals, untouched."""
    import io
    import json
    from decimal import Decimal

    from finance_os.ingestion.ap_intake import openai_extractor

    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    t = generate()
    doc = t["ap_document_truth"][0]
    lines = [l for l in t["ap_document_truth_lines"] if l["doc_file"] == doc["doc_file"]]
    render_ap_pdfs(cfg, [doc], lines, tmp_path)

    sent = {}
    reply = {"vendor_name": doc["vendor_name"], "vendor_invoice_number": doc["vendor_invoice_number"],
             "invoice_date": doc["invoice_date"].isoformat(), "po_number": None, "currency": "USD",
             "total": str(doc["total"]), "lines": [{"description": "x", "quantity": None, "amount": "1.10"}]}

    def fake_urlopen(req, timeout):
        sent["url"], sent["auth"], sent["body"] = req.full_url, req.headers["Authorization"], json.loads(req.data)
        payload = {"model": "test-model", "choices": [{"message": {"content": json.dumps(reply)}}],
                   "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(openai_extractor.urllib.request, "urlopen", fake_urlopen)
    r = openai_extractor.extract(tmp_path / doc["doc_file"])

    assert sent["url"] == "https://api.openai.com/v1/chat/completions"
    assert sent["auth"] == "Bearer test-key"
    assert sent["body"]["response_format"]["json_schema"]["strict"] is True
    assert doc["vendor_invoice_number"] in sent["body"]["messages"][1]["content"]
    assert r["total"] == doc["total"] and isinstance(r["total"], Decimal)
    assert r["lines"][0]["amount"] == Decimal("1.10")
    assert (r["model"], r["prompt_tokens"]) == ("test-model", 10)


def test_reminder_check_rejects_drafts_that_change_numbers():
    from finance_os.collections.draft_reminders import check, draft_template

    f = {"invoice_ref": "INV-EN-001-202606", "customer_id": "EN-001", "balance": "$30,335.85",
         "due_date": "2026-08-14", "days_past_due": 47, "tone": "firm"}
    subject, body, _ = draft_template(f)
    assert check(f, subject, body)
    assert not check(f, subject, body.replace("$30,335.85", "$30,335"))
    assert not check(f, subject.replace("INV-EN-001-202606", "the invoice"), body.replace("INV-EN-001-202606", "the invoice"))
