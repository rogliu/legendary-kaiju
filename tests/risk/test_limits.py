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
