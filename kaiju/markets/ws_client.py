"""Kalshi WebSocket client with reconnect, reconcile-on-connect, and injectable transport.

Authoritative WS contract: docs/superpowers/notes/kalshi-ws-contract.md

## Connection URLs (from recorded contract §1)
    Production:  wss://external-api-ws.kalshi.com/trade-api/ws/v2
    Demo:        wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2

## Auth handshake (from recorded contract §2)
    Same three headers as REST (KALSHI-ACCESS-KEY, KALSHI-ACCESS-SIGNATURE,
    KALSHI-ACCESS-TIMESTAMP), sent as HTTP Upgrade headers.

    Signed string:  timestamp_ms_str + "GET" + "/trade-api/ws/v2"
    NOTE: The WS signing path "/trade-api/ws/v2" differs from the REST base
    path "/trade-api/v2" — `ws` appears before `v2` in the WS path.

## Message shapes (from recorded contract §4)
    Outer envelope:  {type, sid, seq, msg}
    orderbook_snapshot msg fields: market_ticker, market_id, yes_dollars_fp, no_dollars_fp
    orderbook_delta msg fields:    market_ticker, market_id, price_dollars, delta_fp, side, ts, ts_ms
    fill msg fields:               trade_id, order_id, market_ticker, is_taker, side,
                                   yes_price_dollars, count_fp, action, ts, ts_ms,
                                   post_position_fp, purchased_side, subaccount

## UNVERIFIED items for Task 17 live demo
    - Signed path confirmed as "/trade-api/ws/v2" from docs — verify server accepts it
    - orderbook_snapshot level ordering (best-first assumed, not explicitly stated)
    - seq field presence on fill channel messages
    - send_initial_snapshot subscribe param behavior
    - purchased_side vs side distinction in fill messages

## YAGNI scope
    Only WsClient + make_kalshi_ws_connect. No book-state maintenance, no
    position tracking — that is the position_manager / paper_sim / runner job.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class WsClient:
    """Kalshi WebSocket client with injectable transport for offline testing.

    Usage (offline / test):
        client = WsClient(
            connect=lambda: FakeWS(...),
            on_event=handle_event,
            on_connect_reconcile=snapshot_positions_from_rest,
        )
        asyncio.run(client.run_once())

    Usage (production) — see make_kalshi_ws_connect for the real connect factory:
        from kaiju.markets.ws_client import WsClient, make_kalshi_ws_connect

        connect = make_kalshi_ws_connect(
            key_id=settings.kalshi_key_id,
            private_key_pem=settings.kalshi_private_key.get_secret_value(),
            base_ws_url="wss://external-api-ws.kalshi.com/trade-api/ws/v2",
            market_tickers=["KXHIGHNY-25JUN17-T74", ...],
        )
        client = WsClient(connect=connect, on_event=..., on_connect_reconcile=...)
        asyncio.run(client.run_forever())
    """

    def __init__(
        self,
        connect: Callable[[], Any],
        on_event: Callable[[dict], None],
        on_connect_reconcile: Callable[[], None],
        *,
        subscribe_msgs: Optional[list[dict]] = None,
    ) -> None:
        """
        Args:
            connect: 0-arg callable returning an async-iterable WS-like object
                with .send(str), async iteration yielding JSON strings, and .close().
            on_event: Called for each normalized event dict received from the server.
                Receives a flat dict with `type` plus all fields from both the outer
                envelope (sid, seq) and the inner msg merged together.
            on_connect_reconcile: Called once immediately after (re)connect, BEFORE
                consuming messages. Use to fetch current state via REST so that
                subsequent WS deltas can be applied correctly.
            subscribe_msgs: Optional list of subscribe message dicts to send
                after connecting (in order). Each is JSON-serialized and sent.
        """
        self._connect = connect
        self._on_event = on_event
        self._on_connect_reconcile = on_connect_reconcile
        self._subscribe_msgs = subscribe_msgs or []
        self._stopped = False

    def stop(self) -> None:
        """Signal run_forever to exit after the current run_once completes."""
        self._stopped = True

    async def run_once(self) -> None:
        """Open one WS connection, reconcile, consume messages, close on stream end.

        1. Calls connect() to obtain the WS connection.
        2. Calls on_connect_reconcile() (before any messages — reconcile window).
        3. Sends each subscribe_msg via ws.send().
        4. Async-iterates messages; JSON-decodes and normalizes each to a plain dict;
           calls on_event(evt) for each.
        5. On stream end (StopAsyncIteration), calls ws.close().

        Normalization: the outer envelope {type, sid, seq, msg} is flattened —
        type/sid/seq stay at top level, and all fields from msg are merged in.
        This gives on_event a single flat dict with all fields.
        """
        ws = self._connect()
        try:
            self._on_connect_reconcile()
            for msg_dict in self._subscribe_msgs:
                await ws.send(json.dumps(msg_dict))
            async for raw in ws:
                envelope = json.loads(raw)
                evt = _normalize_event(envelope)
                self._on_event(evt)
        finally:
            await ws.close()

    async def run_forever(self, *, max_backoff: float = 30.0) -> None:
        """Loop calling run_once(), reconnecting with exponential backoff on failure.

        Each reconnect re-invokes on_connect_reconcile via run_once.
        Call stop() to signal a clean exit after the next run_once completes.

        Args:
            max_backoff: Maximum reconnect delay in seconds (default 30.0).
                Pass 0.0 in tests to skip actual sleep.
        """
        backoff = 0.1
        while not self._stopped:
            try:
                await self.run_once()
                # Clean stream end — reset backoff, reconnect unless stopped
                backoff = 0.1
            except Exception as exc:
                if self._stopped:
                    break
                logger.warning("WsClient connection error, reconnecting in %.1fs: %s", backoff, exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)


def _normalize_event(envelope: dict) -> dict:
    """Flatten the Kalshi WS outer envelope into a single event dict.

    Kalshi WS outer envelope format (from recorded contract §4):
        {type, sid, seq, msg: {...}}

    Result: {type, sid, seq, <all fields from msg>}

    If msg is absent or not a dict, the event is returned as-is (with type
    and any other top-level fields). This handles non-standard messages
    gracefully (e.g. subscribed/error confirmations).
    """
    msg = envelope.get("msg", {})
    if not isinstance(msg, dict):
        return dict(envelope)
    evt = {k: v for k, v in envelope.items() if k != "msg"}
    evt.update(msg)
    return evt


def make_kalshi_ws_connect(
    key_id: str,
    private_key_pem: str,
    base_ws_url: str,
    market_tickers: list[str],
) -> Callable[[], Any]:
    """Build a real Kalshi WS connect factory using the recorded signed handshake.

    WS auth signing path (from recorded contract §2):
        "/trade-api/ws/v2"
    This is NOT the same as the REST base path "/trade-api/v2"; the WS path
    has `ws` before `v2`.

    The connect factory uses sign_request from kalshi_client (same RSA-PSS
    algorithm as REST) with the literal path "/trade-api/ws/v2".

    Args:
        key_id: Kalshi API Key ID (UUID).
        private_key_pem: PEM-encoded RSA private key. Obtain via
            Settings.kalshi_private_key.get_secret_value().
        base_ws_url: Full WS URL, e.g.
            "wss://external-api-ws.kalshi.com/trade-api/ws/v2" (prod) or
            "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2" (demo).
        market_tickers: List of market tickers to subscribe to.

    Returns:
        0-arg callable that, when called, opens and returns an authenticated
        websockets connection (async context not entered — caller iterates it).

    UNVERIFIED (Task 17 to confirm):
        - Server accepts "/trade-api/ws/v2" as the signed path (not full URL).
        - websockets 12+ connect API with extra_headers kwarg works as expected.
    """
    # Heavy import (websockets) is deferred to _WsConnectionWrapper._ensure_connected —
    # offline tests/mypy do not need it installed.
    import time

    from kaiju.markets.kalshi_client import sign_request

    # WS auth signing path — verbatim from recorded contract §2.
    # NOTE: "/trade-api/ws/v2", NOT "/trade-api/v2" (ws before v2).
    WS_SIGNING_PATH = "/trade-api/ws/v2"

    def _connect() -> Any:
        timestamp_ms = int(time.time() * 1000)
        sig, ts = sign_request(private_key_pem, "GET", WS_SIGNING_PATH, timestamp_ms)
        extra_headers = {
            "KALSHI-ACCESS-KEY": key_id,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }
        # websockets.connect returns a context manager; caller must use it as async CM.
        # For run_once's pattern (direct async iteration), wrap in an async generator
        # that opens the connection and yields it.
        return _WsConnectionWrapper(
            base_ws_url,
            extra_headers=extra_headers,
            market_tickers=market_tickers,
        )

    return _connect


class _WsConnectionWrapper:
    """Thin wrapper around websockets.connect that implements the WsClient transport protocol.

    Exposes: send(), async iteration of messages, close().
    Opens the connection lazily on first use (via __aiter__ or send).

    UNVERIFIED: websockets 12+ connect() with extra_headers kwarg confirmed
    in websockets docs for HTTP headers during the WS handshake upgrade request.
    Task 17 live demo will confirm the full auth flow.
    """

    def __init__(self, url: str, extra_headers: dict, market_tickers: list[str]) -> None:
        self._url = url
        self._extra_headers = extra_headers
        self._market_tickers = market_tickers
        self._ws: Any = None
        self._iter: Any = None

    async def _ensure_connected(self) -> None:
        if self._ws is None:
            import websockets  # type: ignore[import]
            self._ws = await websockets.connect(
                self._url,
                additional_headers=self._extra_headers,
            )

    async def send(self, m: str) -> None:
        await self._ensure_connected()
        await self._ws.send(m)

    def __aiter__(self) -> "_WsConnectionWrapper":
        return self

    async def __anext__(self) -> str:
        await self._ensure_connected()
        try:
            return await self._ws.recv()
        except Exception:
            raise StopAsyncIteration

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
