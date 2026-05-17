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

N = Position("M","no",3,35,"2026-05-17")   # paid 35c for NO; entry(NO-space)=35

def test_no_thesis_invalidation_cuts_when_no_fair_below_entry():
    # YES fair=70 -> NO fair=30 <= entry 35 -> CUT
    d = decide_exit(N, fair_cents=70, quote=q(0,0), minutes_to_timestop=120,
                     exit_margin_cents=5, fill_margin_cents=2)
    assert d.action is ExitAction.CUT

def test_no_profitable_position_not_cut():
    # YES fair=30 -> NO fair=70 > entry 35 -> NOT cut (must not be CUT)
    d = decide_exit(N, fair_cents=30, quote=MarketQuote("M",0,0,60,80,500,1000),
                     minutes_to_timestop=120, exit_margin_cents=5, fill_margin_cents=2)
    assert d.action is not ExitAction.CUT

def test_no_convergence_exits_in_no_space():
    # YES fair=30 -> NO fair=70 ; no_bid=69 -> |70-69|=1<=5 -> EXIT limit 70-2=68 (NO-space)
    d = decide_exit(N, fair_cents=30, quote=MarketQuote("M",28,32,69,72,500,1000),
                     minutes_to_timestop=120, exit_margin_cents=5, fill_margin_cents=2)
    assert d.action is ExitAction.EXIT and d.limit_price_cents == 68

def test_no_convergence_open_gap_holds():
    # YES fair=30 -> NO fair=70 ; no_bid=50 -> |70-50|=20>5 -> HOLD
    d = decide_exit(N, fair_cents=30, quote=MarketQuote("M",48,52,50,53,500,1000),
                     minutes_to_timestop=120, exit_margin_cents=5, fill_margin_cents=2)
    assert d.action is ExitAction.HOLD and "gap" in d.reason

def test_time_stop_wins_over_thesis_for_no():
    # past cutoff: even though NO fair 30 <= entry 35 (would be CUT), time-stop holds
    d = decide_exit(N, fair_cents=70, quote=q(0,0), minutes_to_timestop=-1,
                     exit_margin_cents=5, fill_margin_cents=2)
    assert d.action is ExitAction.HOLD and "time-stop" in d.reason
