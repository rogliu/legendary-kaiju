import pytest
from kaiju.types import TempPMF, Bucket
from kaiju.strategy.edge import bucket_probabilities

def test_bucket_probs_sum_to_one_and_match_pmf():
    pmf = TempPMF.from_probs(low_f=48, probs=[0.1, 0.2, 0.4, 0.2, 0.1])  # 48..52
    buckets = [
        Bucket("LO", None, 49),     # <=49 -> 0.1+0.2=0.3
        Bucket("M1", 50, 51),       # 50,51 -> 0.4+0.2=0.6
        Bucket("HI", 52, None),     # >=52 -> 0.1
    ]
    probs = bucket_probabilities(pmf, buckets)
    assert pytest.approx(probs["LO"]) == 0.3
    assert pytest.approx(probs["M1"]) == 0.6
    assert pytest.approx(probs["HI"]) == 0.1
    assert pytest.approx(sum(probs.values())) == 1.0

def test_renormalizes_when_buckets_cover_partial_support():
    pmf = TempPMF.from_probs(low_f=0, probs=[0.5, 0.5])  # 0,1
    buckets = [Bucket("A", 0, 0), Bucket("B", 1, 1)]
    probs = bucket_probabilities(pmf, buckets)
    assert pytest.approx(sum(probs.values())) == 1.0
