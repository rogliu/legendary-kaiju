"""Kalshi REST API client with RSA-PSS request signing.

Authoritative contract: docs/superpowers/notes/kalshi-api-contract.md

Auth message format (from recorded contract §2):
    message = str(timestamp_ms) + HTTP_METHOD_UPPERCASE + path_without_query_params
    Example: "1703123456789GET/trade-api/v2/portfolio/balance"

Signature algorithm (from recorded contract §2):
    RSA-PSS, SHA-256 digest, MGF1(SHA-256), salt_length = PSS.DIGEST_LENGTH (32 bytes for SHA-256)
    Output: standard base64-encoded string (not URL-safe)

Orderbook field mapping (recorded contract §3.5):
    Response key:     orderbook_fp.yes_dollars  → list of [price_dollars_str, count_fp_str]
    Response key:     orderbook_fp.no_dollars   → list of [price_dollars_str, count_fp_str]
    Each level sorted best-first (highest YES bid first, highest NO bid first).
    Conversion: price_dollars_str → cents via round(float(s) * 100)
    MarketQuote mapping:
        yes_bid  = first yes_dollars level price (best YES buy, cents)
        yes_ask  = 100 - first no_dollars level price (best YES sell = complement of best NO bid)
        no_bid   = first no_dollars level price (best NO buy, cents)
        no_ask   = 100 - first yes_dollars level price (best NO sell = complement of best YES bid)
        volume   = 0 (not returned by orderbook endpoint; caller should use GET /markets/{ticker})
        open_interest = 0 (same — not in orderbook response)

UNVERIFIED items for Task 15/17 to confirm via live demo:
    - Base64 variant (standard vs URL-safe): assumed standard; if sig rejected, try urlsafe
    - Orderbook level ordering: assumed best-first (highest bid first); verify live
    - Create order V2 `side` field: `bid`/`ask` semantics need live confirmation (§7 risk 6)
    - fee_multiplier interaction with fee formula (§7 risk 2)
    - Weather series tickers (KXHIGHNY etc.) must be verified via live GET /series (§7 risk 4)
"""

from __future__ import annotations

import base64
import time
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from cryptography.exceptions import InvalidSignature

from kaiju.types import MarketQuote


def sign_request(
    private_key_pem: str,
    method: str,
    path: str,
    timestamp_ms: int,
) -> tuple[str, str]:
    """Sign a Kalshi API request and return (base64_signature, timestamp_str).

    Args:
        private_key_pem: PEM-encoded RSA private key (TraditionalOpenSSL or PKCS8).
            Callers MUST pass `settings.kalshi_private_key.get_secret_value()`;
            never pass str() on a SecretStr — that would produce "**********".
        method: HTTP method (e.g. "GET", "POST"). Will be uppercased.
        path: Full request path including query string; query string is stripped
            before signing per recorded contract.
        timestamp_ms: Unix timestamp in milliseconds (integer).

    Returns:
        Tuple of (base64-encoded signature string, str(timestamp_ms)).
    """
    # Strip query string before signing (recorded contract §2, critical detail)
    signing_path = path.split("?")[0]

    message = f"{timestamp_ms}{method.upper()}{signing_path}".encode("utf-8")

    loaded_key = serialization.load_pem_private_key(
        private_key_pem.encode("utf-8"),
        password=None,
    )
    if not isinstance(loaded_key, RSAPrivateKey):
        raise TypeError("Expected RSA private key")
    private_key: RSAPrivateKey = loaded_key

    signature_bytes = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )

    return base64.b64encode(signature_bytes).decode("ascii"), str(timestamp_ms)


def _verify_for_test(
    public_key: RSAPublicKey,
    signature_b64: str,
    message: str,
) -> bool:
    """Verify an RSA-PSS signature using the same parameters as sign_request.

    This is a test-only helper; mirrors the exact PSS/SHA256 params from the
    recorded contract to verify round-trip correctness.

    Args:
        public_key: RSA public key corresponding to the signing private key.
        signature_b64: Standard base64-encoded signature string.
        message: The plaintext message that was signed (pre-encoded to UTF-8).

    Returns:
        True if the signature is valid, False otherwise.
    """
    try:
        public_key.verify(
            base64.b64decode(signature_b64),
            message.encode("utf-8"),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return True
    except InvalidSignature:
        return False


def _dollars_str_to_cents(s: str) -> int:
    """Convert a FixedPointDollars string (e.g. "0.5500") to integer cents."""
    return round(float(s) * 100)


class KalshiClient:
    """Authenticated Kalshi REST API client.

    Endpoint paths and JSON field names follow the recorded contract in
    docs/superpowers/notes/kalshi-api-contract.md verbatim.

    Usage (in runner/task 17):
        from kaiju.config import Settings
        settings = Settings()
        client = KalshiClient(
            key_id=settings.kalshi_key_id,
            private_key_pem=settings.kalshi_private_key.get_secret_value(),
            base_url="https://external-api.kalshi.com/trade-api/v2",
        )

    IMPORTANT: Always call settings.kalshi_private_key.get_secret_value() to
    obtain the PEM string. Never use str() on a SecretStr — it returns "**********".
    Never log or print the PEM.
    """

    def __init__(
        self,
        key_id: str,
        private_key_pem: str,
        base_url: str,
        timeout: float = 20.0,
    ) -> None:
        """
        Args:
            key_id: Kalshi API Key ID (UUID, used as KALSHI-ACCESS-KEY header).
            private_key_pem: PEM-encoded RSA private key. Obtain via
                Settings.kalshi_private_key.get_secret_value().
            base_url: Base URL including path prefix, e.g.
                "https://external-api.kalshi.com/trade-api/v2" (prod) or
                "https://external-api.demo.kalshi.co/trade-api/v2" (demo).
            timeout: HTTP request timeout in seconds.
        """
        self._key_id = key_id
        self._private_key_pem = private_key_pem
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
    ) -> Any:
        """Perform a signed HTTP request and return parsed JSON.

        The path should be relative to base_url (e.g. "/markets/M-TICKER").
        Query parameters are passed via `params` dict, not embedded in `path`.

        Signing uses the FULL path including the base_url path prefix (e.g.
        "/trade-api/v2/portfolio/balance") per recorded contract §2.
        """
        timestamp_ms = int(time.time() * 1000)
        # Sign the full path from host root: base_url path prefix + endpoint path.
        # Recorded contract §2 example: "1703123456789GET/trade-api/v2/portfolio/balance"
        base_path = urlparse(self._base_url).path.rstrip("/")  # e.g. "/trade-api/v2"
        full_path = base_path + path  # e.g. "/trade-api/v2/portfolio/balance"
        sig, ts = sign_request(self._private_key_pem, method, full_path, timestamp_ms)

        headers = {
            "KALSHI-ACCESS-KEY": self._key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": sig,
        }

        url = self._base_url + path
        # NOTE: retry/backoff on 5xx deferred to runner (Task 17); failures propagate loud.
        with httpx.Client(timeout=self._timeout) as client:
            response = client.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json,
            )
            response.raise_for_status()
            try:
                return response.json()
            except Exception as e:
                raise RuntimeError(
                    f"Kalshi returned non-JSON response for {method} {path}: {e}"
                ) from e

    # ------------------------------------------------------------------
    # Public API methods (names are cross-task contracts for Task 15/17)
    # ------------------------------------------------------------------

    def list_events(self, series_ticker: str) -> Any:
        """List events for a series.

        GET /events?series_ticker=...

        Recorded contract §3.2 (UNVERIFIED: /events endpoint 404'd during research;
        endpoint likely exists but full schema unconfirmed). Task 15/17 should verify.

        Returns:
            Raw JSON from the API (typically a dict with an events array).
        """
        return self._request("GET", "/events", params={"series_ticker": series_ticker})

    def list_markets(self, event_ticker: str) -> Any:
        """List markets for an event.

        GET /markets?event_ticker=...

        Recorded contract §3.3.

        Returns:
            Raw JSON from the API (dict containing "markets" array).
        """
        return self._request("GET", "/markets", params={"event_ticker": event_ticker})

    def get_quote(self, market_ticker: str) -> MarketQuote:
        """Fetch the current orderbook for a market and return a MarketQuote.

        GET /markets/{ticker}/orderbook

        Recorded contract §3.5. Orderbook shape:
            orderbook_fp.yes_dollars: [[price_dollars_str, count_fp_str], ...]  best bid first
            orderbook_fp.no_dollars:  [[price_dollars_str, count_fp_str], ...]  best bid first

        Field mapping to MarketQuote (all prices in integer cents):
            yes_bid  = first yes_dollars level price
            yes_ask  = 100 - first no_dollars level price  (complement: best YES ask = 100 - best NO bid)
            no_bid   = first no_dollars level price
            no_ask   = 100 - first yes_dollars level price (complement: best NO ask = 100 - best YES bid)
            volume   = 0 (not in orderbook endpoint; use GET /markets/{ticker} for volume)
            open_interest = 0 (same)

        UNVERIFIED: Level ordering (best-first assumed); confirm via live demo.

        WARNING: open_interest and volume are 0 here (the orderbook endpoint carries
        neither). strategy.edge.select_gap_trades SKIPS markets with
        open_interest < min_open_interest (default ~100). Quotes from get_quote MUST
        NOT be the trade-filter quote source. The runner must source open_interest /
        volume from list_markets via markets.parser.parse_event_snapshot (Task 13).
        """
        data = self._request("GET", f"/markets/{market_ticker}/orderbook")
        ob = data.get("orderbook_fp", {})
        yes_levels = ob.get("yes_dollars", [])
        no_levels = ob.get("no_dollars", [])

        yes_bid: Optional[int] = (
            _dollars_str_to_cents(yes_levels[0][0]) if yes_levels else None
        )
        no_bid: Optional[int] = (
            _dollars_str_to_cents(no_levels[0][0]) if no_levels else None
        )
        # yes_ask = complement of best NO bid (best YES sell price)
        yes_ask: Optional[int] = (100 - no_bid) if no_bid is not None else None
        # no_ask = complement of best YES bid (best NO sell price)
        no_ask: Optional[int] = (100 - yes_bid) if yes_bid is not None else None

        return MarketQuote(
            market_ticker=market_ticker,
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            no_bid=no_bid,
            no_ask=no_ask,
            volume=0,
            open_interest=0,
        )

    def get_balance(self) -> Any:
        """Return portfolio balance.

        GET /portfolio/balance

        Recorded contract §3.6. Key response fields:
            balance (int, cents), balance_dollars (str), portfolio_value (int, cents).

        Returns:
            Raw JSON dict from the API.
        """
        return self._request("GET", "/portfolio/balance")

    def get_positions(self) -> list[Any]:
        """Return current market positions.

        GET /portfolio/positions

        Recorded contract §3.7. Response contains "market_positions" array.

        Returns:
            market_positions list from the API response.
        """
        data = self._request("GET", "/portfolio/positions")
        result: list[Any] = data.get("market_positions", [])
        return result

    def create_order(
        self,
        client_order_id: str,
        ticker: str,
        side: str,
        action: str,
        count: int,
        price_cents: int,
    ) -> Any:
        """Create a limit order via the legacy endpoint.

        POST /portfolio/orders

        Recorded contract §3.8. Uses legacy endpoint which is deprecated as of
        May 21, 2026 (rate-limit costs increased). Task 15/17 should migrate to
        POST /portfolio/events/orders (V2, §3.9) once V2 `side` semantics are
        confirmed (UNVERIFIED: bid/ask mapping — see §7 risk 6).

        Args:
            client_order_id: Idempotency key.
            ticker: Market ticker.
            side: "yes" or "no".
            action: "buy" or "sell".
            count: Number of whole contracts (min 1).
            price_cents: Limit price in cents (1–99).

        Returns:
            Raw JSON dict (order object) from the API.
        """
        body: dict[str, Any] = {
            "ticker": ticker,
            "client_order_id": client_order_id,
            "side": side,
            "action": action,
            "count": count,
            "yes_price" if side == "yes" else "no_price": price_cents,
        }
        return self._request("POST", "/portfolio/orders", json=body)

    def cancel_order(self, order_id: str) -> Any:
        """Cancel a resting order.

        DELETE /portfolio/orders/{order_id}

        Recorded contract §3.10. Returns cancelled order object plus reduced_by_fp.

        Returns:
            Raw JSON dict from the API.
        """
        return self._request("DELETE", f"/portfolio/orders/{order_id}")

    def get_fills(self) -> list[Any]:
        """Return recent fills.

        GET /portfolio/fills

        Recorded contract §3.11. Returns fills array.

        Returns:
            fills list from the API response.
        """
        data = self._request("GET", "/portfolio/fills")
        result: list[Any] = data.get("fills", [])
        return result
