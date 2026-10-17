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


def test_segment_counts_match_design():
    segs = [c["segment"] for c in generate()["customers"]]
    assert (segs.count("self_serve"), segs.count("mid_market"), segs.count("enterprise")) == (25, 11, 4)


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
