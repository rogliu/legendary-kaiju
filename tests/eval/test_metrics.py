import pytest
from kaiju.types import TempPMF
from kaiju.eval.metrics import brier_score, crps_pmf, pit_value, roundtrip_pnl_stats


def test_brier_and_crps_and_pit():
    assert brier_score([1.0], [1]) == 0.0
    assert crps_pmf(TempPMF.from_probs(70, [1.0]), 70) == pytest.approx(0.0)
    assert 0.0 <= pit_value(TempPMF.from_probs(60, [0.2, 0.3, 0.5]), 61) <= 1.0


def test_roundtrip_pnl_stats():
    s = roundtrip_pnl_stats([{"pnl_usd": 2.0, "exited": True}, {"pnl_usd": -1.0, "exited": False}])
    assert s["net_pnl_usd"] == pytest.approx(1.0)
    assert s["fill_rate"] == pytest.approx(0.5)
    assert s["n"] == 2


def test_empty_trades_is_failsafe_zero_fill():
    s = roundtrip_pnl_stats([])
    assert s["n"] == 0 and s["net_pnl_usd"] == 0.0 and s["fill_rate"] == 0.0

def test_pit_below_and_above_support():
    pmf = TempPMF.from_probs(60, [0.5, 0.5])  # 60,61
    assert pit_value(pmf, 50) == 0.0
    assert pit_value(pmf, 99) == 1.0

def test_crps_zero_outside_support_is_finite_and_saturates():
    pmf = TempPMF.from_probs(68, [0.2, 0.2, 0.2, 0.2, 0.2])  # 68..72
    import math as _m
    a = crps_pmf(pmf, 999)
    b = crps_pmf(pmf, 73)
    assert _m.isfinite(a) and _m.isfinite(b) and a == b   # saturates (documented)
