from __future__ import annotations
import numpy as np
from kaiju.types import TempPMF


def pmf_from_nbm_percentiles(pct_to_temp: dict[float, float]) -> TempPMF:
    """Interpolate calibrated percentile->temp to a discrete integer-°F PMF.

    Callers must pass percentiles whose temperatures are monotone non-decreasing
    (NBM provides calibrated 0..100 percentiles per the recorded contract).
    """
    qs = np.array(sorted(pct_to_temp), dtype=float) / 100.0
    ts = np.array([pct_to_temp[p] for p in sorted(pct_to_temp)], dtype=float)
    if ts.size > 1 and not np.all(np.diff(ts) >= 0):
        raise ValueError(
            f"percentile->temp not monotone non-decreasing: "
            f"{list(zip(sorted(pct_to_temp), ts.tolist()))}")
    lo, hi = int(np.floor(ts.min())) - 1, int(np.ceil(ts.max())) + 1
    grid = np.arange(lo, hi + 1)
    cdf = np.interp(grid, ts, qs, left=0.0, right=1.0)
    pmf = np.diff(np.concatenate([[0.0], cdf]))
    pmf = np.clip(pmf, 0.0, None)
    return TempPMF.from_probs(low_f=lo, probs=pmf)


def blend_pmfs(weighted: list[tuple[TempPMF, float]]) -> TempPMF:
    """Blend PMFs with relative weights, renormalized via TempPMF.from_probs.

    Weights are treated as RELATIVE (the result is renormalized via
    TempPMF.from_probs), and must be non-negative with positive sum.
    """
    if not weighted:
        raise ValueError("blend_pmfs requires at least one (pmf, weight)")
    if any(w < 0 for _, w in weighted):
        raise ValueError("blend_pmfs weights must be non-negative")
    lo = min(p.low_f for p, _ in weighted)
    hi = max(p.high_f for p, _ in weighted)
    acc = np.zeros(hi - lo + 1)
    for pmf, w in weighted:
        acc[pmf.low_f - lo: pmf.low_f - lo + len(pmf.probs)] += w * pmf.probs
    return TempPMF.from_probs(low_f=lo, probs=acc)
