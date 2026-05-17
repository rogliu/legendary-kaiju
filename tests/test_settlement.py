"""Tests for Task 18: settlement scoring, pnl writing, and gate update.

Contract verified:
  - settle_day(station, climate_date, db_path, deps, series_ticker=...) -> dict
  - Returns dict with 'realized_max' and 'realized_usd' keys
  - Writes a pnl row: climate_date + realized_usd + mode (matching _realized_loss_today's query)
  - Updates gate status via set_gate_status
  - LookupError from official_daily_max -> returns "not_ready" result, no pnl/gate write
  - Gate calibration is real (CRPS vs uniform-climatology baseline, PIT KS test),
    not a hardcoded stub — proved by test_well_calibrated_history and
    test_miscalibrated_history_fails_calibration below.
"""
from kaiju.runner import settle_day, _compute_gate
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


# ---------------------------------------------------------------------------
# Gate-calibration discrimination tests (Fix D)
# ---------------------------------------------------------------------------
# These tests prove the gate's calibration criterion is data-driven, not a stub.
# They seed predictions and settlements directly into state, then call _compute_gate
# and assert: well-calibrated history can pass calibration; miscalibrated history fails.
#
# Design notes:
#   - GateCriteria defaults: min_days=30, min_trades=15.  We seed exactly 30 days so
#     insufficient-days is NOT the fail reason in either test.
#   - Positive pnl is seeded to avoid the "non-positive simulated pnl" gate failure.
#   - PIT check requires >= 5 points AND the KS test; with 30 sharp-centered days the
#     PIT values concentrate near the correct quantile range, but the test does not
#     depend on the PIT check passing/failing — it depends only on calibration.
#   - Both tests pass mode="shadow-paper" throughout.
# ---------------------------------------------------------------------------


def _seed_history(
    state: State,
    station: str,
    days_data: list[tuple[str, int, list[float], int]],
    mode: str = "shadow-paper",
) -> None:
    """Seed predictions, settlements, and pnl rows for a list of days.

    days_data: list of (climate_date, low_f, probs, realized_max).
    Each day gets a positive pnl row (1.0 USD) to avoid the non-positive-pnl gate fail.
    """
    for climate_date, low_f, probs, realized_max in days_data:
        state.record_prediction(station, climate_date, low_f, probs)
        state.record_settlement(climate_date, station, realized_max, mode)
        state.record_pnl(climate_date, 1.0, mode)  # positive pnl row


def test_well_calibrated_history_can_qualify_calibration(tmp_path):
    """A sharp PMF centered on the realized max each day produces low model CRPS,
    well below the uniform-baseline CRPS.  The gate's calibration criterion must NOT
    be the failure reason — demonstrating the criterion is real, not a stub.

    Setup: 30 days, each day realized_max=70.
      Prediction: low_f=69, probs=[0.01, 0.98, 0.01]  (mass on 69/70/71, nearly all at 70)
      Realized:   70 each day.
    Model CRPS per day is very small (< 0.1 for a near-delta PMF at the outcome).
    Uniform baseline spans [70,70] -> widened to [67,73] (7 bins) -> CRPS ~ several °F.
    So model CRPS << baseline CRPS and calibration criterion passes.
    """
    db = str(tmp_path / "s.sqlite")
    st = State(db)
    st.init_schema()

    station = "NYC"
    mode = "shadow-paper"
    realized_max = 70
    n_days = 30

    days_data = [
        (f"2026-01-{d:02d}", 69, [0.01, 0.98, 0.01], realized_max)
        for d in range(1, n_days + 1)
    ]
    _seed_history(st, station, days_data, mode=mode)

    result = _compute_gate(st, station, mode)

    # The gate may still fail due to other criteria (days/trades edge, PIT, drawdown,
    # fill_rate) — but it must NOT fail due to calibration.
    assert result.reason != "calibration not better than market", (
        f"Well-calibrated history must not fail calibration gate. Got: {result.reason}"
    )
    # Verify the reason is not a calibration stub side-effect.
    assert "0.25" not in result.reason and "0.26" not in result.reason, (
        f"Stub calibration constant found in gate reason: {result.reason}"
    )


def test_miscalibrated_history_fails_calibration(tmp_path):
    """A PMF that is always wrong (mass far from realized max) produces high model CRPS,
    at or above the uniform-baseline CRPS.  The gate must fail with the calibration reason.

    Setup: 30 days, each day realized_max=70.
      Prediction: low_f=50, probs=[1.0] * 1  (single spike at 50, far from 70)
      Realized:   70 each day.
    Model CRPS per day is large (~20 for a spike 20°F away from the outcome).
    Uniform baseline spans [70,70] -> widened to [67,73] (7 bins) -> CRPS ~ a few °F.
    So model CRPS >> baseline CRPS and calibration criterion fails.
    """
    db = str(tmp_path / "s.sqlite")
    st = State(db)
    st.init_schema()

    station = "NYC"
    mode = "shadow-paper"
    realized_max = 70
    n_days = 30

    # PMF spike at 50, realized max always 70: systematic 20°F miss.
    days_data = [
        (f"2026-02-{d:02d}", 50, [1.0], realized_max)
        for d in range(1, n_days + 1)
    ]
    _seed_history(st, station, days_data, mode=mode)

    result = _compute_gate(st, station, mode)

    # Must fail with the calibration reason — not a different reason.
    assert not result.qualified, "Miscalibrated history must not qualify"
    assert result.reason == "calibration not better than market", (
        f"Miscalibrated history must fail with calibration reason. Got: {result.reason!r}"
    )
