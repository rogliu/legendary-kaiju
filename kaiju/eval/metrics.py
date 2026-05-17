from __future__ import annotations
import numpy as np
from kaiju.types import TempPMF


def brier_score(probs, outcomes) -> float:
    p = np.asarray(probs, float)
    y = np.asarray(outcomes, float)
    return float(np.mean((p - y) ** 2))


def crps_pmf(pmf: TempPMF, observed: int) -> float:
    temps = np.arange(pmf.low_f, pmf.high_f + 1)
    cdf = np.cumsum(pmf.probs)
    h = (temps >= observed).astype(float)
    return float(np.sum((cdf - h) ** 2))


def pit_value(pmf: TempPMF, observed: int) -> float:
    return float(pmf.prob_interval(None, observed))


def roundtrip_pnl_stats(trades: list[dict]) -> dict:
    n = len(trades)
    net = float(sum(t["pnl_usd"] for t in trades))
    fr = float(sum(1 for t in trades if t.get("exited")) / n) if n else 0.0
    return {"n": n, "net_pnl_usd": net, "fill_rate": fr}
