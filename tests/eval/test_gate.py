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
