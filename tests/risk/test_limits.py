import pytest
from kaiju.types import TradeIntent
from kaiju.risk.limits import RiskGate

def it(c=1,price=40): return TradeIntent("M","yes",price,c,0.7,0.15)

def test_kill_switch_blocks(tmp_path):
    ks=tmp_path/"KILL"
    ks.write_text("x")
    g=RiskGate(str(ks),max_contracts_per_market=50,max_open_exposure_usd=500,
               max_daily_loss_usd=50,bankroll_usd=500)
    assert g.check(it(),realized_loss_today_usd=0,open_exposure_usd=0).approved is False

def test_daily_loss_blocks(tmp_path):
    g=RiskGate(str(tmp_path/"n"),50,500,50,500)
    d=g.check(it(),realized_loss_today_usd=50,open_exposure_usd=0)
    assert d.approved is False and "daily loss" in d.reason

def test_exposure_cap_blocks(tmp_path):
    g=RiskGate(str(tmp_path/"n"),50,100,50,500)
    d=g.check(it(c=10,price=40),realized_loss_today_usd=0,open_exposure_usd=99)
    assert d.approved is False and "exposure" in d.reason

def test_clamps_to_per_market_cap(tmp_path):
    g=RiskGate(str(tmp_path/"n"),max_contracts_per_market=5,max_open_exposure_usd=500,
               max_daily_loss_usd=50,bankroll_usd=500)
    d=g.check(it(c=999),0,0)
    assert d.approved and d.adjusted_count==5

def test_zero_after_clamp_is_rejected_not_approved(tmp_path):
    g=RiskGate(str(tmp_path/"n"),max_contracts_per_market=0,max_open_exposure_usd=500,
               max_daily_loss_usd=50,bankroll_usd=500)
    d=g.check(it(c=5),0,0)
    assert d.approved is False and "zero contracts" in d.reason

def test_bankroll_accounts_for_open_exposure(tmp_path):
    # max_exp high so exposure passes, but cumulative exceeds bankroll
    g=RiskGate(str(tmp_path/"n"),50,max_open_exposure_usd=10000,
               max_daily_loss_usd=999,bankroll_usd=200)
    d=g.check(it(c=10,price=40),realized_loss_today_usd=0,open_exposure_usd=199)
    assert d.approved is False and "bankroll" in d.reason

def test_empty_kill_switch_path_rejected_at_construction():
    with pytest.raises(ValueError):
        RiskGate("",50,500,50,500)
    with pytest.raises(ValueError):
        RiskGate(None,50,500,50,500)  # type: ignore[arg-type]

def test_price_out_of_range_blocked(tmp_path):
    g=RiskGate(str(tmp_path/"n"),50,500,50,500)
    assert g.check(it(c=1,price=0),0,0).approved is False
    assert g.check(it(c=1,price=100),0,0).approved is False

def test_negative_open_exposure_blocked(tmp_path):
    g=RiskGate(str(tmp_path/"n"),50,500,50,500)
    assert g.check(it(c=1,price=40),0,-5).approved is False

def test_exposure_exactly_at_cap_blocks(tmp_path):
    # open+add == max_exp must block (fail-safe >=)
    g=RiskGate(str(tmp_path/"n"),50,max_open_exposure_usd=100.0,
               max_daily_loss_usd=50,bankroll_usd=500)
    d=g.check(it(c=10,price=40),realized_loss_today_usd=0,open_exposure_usd=96.0)  # 96+4=100
    assert d.approved is False and "exposure" in d.reason

def test_kill_switch_wins_even_when_other_limits_breached(tmp_path):
    ks=tmp_path/"KILL"
    ks.write_text("x")
    g=RiskGate(str(ks),50,500,50,500)
    d=g.check(it(c=1,price=40),realized_loss_today_usd=999,open_exposure_usd=999)
    assert d.approved is False and "kill" in d.reason
