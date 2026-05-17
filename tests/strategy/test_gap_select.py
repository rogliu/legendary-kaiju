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


def test_selects_no_when_fair_below_ask():
    # fair=30 -> p=0.30 ; no_ask=25 -> NO edge = 0.70 - 0.25 - fee ≈ 0.43 (>=0.08)
    out = select_gap_trades({"M": 30}, {"M": q("M", 33, 25)}, {},
                            net_edge_threshold=0.08, min_open_interest=100)
    assert len(out) == 1
    assert out[0].side == "no"
    assert out[0].limit_price_cents == 25
    assert abs(out[0].model_prob - 0.70) < 1e-9      # NO stores 1-p, not p


def test_yes_edge_miss_falls_through_to_no():
    # fair=40 -> p=0.40 ; yes_ask=55 -> YES edge ≈ -0.17 (miss) ;
    # no_ask=30 -> NO edge = 0.60 - 0.30 - fee ≈ 0.28 (>=0.08) -> selects NO
    out = select_gap_trades({"M": 40}, {"M": q("M", 55, 30)}, {},
                            net_edge_threshold=0.08, min_open_interest=100)
    assert len(out) == 1 and out[0].side == "no"


def test_absent_ticker_in_quotes_is_skipped():
    assert select_gap_trades({"NOPE": 70}, {}, {}, 0.08, 100) == []
