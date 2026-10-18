import yaml

from generator.__main__ import CONFIG, generate
from generator.documents.ap_bills import render_ap_pdfs
from ingestion.ap_intake import text_extractor


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
