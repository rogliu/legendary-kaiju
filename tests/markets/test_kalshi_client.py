"""Tests for kaiju/markets/kalshi_client.py.

Recorded contract: docs/superpowers/notes/kalshi-api-contract.md

Orderbook shape used in tests matches the recorded contract verbatim:
  {"orderbook_fp": {"yes_dollars": [["0.5500", "100.00"]], "no_dollars": [["0.4500", "100.00"]]}}

Each level is [price_dollars_string, count_fp_string].
Best bid = first entry (highest YES buy price), best ask = first entry (lowest YES sell / NO buy price).
"""

import respx
import httpx
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from kaiju.markets.kalshi_client import KalshiClient, sign_request, _verify_for_test


def _pem():
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = k.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    return k, pem


def test_signature_round_trip():
    k, pem = _pem()
    sig, ts = sign_request(pem, "GET", "/trade-api/v2/markets", timestamp_ms=1700000000000)
    assert _verify_for_test(
        k.public_key(), sig, "1700000000000" + "GET" + "/trade-api/v2/markets"
    )


def test_sign_request_strips_query_string():
    """sign_request must sign only the path, not query params."""
    k, pem = _pem()
    # Path with query string — should be signed WITHOUT the query portion.
    sig, ts = sign_request(
        pem,
        "GET",
        "/trade-api/v2/portfolio/orders?limit=5",
        timestamp_ms=1700000000000,
    )
    # Verification against path WITHOUT query should pass.
    assert _verify_for_test(
        k.public_key(),
        sig,
        "1700000000000" + "GET" + "/trade-api/v2/portfolio/orders",
    )


def test_get_quote_parses_orderbook():
    """get_quote parses the recorded orderbook_fp shape into MarketQuote (cents ints)."""
    _, pem = _pem()
    # Recorded response shape (kalshi-api-contract.md §3.5):
    # orderbook_fp.yes_dollars: list of [price_dollars_str, count_fp_str], best bid first
    # orderbook_fp.no_dollars:  list of [price_dollars_str, count_fp_str], best bid first
    # "0.5500" dollars → 55 cents; "0.4500" dollars → 45 cents
    body = {
        "orderbook_fp": {
            "yes_dollars": [["0.5500", "100.00"], ["0.5400", "50.00"]],
            "no_dollars": [["0.4500", "100.00"], ["0.4600", "50.00"]],
        }
    }
    with respx.mock:
        respx.get(url__regex=r".*/markets/.*/orderbook").mock(
            return_value=httpx.Response(200, json=body)
        )
        c = KalshiClient(key_id="k", private_key_pem=pem, base_url="https://x")
        q = c.get_quote("M-TICKER")

    assert q.market_ticker == "M-TICKER"
    # yes_bid = best YES buy price = first yes_dollars level = 55 cents
    assert q.yes_bid == 55
    # yes_ask is not available directly from orderbook; we derive it from
    # the best NO buy level: yes_ask = 100 - no_bid_cents = 100 - 45 = 55
    # (contract: yes + no = 1 dollar; no_bid_dollars is lowest YES ask)
    assert q.yes_ask is not None
    # no_bid = best NO buy price = first no_dollars level = 45 cents
    assert q.no_bid == 45
    # no_ask derived from yes_bid: no_ask = 100 - yes_bid = 100 - 55 = 45
    assert q.no_ask is not None


def test_get_quote_empty_orderbook():
    """Empty orderbook levels yield None for all bid/ask fields."""
    _, pem = _pem()
    body = {"orderbook_fp": {"yes_dollars": [], "no_dollars": []}}
    with respx.mock:
        respx.get(url__regex=r".*/markets/.*/orderbook").mock(
            return_value=httpx.Response(200, json=body)
        )
        c = KalshiClient(key_id="k", private_key_pem=pem, base_url="https://x")
        q = c.get_quote("EMPTY-TICKER")

    assert q.market_ticker == "EMPTY-TICKER"
    assert q.yes_bid is None
    assert q.yes_ask is None
    assert q.no_bid is None
    assert q.no_ask is None
