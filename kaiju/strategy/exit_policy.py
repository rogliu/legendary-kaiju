from __future__ import annotations
from kaiju.types import Position, MarketQuote, ExitDecision, ExitAction

def decide_exit(position: Position, fair_cents: int, quote: MarketQuote,
                minutes_to_timestop: int, exit_margin_cents: int,
                fill_margin_cents: int) -> ExitDecision:
    """Convergence / thesis-invalidation / time-stop exit logic.
    Position held is `side` of `count`; we close by trading the opposite side."""
    entry = position.avg_entry_cents
    # Thesis invalidation: fair has moved against the entry thesis.
    if position.side == "yes" and fair_cents <= entry:
        return ExitDecision(ExitAction.CUT, None, "thesis invalidated (fair<=entry)")
    if position.side == "no" and fair_cents >= entry:
        return ExitDecision(ExitAction.CUT, None, "thesis invalidated (fair>=entry)")
    # Time-stop: stop managing; hold remainder to settlement (bounded fallback).
    if minutes_to_timestop < 0:
        return ExitDecision(ExitAction.HOLD, None, "time-stop: hold to settlement")
    # Convergence: market within exit_margin of fair -> close via limit.
    mkt = quote.yes_bid if position.side == "yes" else quote.no_bid
    if mkt is not None and abs(fair_cents - mkt) <= exit_margin_cents:
        limit = max(1, min(99, fair_cents - fill_margin_cents))
        return ExitDecision(ExitAction.EXIT, limit, "converged")
    return ExitDecision(ExitAction.HOLD, None, "gap open")
