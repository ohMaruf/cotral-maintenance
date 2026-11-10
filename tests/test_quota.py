from datetime import UTC, datetime

from cotral_maintenance.explorer.quota import MonthlyLedger

NOV = datetime(2026, 11, 9, tzinfo=UTC)
DEC = datetime(2026, 12, 1, tzinfo=UTC)


def test_the_free_tier_is_counted_per_month_with_a_margin(tmp_path):
    ledger = MonthlyLedger(tmp_path / "usage.json", free={"static": 100, "tiles": 1000}, margin=0.1)
    assert ledger.remaining(NOV).covers(14, 42)
    ledger.add("f1_run", static=80, tiles=500, now=NOV)
    left = ledger.remaining(NOV)
    assert (left.static, left.tiles) == (10, 400) and not left.covers(14, 42)
    assert ledger.remaining(DEC).covers(14, 42)  # a new month starts again


def test_the_ledger_persists(tmp_path):
    MonthlyLedger(tmp_path / "usage.json").add("f1_run", static=3, tiles=2, now=NOV)
    again = MonthlyLedger(tmp_path / "usage.json")
    assert again.used("2026-11") == {"static": 3, "tiles": 2}
    assert again.data["2026-11"]["runs"] == [{"run": "f1_run", "static": 3, "tiles": 2}]
