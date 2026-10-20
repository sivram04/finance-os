from finance_os.reports.build_metric_catalog import DOC, FIELDS, SEED, load, render_doc, render_seed


def test_every_metric_has_all_fields():
    for m in load():
        derived = {"threshold_rule", "recon_checks"}  # built from threshold / recon_checks (a list, may be empty)
        missing = [f for f in FIELDS if f not in derived and not m.get(f)]
        assert not missing, (m.get("name"), missing)
        assert {"basis", "better", "amber", "red"} <= set(m["threshold"]), m["name"]
        assert "recon_checks" in m and "decision_amber" not in m, m["name"]  # no canned actions
        assert m["status"] in ("MEASURED", "ASSUMED")


def test_generated_files_are_up_to_date():
    """Run `python -m finance_os.reports.build_metric_catalog` if this fails."""
    metrics = load()
    assert SEED.read_text(encoding="utf-8") == render_seed(metrics)
    assert DOC.read_text(encoding="utf-8") == render_doc(metrics)
