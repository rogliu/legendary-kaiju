import pytest
from kaiju.types import TempPMF, Bucket

def test_pmf_validates_and_normalizes():
    pmf = TempPMF.from_probs(low_f=50, probs=[1.0, 1.0, 2.0])  # unnormalized
    assert pmf.high_f == 52
    assert pytest.approx(pmf.probs.sum()) == 1.0
    assert pytest.approx(pmf.prob_at(50)) == 0.25

def test_pmf_rejects_negative():
    with pytest.raises(ValueError):
        TempPMF.from_probs(low_f=0, probs=[0.5, -0.1, 0.6])

def test_prob_interval_inclusive_and_open_tails():
    pmf = TempPMF.from_probs(low_f=10, probs=[0.2, 0.3, 0.5])  # 10,11,12
    assert pytest.approx(pmf.prob_interval(11, 12)) == 0.8
    assert pytest.approx(pmf.prob_interval(None, 10)) == 0.2   # <=10
    assert pytest.approx(pmf.prob_interval(12, None)) == 0.5    # >=12
    assert pytest.approx(pmf.prob_interval(None, None)) == 1.0

def test_bucket_contains_semantics():
    b = Bucket(market_ticker="M", lower_f=50, upper_f=51)   # inclusive 50..51
    assert b.contains(50) and b.contains(51) and not b.contains(52)
    lo_tail = Bucket(market_ticker="L", lower_f=None, upper_f=49)
    assert lo_tail.contains(-5) and lo_tail.contains(49) and not lo_tail.contains(50)

def test_prob_at_outside_range_is_zero():
    pmf = TempPMF.from_probs(low_f=10, probs=[0.5, 0.5])  # 10,11
    assert pmf.prob_at(99) == 0.0
    assert pmf.prob_at(-1) == 0.0

def test_from_probs_rejects_empty_nan_and_2d():
    with pytest.raises(ValueError):
        TempPMF.from_probs(10, [])
    with pytest.raises(ValueError):
        TempPMF.from_probs(10, [0.3, float("nan"), 0.4])
    with pytest.raises(ValueError):
        TempPMF.from_probs(10, [[0.3, 0.7]])
