import pytest
from kaiju.types import TradeIntent
from kaiju.strategy.sizing import size_event


def _intent(tkr, p, price, edge):
    return TradeIntent(tkr, "yes", price, 1, p, edge)


def _it(tkr, p, price, edge, c=1): return TradeIntent(tkr, "yes", price, c, p, edge)


def test_kelly_caps_by_bankroll_fraction():
    intents = [_intent("M", 0.7, 45, 0.20)]
    sized = size_event(intents, bankroll_usd=500, kelly_fraction=0.25,
                        max_bankroll_frac=0.10)
    # capped stake <= 0.10 * 500 = $50 ; contract cost $0.45 => <=111 contracts,
    # but Kelly fraction should bind first and be > 0
    assert 1 <= sized[0].count
    assert sized[0].count * 0.45 <= 50.0 + 1e-9


def test_drops_when_kelly_below_one_contract():
    intents = [_intent("M", 0.51, 49, 0.005)]
    sized = size_event(intents, 100, 0.25, 0.10)
    assert sized == []


def test_event_level_budget_shared_across_buckets():
    intents = [_intent("A", 0.6, 30, 0.15), _intent("B", 0.6, 30, 0.15)]
    sized = size_event(intents, 500, 0.25, 0.10)
    total_cost = sum(s.count * 0.30 for s in sized)
    assert total_cost <= 0.10 * 500 + 1e-9   # shared event budget, not per-bucket


def test_non_positive_edge_intent_dropped():
    assert size_event([_it("M", 0.5, 50, -0.1)], 500, 0.25, 0.10) == []
    assert size_event([_it("M", 0.5, 50, 0.0)], 500, 0.25, 0.10) == []


def test_full_kelly_boundary_still_budget_capped():
    sized = size_event([_it("M", 0.9, 30, 0.5)], 500, 1.0, 0.10)
    assert sum(s.count * 0.30 for s in sized) <= 0.10 * 500 + 1e-9


def test_single_intent_exceeding_budget_capped():
    sized = size_event([_it("A", 0.9, 10, 0.5)], 100, 0.25, 0.10)
    assert sum(s.count * 0.10 for s in sized) <= 0.10 * 100 + 1e-9


def test_invalid_params_raise():
    with pytest.raises(ValueError):
        size_event([_it("M", 0.7, 40, 0.2)], 500, 0.0, 0.10)
    with pytest.raises(ValueError):
        size_event([_it("M", 0.7, 40, 0.2)], 500, 1.5, 0.10)
    with pytest.raises(ValueError):
        size_event([_it("M", 0.7, 40, 0.2)], 500, 0.25, 0.0)
    with pytest.raises(ValueError):
        size_event([_it("M", 0.7, 40, 0.2)], 500, 0.25, 1.5)
