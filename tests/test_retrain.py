"""Tests for Task 19: calibration retrain job.

PMF construction note:
    low_f=med-1, probs=[0.2, 0.6, 0.2]
    cumsum at T=med-1: 0.2  (<0.5 → not median)
    cumsum at T=med:   0.8  (>=0.5 → median = med  ✓)
    So the PMF [0.2, 0.6, 0.2] with low_f=med-1 yields median==med
    under the definition: smallest T where cumsum >= 0.5.
"""

from kaiju.runner import retrain_calibration
from kaiju.state import State


def test_retrain_fits_and_persists_calibration(tmp_path):
    db = str(tmp_path / "s.sqlite")
    st = State(db)
    st.init_schema()
    # 4 days: stored prediction PMFs + persisted realized maxes (settlements)
    # forecast median 60/65/70/55 ; realized 57/62/67/52  (consistent +3 warm bias)
    days = [
        ("2026-04-01", 60, 57),
        ("2026-04-02", 65, 62),
        ("2026-04-03", 70, 67),
        ("2026-04-04", 55, 52),
    ]
    for d, med, real in days:
        # build a PMF whose median == med: low_f=med-1, probs=[0.2,0.6,0.2] -> median = med
        st.record_prediction("NYC", d, med - 1, [0.2, 0.6, 0.2])
        st.record_settlement(d, "NYC", real, "shadow-paper")
    cal = retrain_calibration(station="NYC", db_path=db)
    assert cal.n_samples == 4
    assert cal.bias < 0.0  # forecast medians run ~+3 warm vs realized -> negative bias correction
    got = st.get_calibration("NYC")
    assert got is not None and got["n"] == 4 and abs(got["bias"] - cal.bias) < 1e-9


def test_retrain_no_data_returns_identity_and_persists_nothingbad(tmp_path):
    db = str(tmp_path / "s.sqlite")
    st = State(db)
    st.init_schema()
    cal = retrain_calibration(station="NYC", db_path=db)
    assert cal.n_samples == 0 and cal.bias == 0.0 and cal.spread_scale == 1.0
