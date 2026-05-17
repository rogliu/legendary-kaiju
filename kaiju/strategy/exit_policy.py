from __future__ import annotations
from kaiju.types import Position, MarketQuote, ExitDecision, ExitAction

def decide_exit(position: Position, fair_cents: int, quote: MarketQuote,
                minutes_to_timestop: int, exit_margin_cents: int,
                fill_margin_cents: int) -> ExitDecision:
    """Exit logic for an open position. Precedence (deliberate):
    time-stop -> thesis-invalidation -> convergence -> hold.

    All comparisons are done in the price space of the contract we ACTUALLY
    hold: `side_fair` is the fair value of that contract (YES fair for a yes
    position, 100 - YES fair for a no position), and `entry` is the price we
    paid for it. Time-stop wins first: once past the cutoff we hold the
    remainder to settlement (bounded fallback) rather than CUT into a thin
    end-of-day book.
    """
    is_yes = position.side == "yes"
    side_fair = fair_cents if is_yes else 100 - fair_cents
    entry = position.avg_entry_cents

    # Time-stop: bounded fallback wins -> hold remainder to settlement.
    # minutes_to_timestop == 0 still attempts a clean exit; only strictly past cutoff (<0) holds
    if minutes_to_timestop < 0:
        return ExitDecision(ExitAction.HOLD, None, "time-stop: hold to settlement")
    # Thesis invalidation: the contract we hold is now worth <= what we paid.
    if side_fair <= entry:
        return ExitDecision(ExitAction.CUT, None,
                            f"thesis invalidated (side_fair {side_fair} <= entry {entry})")
    # Convergence: market (the side we'd sell) within exit_margin of side_fair.
    mkt = quote.yes_bid if is_yes else quote.no_bid
    if mkt is not None and abs(side_fair - mkt) <= exit_margin_cents:
        limit = max(1, min(99, side_fair - fill_margin_cents))
        return ExitDecision(ExitAction.EXIT, limit, "converged")
    return ExitDecision(ExitAction.HOLD, None, "gap open")
