from __future__ import annotations
from kaiju.types import TradeIntent


def _kelly_fraction(p: float, price_cents: int) -> float:
    """Binary Kelly: edge / odds. Cost c, payoff 1. b = (1-c)/c, q = 1-p."""
    c = price_cents / 100.0
    if c <= 0 or c >= 1:
        return 0.0
    b = (1.0 - c) / c
    f = (p * b - (1.0 - p)) / b
    return max(0.0, f)


def size_event(
    intents: list[TradeIntent],
    bankroll_usd: float,
    kelly_fraction: float,
    max_bankroll_frac: float,
) -> list[TradeIntent]:
    budget = bankroll_usd * max_bankroll_frac          # shared per city-day event
    out: list[TradeIntent] = []
    spent = 0.0
    for it in sorted(intents, key=lambda x: -x.net_edge):
        if _kelly_fraction(it.model_prob, it.limit_price_cents) <= 0.0:
            continue
        stake = min(kelly_fraction * it.net_edge * bankroll_usd, budget - spent)
        cost = it.limit_price_cents / 100.0
        count = int(stake // cost)
        if count < 1:
            continue
        spent += count * cost
        out.append(
            TradeIntent(
                it.market_ticker,
                it.side,
                it.limit_price_cents,
                count,
                it.model_prob,
                it.net_edge,
            )
        )
    return out
