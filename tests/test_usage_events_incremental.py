"""The morning job appends only new days of usage events; appending must give exactly what a full rebuild gives,
and changed history must trigger a full rebuild instead of keeping stale days."""
from datetime import date

import duckdb
import yaml

from finance_os.generator.__main__ import CONFIG
from finance_os.generator.high_volume.__main__ import run_duckdb
from finance_os.paths import ROOT

PARAMS = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["api_requests"]
SUM = "select count(*), sum(latency_ms), count(distinct request_id) from raw_usage.api_requests"


def _drivers(db, through):
    con = duckdb.connect(str(db))
    con.execute(f"attach '{(ROOT / 'data' / 'finance_os.duckdb').as_posix()}' as src (read_only)")
    con.execute("create schema raw_synth")
    for t in ("products", "customers"):
        con.execute(f"create table raw_synth.{t} as select * from src.raw_synth.{t}")
    con.execute("create table raw_synth.usage_daily as select * from src.raw_synth.usage_daily "
                "where usage_date between date '2026-09-01' and ? and customer_id like 'MM-%'", [through])
    con.close()


def test_appending_a_day_equals_a_full_rebuild(tmp_path):
    a, b = tmp_path / "a.duckdb", tmp_path / "b.duckdb"
    _drivers(a, date(2026, 9, 3))
    assert run_duckdb(PARAMS, a)["mode"] == "rebuilt"
    con = duckdb.connect(str(a))
    con.execute("insert into raw_synth.usage_daily select * from raw_synth.usage_daily where false")  # schema check
    con.execute(f"attach '{(ROOT / 'data' / 'finance_os.duckdb').as_posix()}' as src (read_only)")
    con.execute("insert into raw_synth.usage_daily select * from src.raw_synth.usage_daily "
                "where usage_date = date '2026-09-04' and customer_id like 'MM-%'")
    con.close()
    stats = run_duckdb(PARAMS, a)
    assert stats["mode"] == "appended" and stats["days"] == 1
    _drivers(b, date(2026, 9, 4))
    run_duckdb(PARAMS, b, full=True)
    ca, cb = duckdb.connect(str(a)), duckdb.connect(str(b))
    assert ca.execute(SUM).fetchone() == cb.execute(SUM).fetchone()


def test_changed_history_forces_a_rebuild(tmp_path):
    a = tmp_path / "a.duckdb"
    _drivers(a, date(2026, 9, 3))
    run_duckdb(PARAMS, a)
    con = duckdb.connect(str(a))
    con.execute("update raw_synth.usage_daily set audio_hours = audio_hours * 2 where usage_date = date '2026-09-01'")
    con.close()
    assert run_duckdb(PARAMS, a)["mode"] == "rebuilt"
