from __future__ import annotations
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class GateCriteria:
    min_days: int = 30
    min_trades: int = 15
    min_pit_pvalue: float = 0.05
    max_drawdown_usd: float = 25.0
    min_fill_rate: float = 0.20


@dataclass(frozen=True)
class GateResult:
    qualified: bool
    reason: str


def evaluate_promotion(days, brier, market_baseline_brier, pit_uniform_pvalue,
        sim_pnl_usd, trades, max_drawdown_usd, fill_rate, c: GateCriteria) -> GateResult:
    # Boundary semantics: all at-threshold checks PASS by design (days==min passes,
    # trades==min passes, drawdown==max passes, fill==min passes).
    # brier>=baseline and pnl<=0 are the conservative FAIL boundaries.
    metrics = {"days": days, "brier": brier,
               "market_baseline_brier": market_baseline_brier,
               "pit_uniform_pvalue": pit_uniform_pvalue, "sim_pnl_usd": sim_pnl_usd,
               "trades": trades, "max_drawdown_usd": max_drawdown_usd,
               "fill_rate": fill_rate}
    for _name, _v in metrics.items():
        if not math.isfinite(_v):
            return GateResult(False, f"non-finite metric: {_name}={_v}")
    if days < c.min_days:
        return GateResult(False, f"insufficient days ({days})")
    if trades < c.min_trades:
        return GateResult(False, f"insufficient trades ({trades})")
    if brier >= market_baseline_brier:
        return GateResult(False, "calibration not better than market")
    if pit_uniform_pvalue < c.min_pit_pvalue:
        return GateResult(False, "PIT not uniform")
    if sim_pnl_usd <= 0:
        return GateResult(False, "non-positive simulated pnl")
    if max_drawdown_usd > c.max_drawdown_usd:
        return GateResult(False, "drawdown exceeds bound")
    if fill_rate < c.min_fill_rate:
        return GateResult(False, "fill rate too low")
    return GateResult(True, "qualified")


def can_trade_live(qualified: bool, armed: bool) -> bool:
    return bool(qualified and armed)
