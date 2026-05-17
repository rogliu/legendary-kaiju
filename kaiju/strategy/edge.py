from __future__ import annotations
from kaiju.types import TempPMF, Bucket


def bucket_probabilities(pmf: TempPMF, buckets: list[Bucket]) -> dict[str, float]:
    raw: dict[str, float] = {}
    for b in buckets:
        lo = None if b.lower_f is None else int(b.lower_f)
        hi = None if b.upper_f is None else int(b.upper_f)
        raw[b.market_ticker] = pmf.prob_interval(lo, hi)
    total = sum(raw.values())
    if total <= 0:
        raise ValueError("buckets capture no PMF mass")
    return {k: v / total for k, v in raw.items()}
