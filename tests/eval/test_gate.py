from kaiju.eval.gate import evaluate_promotion, GateCriteria, can_trade_live


def test_qualifies_and_arm_required():
    r = evaluate_promotion(
        days=30, brier=0.16, market_baseline_brier=0.20,
        pit_uniform_pvalue=0.4, sim_pnl_usd=18.0, trades=25, max_drawdown_usd=8.0,
        fill_rate=0.6, c=GateCriteria()
    )
    assert r.qualified is True
    assert can_trade_live(True, True) and not can_trade_live(True, False) and not can_trade_live(False, True)


def test_fails_on_negative_pnl_or_low_fill_or_few_days():
    c = GateCriteria()
    assert evaluate_promotion(30, 0.16, 0.20, 0.4, -1.0, 25, 8.0, 0.6, c).qualified is False
    assert evaluate_promotion(30, 0.16, 0.20, 0.4, 18.0, 25, 8.0, 0.05, c).qualified is False
    assert evaluate_promotion(5, 0.16, 0.20, 0.4, 18.0, 25, 8.0, 0.6, c).qualified is False


def test_gate_fails_closed_on_non_finite_metric():
    c = GateCriteria()
    r = evaluate_promotion(30, float("nan"), 0.20, 0.4, 18.0, 25, 8.0, 0.6, c)
    assert r.qualified is False and "non-finite" in r.reason
    r2 = evaluate_promotion(30, 0.16, 0.20, 0.4, float("inf"), 25, 8.0, 0.6, c)
    assert r2.qualified is False and "non-finite" in r2.reason

def test_gate_boundaries_at_threshold():
    c = GateCriteria()
    # at-threshold PASSES: days==30, trades==15, drawdown==25.0, fill==0.20
    assert evaluate_promotion(30, 0.16, 0.20, 0.4, 1.0, 15, 25.0, 0.20, c).qualified is True
    # brier == baseline FAILS (strict improvement required)
    assert evaluate_promotion(30, 0.20, 0.20, 0.4, 1.0, 25, 8.0, 0.6, c).qualified is False
    # pnl == 0 FAILS (non-positive)
    assert evaluate_promotion(30, 0.16, 0.20, 0.4, 0.0, 25, 8.0, 0.6, c).qualified is False

def test_can_trade_live_false_false():
    assert can_trade_live(False, False) is False
