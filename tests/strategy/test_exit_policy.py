from kaiju.types import Position, MarketQuote, ExitAction
from kaiju.strategy.exit_policy import decide_exit

P = Position("M","yes",3,45,"2026-05-17")
def q(yb,ya): return MarketQuote("M",yb,ya,100-ya,100-yb,500,1000)

def test_converged_triggers_exit_limit_at_fair_minus_margin():
    d = decide_exit(P, fair_cents=70, quote=q(68,71), minutes_to_timestop=120,
                     exit_margin_cents=5, fill_margin_cents=2)
    assert d.action is ExitAction.EXIT and d.limit_price_cents == 68  # fair70 - fill2

def test_thesis_invalidation_cuts_when_fair_drops_through_entry():
    d = decide_exit(P, fair_cents=40, quote=q(38,41), minutes_to_timestop=120,
                     exit_margin_cents=5, fill_margin_cents=2)
    assert d.action is ExitAction.CUT

def test_time_stop_holds_to_settlement_when_unfillable():
    d = decide_exit(P, fair_cents=90, quote=q(50,55), minutes_to_timestop=-1,
                     exit_margin_cents=5, fill_margin_cents=2)
    assert d.action is ExitAction.HOLD and "time-stop" in d.reason

def test_open_gap_holds():
    d = decide_exit(P, fair_cents=90, quote=q(60,63), minutes_to_timestop=120,
                     exit_margin_cents=5, fill_margin_cents=2)
    assert d.action is ExitAction.HOLD
