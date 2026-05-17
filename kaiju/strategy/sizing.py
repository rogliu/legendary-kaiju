from __future__ import annotations
from kaiju.types import TradeIntent


def _has_positive_edge(p: float, price_cents: int) -> bool:
    """Positive-edge gate: returns True only when model prob exceeds contract cost."""
    c = price_cents / 100.0
    return 0.0 < c < 1.0 and p > c


def size_event(
    intents: list[TradeIntent],
    bankroll_usd: float,
    kelly_fraction: float,
    max_bankroll_frac: float,
) -> list[TradeIntent]:
    if not (0.0 < kelly_fraction <= 1.0):
        raise ValueError(f"kelly_fraction must be in (0,1], got {kelly_fraction}")
    if not (0.0 < max_bankroll_frac <= 1.0):
        raise ValueError(f"max_bankroll_frac must be in (0,1], got {max_bankroll_frac}")
    budget = bankroll_usd * max_bankroll_frac          # shared per city-day event
    out: list[TradeIntent] = []
    spent = 0.0
    for it in sorted(intents, key=lambda x: -x.net_edge):
        if not _has_positive_edge(it.model_prob, it.limit_price_cents):
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
