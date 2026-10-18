from decimal import Decimal

from generator.__main__ import generate, write_csvs


def test_same_seed_gives_identical_files(tmp_path):
    """NFR-2: deterministic for a given seed."""
    write_csvs(generate(), tmp_path / "a")
    write_csvs(generate(), tmp_path / "b")
    for f in (tmp_path / "a").iterdir():
        assert f.read_bytes() == (tmp_path / "b" / f.name).read_bytes(), f.name


def test_different_seed_changes_usage():
    assert generate(1)["usage_daily"] != generate(2)["usage_daily"]


def test_money_and_hours_are_decimal():
    """NFR-1: no floats."""
    t = generate()
    assert all(isinstance(p["list_price_per_hour"], Decimal) for p in t["products"])
    assert all(isinstance(u["audio_hours"], Decimal) for u in t["usage_daily"])


def test_segment_counts_match_config():
    import yaml
    from generator.__main__ import CONFIG
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    segs = [c["segment"] for c in generate()["customers"]]
    assert all(segs.count(s) == spec["count"] for s, spec in cfg["segments"].items())


def test_shared_gpu_jobs_have_no_customer_and_direct_jobs_do():
    jobs = generate()["gpu_jobs"]
    shared = [j for j in jobs if j["customer_id"] is None]
    assert shared and len(shared) < len(jobs)


def test_streaming_shift_anomaly_changes_mix_from_start_date():
    t = generate()
    a = t["anomaly_manifest"][0]
    after = [u for u in t["usage_daily"] if u["customer_id"] == a["entity_id"] and u["usage_date"] >= a["start_date"]]
    assert {u["product_id"] for u in after} == {"batch_pro", "stream"}
    stream_share = sum(u["audio_hours"] for u in after if u["product_id"] == "stream") / sum(u["audio_hours"] for u in after)
    assert abs(stream_share - Decimal("0.80")) < Decimal("0.01")


def test_vendor_bill_totals_equal_sum_of_lines():
    t = generate()
    by_bill = {}
    for line in t["vendor_bill_lines"]:
        by_bill[line["bill_id"]] = by_bill.get(line["bill_id"], Decimal(0)) + line["amount"]
    assert all(b["total_amount"] == by_bill[b["bill_id"]] for b in t["vendor_bills"])


def test_untagged_cluster_anomaly_adds_unlabeled_lines_for_each_day():
    t = generate()
    a = next(x for x in t["anomaly_manifest"] if x["kind"] == "untagged_gpu_cluster")
    days = {c["usage_date"] for c in t["cloud_costs_daily"] if c["label_team"] is None and "GPU" in c["sku"]}
    assert len(days) == 9 and min(days) == a["start_date"]


def test_every_journal_entry_balances():
    t = generate()
    totals = {}
    for l in t["journal_lines"]:
        d, c = totals.get(l["entry_id"], (0, 0))
        totals[l["entry_id"]] = (d + l["debit"], c + l["credit"])
    assert all(d == c for d, c in totals.values())


def test_headcount_ends_at_plan():
    import yaml
    from generator.__main__ import CONFIG
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    end = cfg["window"]["end"]
    active = [e for e in generate()["employees"]
              if e["hire_date"] <= end and (e["termination_date"] is None or e["termination_date"] > end)]
    assert len(active) == sum(p["end"] for p in cfg["headcount_plan"])


def test_no_usage_while_churned():
    from generator.entities.lifecycle import CustomerState
    t = generate()
    events = {}
    for e in t["lifecycle_events"]:
        events.setdefault(e["customer_id"], []).append(e)
    states = {cid: CustomerState(ev) for cid, ev in events.items()}
    assert not [u for u in t["usage_daily"] if u["customer_id"] in states and not states[u["customer_id"]].active(u["usage_date"])]


def test_story_customers_sign_up_before_their_events():
    t = generate()
    signup = {c["customer_id"]: c["signup_date"] for c in t["customers"]}
    scripted = [e for e in t["lifecycle_events"] if e["source"] == "scripted"]
    assert scripted and all(signup[e["customer_id"]] < e["event_date"] for e in scripted)
