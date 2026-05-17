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
