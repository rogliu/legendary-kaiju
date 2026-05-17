from __future__ import annotations
from kaiju.types import TempPMF, Bucket, MarketQuote, TradeIntent
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


def select_trades(model_probs: dict[str, float], quotes: dict[str, MarketQuote],
                  net_edge_threshold: float, min_open_interest: int) -> list[TradeIntent]:
    intents: list[TradeIntent] = []
    for tkr, p in model_probs.items():
        q = quotes.get(tkr)
        if q is None or q.open_interest < min_open_interest:
            continue
        # YES: pay yes_ask cents, win 100 if event true
        if q.yes_ask is not None:
            cost = q.yes_ask / 100.0
            fee = trade_fee_cents(q.yes_ask, 1) / 100.0
            edge = p - cost - fee
            if edge >= net_edge_threshold:
                intents.append(TradeIntent(tkr, "yes", q.yes_ask, 1, p, edge))
                continue
        # NO: pay no_ask cents, win 100 if event false
        if q.no_ask is not None:
            cost = q.no_ask / 100.0
            fee = trade_fee_cents(q.no_ask, 1) / 100.0
            edge = (1.0 - p) - cost - fee
            if edge >= net_edge_threshold:
                intents.append(TradeIntent(tkr, "no", q.no_ask, 1, p, edge))
    return intents
