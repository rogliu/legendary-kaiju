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
