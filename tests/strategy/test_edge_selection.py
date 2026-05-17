from kaiju.types import MarketQuote
from kaiju.strategy.edge import select_trades

def test_selects_yes_when_model_beats_ask_net_of_fee():
    model_probs = {"M": 0.70}
    quotes = {"M": MarketQuote("M", yes_bid=40, yes_ask=45, no_bid=55, no_ask=60,
                               volume=500, open_interest=1000)}
    intents = select_trades(model_probs, quotes, net_edge_threshold=0.08,
                            min_open_interest=100)
    assert len(intents) == 1
    t = intents[0]
    assert t.side == "yes" and t.limit_price_cents == 45
    assert t.net_edge > 0.08

def test_rejects_when_edge_below_threshold():
    model_probs = {"M": 0.50}
    quotes = {"M": MarketQuote("M", 48, 52, 48, 52, 500, 1000)}
    assert select_trades(model_probs, quotes, 0.08, 100) == []

def test_rejects_illiquid_market():
    model_probs = {"M": 0.99}
    quotes = {"M": MarketQuote("M", 1, 2, 98, 99, 0, 10)}
    assert select_trades(model_probs, quotes, 0.08, 100) == []

def test_selects_no_when_model_far_below_ask():
    model_probs = {"M": 0.20}
    quotes = {"M": MarketQuote("M", 20, 25, 70, 75, 500, 1000)}
    intents = select_trades(model_probs, quotes, 0.02, 100)
    assert len(intents) == 1
    assert intents[0].side == "no"

def test_yes_miss_falls_through_to_no():
    # YES edge below threshold; NO edge above threshold -> NO selected
    model_probs = {"M": 0.40}
    quotes = {"M": MarketQuote("M", 48, 50, 48, 50, 500, 1000)}
    intents = select_trades(model_probs, quotes, 0.01, 100)
    assert len(intents) == 1
    assert intents[0].side == "no"

def test_skips_boundary_ask_prices_without_crashing():
    # yes_ask=100 (at settlement) must not raise and must not produce a trade;
    # a valid market in the same batch is still evaluated.
    quotes = {
        "SETTLE": MarketQuote("SETTLE", 99, 100, 0, 1, 500, 1000),
        "GOOD":   MarketQuote("GOOD",   40,  45, 55, 60, 500, 1000),
    }
    intents = select_trades({"SETTLE": 0.99, "GOOD": 0.70}, quotes, 0.08, 100)
    assert [i.market_ticker for i in intents] == ["GOOD"]
    assert intents[0].side == "yes"

def test_ticker_missing_from_quotes_is_skipped():
    intents = select_trades({"NOPE": 0.9}, {}, 0.08, 100)
    assert intents == []
