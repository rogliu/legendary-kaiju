from kaiju.types import Position, ExitDecision, ExitAction

def test_position_fields():
    p = Position(market_ticker="M", side="yes", count=3, avg_entry_cents=44, climate_date="2026-05-17")
    assert p.count == 3 and p.side == "yes" and p.avg_entry_cents == 44

def test_exit_decision_actions():
    d = ExitDecision(action=ExitAction.EXIT, limit_price_cents=61, reason="converged")
    assert d.action is ExitAction.EXIT and d.limit_price_cents == 61
    h = ExitDecision(action=ExitAction.HOLD, limit_price_cents=None, reason="gap open")
    assert h.action is ExitAction.HOLD and h.limit_price_cents is None
    c = ExitDecision(action=ExitAction.CUT, limit_price_cents=None, reason="stop hit")
    assert c.action is ExitAction.CUT and c.limit_price_cents is None
