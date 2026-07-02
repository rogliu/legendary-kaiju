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
import pytest
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


# ---------------------------------------------------------------------------
# Fix 1 — idempotency: re-run must not clobber real PnL with 0.0
# ---------------------------------------------------------------------------


def test_settle_day_rerun_is_idempotent(tmp_path):
    """settle_day called a second time for the same (climate_date, station) must NOT
    recompute realized_usd from (now-cleared) positions and clobber the persisted PnL.

    First run: position held → realized_usd is non-zero.
    After first run: positions cleared (simulate cron / position-manager clear).
    Second run: same date → should return already_settled=True, preserved realized_usd.
    """
    import sqlite3

    db = str(tmp_path / "idem.sqlite")
    st = State(db)
    st.init_schema()

    station = "NYC"
    climate_date = "2026-05-17"
    series_ticker = "KXHIGHNY"
    mode = "shadow-paper"

    # Seed a prediction and a position that pays out.
    st.record_prediction(station, climate_date, 65, [0.0, 1.0, 0.0])
    # Position: bought 5 yes contracts on B66 (the winning bucket) at 40¢.
    # Official max=66 → in-bucket → payoff 100¢ → pnl = 5*(100-40)/100 = 3.0 USD.
    st.upsert_position("KXHIGHNY-26MAY17-B66", "yes", 5, 40, climate_date)

    class DepsWith66:
        def official_daily_max(self, *a, **kw) -> int:
            return 66

    # --- First settlement run ---
    res1 = settle_day(
        station=station,
        climate_date=climate_date,
        db_path=db,
        deps=DepsWith66(),
        series_ticker=series_ticker,
        mode=mode,
    )
    assert res1["realized_max"] == 66
    assert res1["realized_usd"] == pytest.approx(3.0)
    assert res1.get("already_settled") is None  # first run: no flag

    # Verify pnl row is written with the real value.
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT realized_usd FROM pnl WHERE climate_date=? AND mode=?",
        (climate_date, mode),
    ).fetchone()
    assert row is not None
    assert row[0] == pytest.approx(3.0)

    # Clear positions (simulates PositionManager.clear or end-of-day cleanup).
    # Direct delete simulates any external clearing of positions.
    conn.execute("DELETE FROM positions")
    conn.commit()
    conn.close()

    # --- Second settlement run (re-run with no positions remaining) ---
    res2 = settle_day(
        station=station,
        climate_date=climate_date,
        db_path=db,
        deps=DepsWith66(),
        series_ticker=series_ticker,
        mode=mode,
    )
    assert res2["already_settled"] is True, "Re-run must signal already_settled"
    assert res2["realized_max"] == 66, "Persisted realized_max must be returned"
    assert res2["realized_usd"] == pytest.approx(3.0), (
        "Re-run must NOT clobber realized_usd with 0.0 (positions were cleared)"
    )

    # Verify the pnl row in the database is STILL the real value.
    conn2 = sqlite3.connect(db)
    row2 = conn2.execute(
        "SELECT realized_usd FROM pnl WHERE climate_date=? AND mode=?",
        (climate_date, mode),
    ).fetchone()
    assert row2 is not None
    assert row2[0] == pytest.approx(3.0), (
        "DB pnl row must preserve real realized_usd after re-run with cleared positions"
    )
    conn2.close()


# ---------------------------------------------------------------------------
# Fix 2 — end-to-end gate qualifiability: a genuinely good model must qualify
# ---------------------------------------------------------------------------


def test_settle_day_includes_roundtrip_pnl(tmp_path):
    """Task 0003: a buy fill then a sell fill at a better price yields positive
    realized round-trip PnL in settle_day's realized_usd."""
    db = str(tmp_path / "rt.sqlite")
    st = State(db)
    st.init_schema()
    market = "KXHIGHNY-26MAY17-B65"
    # Round-trip: bought 10 @ 40, sold 10 @ 55 -> +$1.50; position fully closed.
    st.record_order("b1", market, "yes", 40, 10, "shadow-paper", action="buy")
    st.record_order("s1", market, "yes", 55, 10, "shadow-paper", action="sell")
    st.record_fill("b1", market, 40, 10)
    st.record_fill("s1", market, 55, 10)
    st.upsert_position(market, "yes", 0, 40, "2026-05-17")  # closed by the round-trip
    res = settle_day(
        station="NYC", climate_date="2026-05-17", db_path=db,
        deps=Deps(), series_ticker="KXHIGHNY", mode="shadow-paper",
    )
    # Held-to-settlement on a count-0 position = 0; all PnL is the round-trip.
    assert res["realized_usd"] == pytest.approx(1.50)


def test_settle_day_roundtrip_is_distinct_from_held(tmp_path):
    """Round-trip PnL ADDS to held-to-settlement, on a separate market."""
    db = str(tmp_path / "rt2.sqlite")
    st = State(db)
    st.init_schema()
    st.record_prediction("NYC", "2026-05-17", 64, [0.2, 0.6, 0.2])
    held = "KXHIGHNY-26MAY17-B66"  # held to settlement; official max 66 -> in bucket
    st.upsert_position(held, "yes", 5, 40, "2026-05-17")  # 5*(100-40)/100 = $3.00
    rt = "KXHIGHNY-26MAY17-B70"  # round-tripped and closed
    st.record_order("b1", rt, "yes", 30, 4, "shadow-paper", action="buy")
    st.record_order("s1", rt, "yes", 50, 4, "shadow-paper", action="sell")
    st.record_fill("b1", rt, 30, 4)
    st.record_fill("s1", rt, 50, 4)
    st.upsert_position(rt, "yes", 0, 30, "2026-05-17")
    res = settle_day(
        station="NYC", climate_date="2026-05-17", db_path=db,
        deps=Deps(), series_ticker="KXHIGHNY", mode="shadow-paper",
    )
    # held $3.00 + round-trip 4*(50-30)/100 = $0.80 -> $3.80
    assert res["realized_usd"] == pytest.approx(3.80)


def test_settle_day_partial_roundtrip_plus_held_no_double_count(tmp_path):
    """A partial exit: the closed portion realizes round-trip PnL, the remainder
    is held to settlement — the two never overlap (task 0005 left count = bought-sold)."""
    db = str(tmp_path / "rt3.sqlite")
    st = State(db)
    st.init_schema()
    st.record_prediction("NYC", "2026-05-17", 64, [0.2, 0.6, 0.2])
    market = "KXHIGHNY-26MAY17-B66"  # official max 66 -> in bucket
    # Bought 10 @ 40, sold 4 @ 55 -> closed 4 ($0.60), 6 held @ 40.
    st.record_order("b1", market, "yes", 40, 10, "shadow-paper", action="buy")
    st.record_order("s1", market, "yes", 55, 4, "shadow-paper", action="sell")
    st.record_fill("b1", market, 40, 10)
    st.record_fill("s1", market, 55, 4)
    st.upsert_position(market, "yes", 6, 40, "2026-05-17")  # 0005 reduced 10 -> 6
    res = settle_day(
        station="NYC", climate_date="2026-05-17", db_path=db,
        deps=Deps(), series_ticker="KXHIGHNY", mode="shadow-paper",
    )
    # held 6*(100-40)/100 = 3.60 ; round-trip 4*(55-40)/100 = 0.60 -> 4.20
    assert res["realized_usd"] == pytest.approx(4.20)


def test_settle_day_no_fills_held_to_settlement_unchanged(tmp_path):
    """Held-to-settlement scoring is unchanged when there are no round-trip fills."""
    db = str(tmp_path / "rt4.sqlite")
    st = State(db)
    st.init_schema()
    st.record_prediction("NYC", "2026-05-17", 64, [0.2, 0.6, 0.2])
    st.upsert_position("KXHIGHNY-26MAY17-B66", "yes", 5, 40, "2026-05-17")
    res = settle_day(
        station="NYC", climate_date="2026-05-17", db_path=db,
        deps=Deps(), series_ticker="KXHIGHNY", mode="shadow-paper",
    )
    assert res["realized_usd"] == pytest.approx(3.0)  # held only, nothing added


def test_settle_day_roundtrip_scoped_to_day(tmp_path):
    """A round-trip on another day's market must not leak into this day's pnl."""
    db = str(tmp_path / "rt5.sqlite")
    st = State(db)
    st.init_schema()
    other = "KXHIGHNY-26MAY18-B65"  # a DIFFERENT climate day
    st.record_order("b1", other, "yes", 40, 10, "shadow-paper", action="buy")
    st.record_order("s1", other, "yes", 55, 10, "shadow-paper", action="sell")
    st.record_fill("b1", other, 40, 10)
    st.record_fill("s1", other, 55, 10)
    res = settle_day(
        station="NYC", climate_date="2026-05-17", db_path=db,
        deps=Deps(), series_ticker="KXHIGHNY", mode="shadow-paper",
    )
    assert res["realized_usd"] == pytest.approx(0.0)  # 26MAY18 round-trip excluded


def test_settle_day_roundtrip_idempotent(tmp_path):
    """Re-running settle preserves the round-trip-inclusive pnl, never re-adds it (B5)."""
    db = str(tmp_path / "rt6.sqlite")
    st = State(db)
    st.init_schema()
    market = "KXHIGHNY-26MAY17-B65"
    st.record_order("b1", market, "yes", 40, 10, "shadow-paper", action="buy")
    st.record_order("s1", market, "yes", 55, 10, "shadow-paper", action="sell")
    st.record_fill("b1", market, 40, 10)
    st.record_fill("s1", market, 55, 10)
    res1 = settle_day(
        station="NYC", climate_date="2026-05-17", db_path=db,
        deps=Deps(), series_ticker="KXHIGHNY", mode="shadow-paper",
    )
    assert res1["realized_usd"] == pytest.approx(1.50)
    res2 = settle_day(
        station="NYC", climate_date="2026-05-17", db_path=db,
        deps=Deps(), series_ticker="KXHIGHNY", mode="shadow-paper",
    )
    assert res2["already_settled"] is True
    assert res2["realized_usd"] == pytest.approx(1.50)  # preserved, not 3.00


def test_well_calibrated_history_qualifies_end_to_end(tmp_path):
    """Prove the gate is passable by a realistic well-calibrated history.

    Construction (deterministic, seeded by index — not random):
    - 35 climate_dates (> 30 required minimum).
    - Varied true centers cycling through 60..79°F.
    - Wide Gaussian PMF (sigma=3, 15 bins) centered at each day's center so the
      model is reasonably sharp relative to the uniform baseline.
    - realized_max chosen via inverse-CDF at quasi-uniform fraction u_d=(d+0.5)/N:
      this makes the empirical PIT ≈ uniform by construction so KS p >> 0.05.
    - All pnl rows set to +1.0 USD (positive, zero drawdown) so the financial
      criteria pass trivially.

    This test asserts qualified == True — it must FAIL if the gate's criteria
    cannot be met by a realistic well-calibrated model (that would be a gate defect).
    """
    import math as _math

    db = str(tmp_path / "e2e.sqlite")
    st = State(db)
    st.init_schema()

    station = "NYC"
    mode = "shadow-paper"
    N = 35

    def _gaussian_probs_wide(center: int, sigma: float = 3.0) -> tuple[int, list[float]]:
        """Return (low_f, probs) for a 15-bin discretized Gaussian PMF."""
        low_f = center - 7
        temps = list(range(low_f, low_f + 15))
        raw = [_math.exp(-((t - center) ** 2) / (2 * sigma ** 2)) for t in temps]
        total = sum(raw)
        return low_f, [r / total for r in raw]

    def _icdf_realized_max(center: int, u: float) -> int:
        """Return the realized_max where CDF first reaches u (inverse-CDF sampling)."""
        low_f, probs = _gaussian_probs_wide(center)
        temps = list(range(low_f, low_f + 15))
        cdf = 0.0
        for t, p in zip(temps, probs):
            cdf += p
            if cdf >= u:
                return t
        return temps[-1]  # fallback: top bin

    # Build 35 days of paired predictions and settlements.
    for d in range(N):
        # Varied centers: cycle through 60, 61, ..., 79 (20 distinct values).
        center = 60 + (d * 20 // N)
        low_f, probs = _gaussian_probs_wide(center)
        # Quasi-uniform quantile for day d ensures empirical PIT ≈ uniform.
        u_d = (d + 0.5) / N
        realized_max = _icdf_realized_max(center, u_d)
        # Dates: 2026-03-01 .. 2026-04-04 (35 days)
        day_of_month = d + 1  # 1..35
        if day_of_month <= 31:
            date_str = f"2026-03-{day_of_month:02d}"
        else:
            date_str = f"2026-04-{(day_of_month - 31):02d}"
        st.record_prediction(station, date_str, low_f, probs)
        st.record_settlement(date_str, station, realized_max, mode)
        st.record_pnl(date_str, 1.0, mode)  # positive, no drawdown

    result = _compute_gate(st, station, mode)

    assert result.qualified, (
        f"A well-calibrated history with varied centers and inverse-CDF PIT "
        f"construction MUST qualify the gate. Got reason: {result.reason!r}. "
        f"If this assertion fails, there is a gate-design defect: a realistically "
        f"good model cannot pass the promotion gate."
    )
