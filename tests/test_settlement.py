"""Tests for Task 18: settlement scoring, pnl writing, and gate update.

Contract verified:
  - settle_day(station, climate_date, db_path, deps, series_ticker=...) -> dict
  - Returns dict with 'realized_max' and 'realized_usd' keys
  - Writes a pnl row: climate_date + realized_usd + mode (matching _realized_loss_today's query)
  - Updates gate status via set_gate_status
  - LookupError from official_daily_max -> returns "not_ready" result, no pnl/gate write
"""
from kaiju.runner import settle_day
from kaiju.state import State


class Deps:
    def official_daily_max(self, *args, **kwargs) -> int:
        return 66          # injected (real = IEMClient)


class DepsNotReady:
    def official_daily_max(self, *args, **kwargs) -> int:
        raise LookupError("data not yet available")


def test_settles_positions_writes_pnl_and_updates_gate(tmp_path):
    db = str(tmp_path / "s.sqlite")
    st = State(db)
    st.init_schema()
    # a held-to-settlement position: bought 2 'yes' @ 40c on the 65-66 bucket
    st.record_prediction("NYC", "2026-05-17", 64, [0.2, 0.6, 0.2])
    st.upsert_position("KXHIGHNY-26MAY17-B65", "yes", 2, 40, "2026-05-17")
    res = settle_day(
        station="NYC",
        climate_date="2026-05-17",
        db_path=db,
        deps=Deps(),
        series_ticker="KXHIGHNY",
    )
    assert res["realized_max"] == 66
    assert "realized_usd" in res
    # pnl row written so RiskGate daily-loss is no longer inert
    import sqlite3
    c = sqlite3.connect(db)
    row = c.execute(
        "SELECT realized_usd FROM pnl WHERE climate_date=?", ("2026-05-17",)
    ).fetchone()
    assert row is not None
    assert st.get_gate_status() is not None


def test_not_ready_returns_no_pnl_write(tmp_path):
    """LookupError from official_daily_max must return 'not_ready', no pnl/gate write."""
    db = str(tmp_path / "s.sqlite")
    st = State(db)
    st.init_schema()
    st.record_prediction("NYC", "2026-05-17", 64, [0.2, 0.6, 0.2])

    res = settle_day(
        station="NYC",
        climate_date="2026-05-17",
        db_path=db,
        deps=DepsNotReady(),
        series_ticker="KXHIGHNY",
    )
    assert res.get("status") == "not_ready"
    assert "realized_usd" not in res
    # No pnl row written
    import sqlite3
    c = sqlite3.connect(db)
    row = c.execute(
        "SELECT realized_usd FROM pnl WHERE climate_date=?", ("2026-05-17",)
    ).fetchone()
    assert row is None
    # No gate status updated
    assert st.get_gate_status() is None


def test_pnl_columns_match_realized_loss_query(tmp_path):
    """Verify pnl row columns match _realized_loss_today's query (climate_date + mode)."""
    db = str(tmp_path / "s.sqlite")
    st = State(db)
    st.init_schema()
    st.record_prediction("NYC", "2026-05-17", 64, [0.2, 0.6, 0.2])

    res = settle_day(
        station="NYC",
        climate_date="2026-05-17",
        db_path=db,
        deps=Deps(),
        series_ticker="KXHIGHNY",
        mode="shadow-paper",
    )
    assert "realized_usd" in res

    # _realized_loss_today queries: SELECT realized_usd FROM pnl WHERE climate_date=? AND mode=?
    import sqlite3
    c = sqlite3.connect(db)
    row = c.execute(
        "SELECT realized_usd FROM pnl WHERE climate_date=? AND mode=?",
        ("2026-05-17", "shadow-paper"),
    ).fetchone()
    assert row is not None, "pnl row must be queryable by climate_date AND mode"
