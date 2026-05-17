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
