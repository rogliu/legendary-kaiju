"""
Kalshi fee model — taker fee for quadratic-fee markets.

Formula (taker, per contract):
    per_contract_centicents = ceil(FEE_COEFF × (price_cents / 100) × (1 − price_cents / 100) × 10_000)
    fee_cents = ceil(per_contract_centicents × count / 100)

Where 10_000 converts dollars to centicents ($0.0001 = 1 centicent) and the
outer ceil converts centicents to whole cents.

Source: docs/superpowers/notes/kalshi-api-contract.md, Section 4 ("Fee Formula")
        and Section 6 ("Test vectors").

Rounding rule (from official Kalshi fee-rounding docs, Section 4):
    "trade fee: rounded up to the nearest $0.0001 (centicent)"
    Rounding is applied per-contract to the nearest centicent ($0.0001), then
    the total is converted to integer cents (ceiling).  This matches the
    Section 6 test vector: price_cents=50, count=100 → 175 cents ($1.75).

NOTE — UNVERIFIED CONSTANT:
    FEE_COEFF = 0.07 (7% taker rate) is sourced from third-party sources
    (polytrage.com, pm.wiki); the official Kalshi fee-schedule PDF returned
    HTTP 429 during the research spike and could not be directly read.  The
    constant is deliberately isolated here so it can be trivially updated once
    a live demo fill confirms the actual rate (see Section 7, item 1 of the
    contract notes).
"""

import math

# Taker fee coefficient.
# SOURCE: third-party (polytrage.com, pm.wiki); see module docstring.
# UNVERIFIED — adjust here once confirmed against a live demo fill.
FEE_COEFF: float = 0.07

# Number of centicents per dollar ($0.0001 = 1 centicent; $1.00 = 10_000 centicents).
# This is the rounding granularity stated in official Kalshi fee-rounding docs.
_CENTICENTS_PER_DOLLAR: int = 10_000


def trade_fee_cents(price_cents: int, count: int) -> int:
    """Return the taker fee in whole cents (rounded up) for a single order.

    Args:
        price_cents: YES-side price in integer cents (1–99).  Enforced: must be
            in the closed range [1, 99]; raises ValueError otherwise.
        count: Number of contracts in the order (≥ 1).  Enforced: must be >= 1;
            raises ValueError otherwise.

    Returns:
        Fee in integer cents (ceiling after centicent rounding).

    Raises:
        ValueError: if price_cents is not in 1..99 or count < 1.

    Formula:
        per_contract_centicents = ceil(FEE_COEFF × (price_cents/100) × (1 − price_cents/100) × 10_000)
        fee_cents = ceil(per_contract_centicents × count / 100)
    """
    if not (1 <= price_cents <= 99):
        raise ValueError(f"price_cents must be 1..99, got {price_cents}")
    if count < 1:
        raise ValueError(f"count must be >= 1, got {count}")
    p = price_cents / 100.0
    raw_dollars_per_contract = FEE_COEFF * p * (1.0 - p)
    # Round up per-contract fee to nearest centicent ($0.0001), guarding
    # against IEEE-754 noise before ceil (e.g. p=50: 0.07*0.50*0.50*10_000 = 175.00000000000003).
    per_contract_centicents = math.ceil(round(raw_dollars_per_contract * _CENTICENTS_PER_DOLLAR, 10))
    total_centicents = per_contract_centicents * count
    return math.ceil(total_centicents / 100)
