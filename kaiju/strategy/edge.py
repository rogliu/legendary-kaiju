from __future__ import annotations
from kaiju.types import TempPMF, Bucket, MarketQuote, TradeIntent, Position
from kaiju.strategy.fees import trade_fee_cents


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


def select_gap_trades(fair_cents: dict[str, int], quotes: dict[str, MarketQuote],
                       positions: dict[str, Position], net_edge_threshold: float,
                       min_open_interest: int) -> list[TradeIntent]:
    """Enter the cheap side when |fair-market| clears fee+spread+threshold.
    Position-aware: skip a market we already hold (exits handled elsewhere)."""
    out: list[TradeIntent] = []
    for tkr, fair in fair_cents.items():
        if tkr in positions:
            continue
        q = quotes.get(tkr)
        if q is None or q.open_interest < min_open_interest:
            continue
        p = fair / 100.0
        if q.yes_ask is not None and 1 <= q.yes_ask <= 99:
            edge = p - q.yes_ask / 100.0 - trade_fee_cents(q.yes_ask, 1) / 100.0
            if edge >= net_edge_threshold:
                out.append(TradeIntent(tkr, "yes", q.yes_ask, 1, p, edge))
                continue
        if q.no_ask is not None and 1 <= q.no_ask <= 99:
            edge = (1.0 - p) - q.no_ask / 100.0 - trade_fee_cents(q.no_ask, 1) / 100.0
            if edge >= net_edge_threshold:
                out.append(TradeIntent(tkr, "no", q.no_ask, 1, 1.0 - p, edge))
    return out
