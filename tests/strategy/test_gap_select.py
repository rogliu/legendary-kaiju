from kaiju.types import MarketQuote, Position
from kaiju.strategy.edge import select_gap_trades


def q(t, ya, na, oi=1000):
    return MarketQuote(t, ya - 3, ya, na - 3, na, 500, oi)


def test_buys_underpriced_side_when_gap_clears_cost():
    fair = {"M": 70}
    quotes = {"M": q("M", 55, 48)}   # fair 70 > yes_ask 55 -> buy yes
    out = select_gap_trades(fair, quotes, positions={}, net_edge_threshold=0.08, min_open_interest=100)
    assert len(out) == 1 and out[0].side == "yes" and out[0].limit_price_cents == 55


def test_skips_when_already_positioned():
    fair = {"M": 70}
    quotes = {"M": q("M", 55, 48)}
    pos = {"M": Position("M", "yes", 2, 55, "2026-05-17")}
    assert select_gap_trades(fair, quotes, pos, 0.08, 100) == []


def test_skips_thin_book_and_small_gap():
    assert select_gap_trades({"M": 52}, {"M": q("M", 50, 52)}, {}, 0.08, 100) == []
    assert select_gap_trades({"M": 99}, {"M": q("M", 5, 95, oi=10)}, {}, 0.08, 100) == []
