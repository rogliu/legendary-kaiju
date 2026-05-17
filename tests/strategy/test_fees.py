"""
Tests for kaiju.strategy.fees.trade_fee_cents.

Test vectors are from docs/superpowers/notes/kalshi-api-contract.md Section 6.
The fee constant (FEE_COEFF = 0.07) is UNVERIFIED pending live-demo cross-check
(see Section 7 item 1 in the contract notes).
"""

from kaiju.strategy.fees import trade_fee_cents


def test_fee_matches_kalshi_published_example() -> None:
    # From docs/superpowers/notes/kalshi-api-contract.md Section 6 "Test vectors":
    #   Input:  price_dollars = 0.50, count = 100, role = taker
    #   Expected output: $1.75 total fee = 175 cents
    #   Formula: ceil(0.07 × 0.50 × 0.50 × 100) × 100 = ceil(175.0) = 175 cents
    assert trade_fee_cents(price_cents=50, count=100) == 175


def test_fee_is_nonneg_and_symmetric_in_price() -> None:
    assert trade_fee_cents(1, 1) >= 0
    # fee depends on p*(1-p); price P and (100-P) are symmetric, so equal fee
    assert trade_fee_cents(40, 7) == trade_fee_cents(60, 7)


def test_fee_scales_with_count_monotonically() -> None:
    assert trade_fee_cents(50, 10) >= trade_fee_cents(50, 1)


def test_fee_rounds_up_to_integer_cents() -> None:
    # price_cents=50, count=1: raw = 0.07 × 0.50 × 0.50 × 100 = 1.75 → ceil → 2
    f = trade_fee_cents(50, 1)
    assert isinstance(f, int)
    assert f == 2   # round-up of 1.75c/contract for a single contract
