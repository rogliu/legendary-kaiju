import pytest
from kaiju.types import TempPMF
from kaiju.model.nowcast import nowcast_pmf

def test_running_max_left_truncates():
    base = TempPMF.from_probs(60, [0.2,0.2,0.2,0.2,0.2])  # 60..64
    out = nowcast_pmf(base, observed_max_f=62, minutes_past_peak=-120, remaining_forecast_max_f=70)
    assert out.prob_interval(None, 61) == 0.0
    assert pytest.approx(out.probs.sum()) == 1.0
    assert out.prob_interval(62, None) == pytest.approx(1.0)

def test_post_peak_collapses_upside():
    base = TempPMF.from_probs(60, [0.1,0.1,0.2,0.3,0.3])  # 60..64
    out = nowcast_pmf(base, observed_max_f=63, minutes_past_peak=120, remaining_forecast_max_f=63)
    assert out.prob_at(63) == pytest.approx(1.0)

def test_pre_peak_keeps_upside_capped_at_remaining_forecast():
    base = TempPMF.from_probs(60, [0.2,0.2,0.2,0.2,0.2])
    out = nowcast_pmf(base, observed_max_f=61, minutes_past_peak=-60, remaining_forecast_max_f=63)
    assert out.prob_interval(64, None) == 0.0
    assert out.prob_interval(61, 63) == pytest.approx(1.0)

def test_observation_outside_support_degenerate_point_mass():
    base = TempPMF.from_probs(60, [0.5,0.5])  # 60,61
    out = nowcast_pmf(base, observed_max_f=80, minutes_past_peak=200, remaining_forecast_max_f=80)
    assert out.prob_at(80) == pytest.approx(1.0)
