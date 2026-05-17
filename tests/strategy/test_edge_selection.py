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
