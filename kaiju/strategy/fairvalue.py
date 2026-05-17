from __future__ import annotations
from kaiju.types import TempPMF, Bucket
from kaiju.strategy.edge import bucket_probabilities

def fair_prices(pmf: TempPMF, buckets: list[Bucket]) -> dict[str, int]:
    """Fair value per bucket in cents = round(100 * P(bucket))."""
    probs = bucket_probabilities(pmf, buckets)
    return {tkr: int(round(100.0 * p)) for tkr, p in probs.items()}
