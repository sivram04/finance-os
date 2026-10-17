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
