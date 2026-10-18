from finance_os.reports.build_metric_catalog import DOC, FIELDS, SEED, load, render_doc, render_seed


def test_every_metric_has_all_fields():
    for m in load():
        missing = [f for f in FIELDS if not m.get(f)]
        assert not missing, (m.get("name"), missing)
        assert m["status"] in ("MEASURED", "ASSUMED")


def test_generated_files_are_up_to_date():
    """Run `python -m finance_os.reports.build_metric_catalog` if this fails."""
    metrics = load()
    assert SEED.read_text(encoding="utf-8") == render_seed(metrics)
    assert DOC.read_text(encoding="utf-8") == render_doc(metrics)
