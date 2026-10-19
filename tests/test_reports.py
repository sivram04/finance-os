"""Recurring reports: cadence rules, and every report builds from the warehouse."""
from datetime import date

import pytest

from finance_os.reports import scheduled


def test_cadences_decide_the_period_each_report_covers():
    closed = date(2026, 9, 1)
    assert scheduled.period_key("daily", date(2026, 10, 18), closed) == "2026-10-18"
    assert scheduled.period_key("weekly:mon", date(2026, 10, 19), closed) == "2026-W43"     # a Monday
    assert scheduled.period_key("weekly:mon", date(2026, 10, 18), closed) is None            # a Sunday
    assert scheduled.period_key("monthly:on_close", date(2026, 10, 18), closed) == "2026-09"  # once per closed month


@pytest.mark.skipif(not scheduled.WAREHOUSE.exists(), reason="build the warehouse first")
def test_every_report_builds():
    import duckdb
    con = duckdb.connect(str(scheduled.WAREHOUSE), read_only=True)
    try:
        for name, build in scheduled.REPORTS.items():
            text = build(con, date(2026, 10, 19))
            assert text.startswith("#") and "None" not in text.splitlines()[0], name
    finally:
        con.close()
