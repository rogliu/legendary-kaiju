from kaiju.types import TempPMF, Bucket
from kaiju.strategy.fairvalue import fair_prices

def test_fair_prices_are_rounded_cents_summing_near_100():
    pmf = TempPMF.from_probs(48, [0.1,0.2,0.4,0.2,0.1])
    buckets=[Bucket("LO",None,49),Bucket("M",50,51),Bucket("HI",52,None)]
    fp = fair_prices(pmf, buckets)
    assert fp == {"LO":30, "M":60, "HI":10}
    assert 99 <= sum(fp.values()) <= 101
