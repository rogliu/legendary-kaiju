import pytest
from kaiju.types import TempPMF
from kaiju.model.calibration import fit_calibration, apply_calibration, CalibrationParams


def test_bias_is_shrunk_when_few_samples():
    fc_medians = [60.0, 65.0, 70.0]
    realized   = [57, 62, 67]
    cal = fit_calibration(fc_medians, realized, min_samples=20)
    assert -3.0 < cal.bias < 0.0
    assert cal.n_samples == 3


def test_apply_shifts_pmf_by_bias_and_scales_spread():
    pmf = TempPMF.from_probs(60, [0.25, 0.5, 0.25])
    cal = CalibrationParams(bias=-1.0, spread_scale=1.0, n_samples=50)
    out = apply_calibration(pmf, cal)
    assert pytest.approx(out.probs.sum()) == 1.0
    assert out.prob_interval(None, 60) > pmf.prob_interval(None, 60)


def test_empty_history_is_identity():
    cal = fit_calibration([], [], min_samples=20)
    assert cal.bias == 0.0 and cal.spread_scale == 1.0 and cal.n_samples == 0


def test_mismatched_lengths_raise():
    with pytest.raises(ValueError):
        fit_calibration([60.0], [62.0, 67.0, 70.0], min_samples=5)


def test_zero_forecast_variance_is_bounded_identity_scale():
    # constant forecast median, varying obs: std(fc)=0 -> scale must be 1.0, NOT millions
    cal = fit_calibration([62.0]*10, [60,61,62,63,64,65,66,67,68,69], min_samples=1)
    assert cal.spread_scale == pytest.approx(1.0)
    assert 0.5 <= cal.spread_scale <= 3.0


def test_apply_conserves_mass_for_spread_scale_2_and_half():
    pmf = TempPMF.from_probs(60, [0.1,0.2,0.4,0.2,0.1])  # 60..64
    for s in (2.0, 0.5):
        cal = CalibrationParams(bias=0.0, spread_scale=s, n_samples=50)
        out = apply_calibration(pmf, cal)
        assert out.probs.sum() == pytest.approx(1.0)
