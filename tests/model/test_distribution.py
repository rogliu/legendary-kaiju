import numpy as np
import pytest
from kaiju.model.distribution import pmf_from_nbm_percentiles, blend_pmfs
from kaiju.types import TempPMF


def test_pmf_from_percentiles_is_monotone_and_normalized():
    pct = {10: 60.0, 25: 62.0, 50: 65.0, 75: 68.0, 90: 70.0}
    pmf = pmf_from_nbm_percentiles(pct)
    assert isinstance(pmf, TempPMF)
    assert pytest.approx(pmf.probs.sum()) == 1.0
    cdf = np.cumsum(pmf.probs)
    assert np.all(np.diff(cdf) >= -1e-12)
    assert abs(pmf.prob_interval(None, 65) - 0.5) < 0.08


def test_blend_is_convex_combination():
    a = TempPMF.from_probs(0, [1.0, 0.0])
    b = TempPMF.from_probs(0, [0.0, 1.0])
    blended = blend_pmfs([(a, 0.75), (b, 0.25)])
    assert pytest.approx(blended.prob_at(0)) == 0.75
    assert pytest.approx(blended.prob_at(1)) == 0.25


def test_non_monotone_percentiles_raise():
    with pytest.raises(ValueError, match="not monotone"):
        pmf_from_nbm_percentiles({10: 70.0, 50: 60.0, 90: 65.0})


def test_blend_different_ranged_pmfs_union_grid():
    a = TempPMF.from_probs(60, [0.5, 0.5])      # 60,61
    b = TempPMF.from_probs(62, [1.0])           # 62
    out = blend_pmfs([(a, 0.5), (b, 0.5)])
    assert out.low_f == 60 and out.high_f == 62
    assert out.prob_at(60) == pytest.approx(0.25)
    assert out.prob_at(61) == pytest.approx(0.25)
    assert out.prob_at(62) == pytest.approx(0.50)
    assert out.probs.sum() == pytest.approx(1.0)


def test_blend_non_unit_weights_are_relative():
    a = TempPMF.from_probs(0, [1.0, 0.0])
    b = TempPMF.from_probs(0, [0.0, 1.0])
    out = blend_pmfs([(a, 2.0), (b, 2.0)])      # equal relative weights -> 50/50
    assert out.prob_at(0) == pytest.approx(0.5)
    assert out.prob_at(1) == pytest.approx(0.5)


def test_blend_empty_and_negative_weight_raise():
    with pytest.raises(ValueError):
        blend_pmfs([])
    a = TempPMF.from_probs(0, [1.0])
    with pytest.raises(ValueError):
        blend_pmfs([(a, -0.5)])
