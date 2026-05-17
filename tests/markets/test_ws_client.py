"""Tests for kaiju/markets/ws_client.py.

Recorded WS contract: docs/superpowers/notes/kalshi-ws-contract.md

All tests are OFFLINE — no real network connections. A FakeWS transport
replaces the real websockets connection.

WS message type note: the recorded contract uses:
  - "orderbook_snapshot" (outer type field)
  - "orderbook_delta"    (outer type field)
  - "fill"               (outer type field)
matching exactly what we use in FakeWS messages and what WsClient normalizes.

The outer envelope from the real server is:
  {"type": "...", "sid": N, "seq": N, "msg": {...}}
WsClient normalizes by hoisting type to top level and merging msg fields in,
so on_event receives: {"type": "...", "sid": N, "seq": N, <msg fields...>}
"""

import asyncio
import json

from kaiju.markets.ws_client import WsClient


class FakeWS:
    """Fake async WebSocket transport for offline tests."""

    def __init__(self, msgs):
        self.msgs = list(msgs)
        self.sent = []
        self.closed = False

    async def send(self, m):
        self.sent.append(json.loads(m))

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.msgs:
            raise StopAsyncIteration
        return json.dumps(self.msgs.pop(0))

    async def close(self):
        self.closed = True


def test_run_once_reconciles_then_dispatches_book_and_fill():
    """Core contract: reconcile fires first, then each message, socket closed on end."""
    events = []
    fake = FakeWS([
        {
            "type": "orderbook_snapshot",
            "sid": 2,
            "seq": 2,
            "msg": {
                "market_ticker": "M",
                "yes_dollars_fp": [["0.4000", "100.00"]],
                "no_dollars_fp": [["0.5800", "50.00"]],
            },
        },
        {
            "type": "fill",
            "sid": 13,
            "msg": {
                "market_ticker": "M",
                "yes_price_dollars": "0.400",
                "count_fp": "2.00",
                "side": "yes",
            },
        },
    ])
    c = WsClient(
        connect=lambda: fake,
        on_event=events.append,
        on_connect_reconcile=lambda: events.append({"type": "reconcile"}),
    )
    asyncio.run(c.run_once())
    kinds = [e["type"] for e in events]
    assert kinds[0] == "reconcile"
    assert "orderbook_snapshot" in kinds and "fill" in kinds
    assert fake.closed is True  # socket must be closed when stream ends


def test_run_once_sends_subscribe_msgs():
    """subscribe_msgs are sent to the socket before consuming messages."""
    events = []
    fake = FakeWS([])
    subs = [
        {"id": 1, "cmd": "subscribe", "params": {"channels": ["orderbook_delta"], "market_ticker": "M"}},
        {"id": 2, "cmd": "subscribe", "params": {"channels": ["fill"]}},
    ]
    c = WsClient(
        connect=lambda: fake,
        on_event=events.append,
        on_connect_reconcile=lambda: None,
        subscribe_msgs=subs,
    )
    asyncio.run(c.run_once())
    # Both subscribe messages should be sent in order
    assert len(fake.sent) == 2
    assert fake.sent[0]["cmd"] == "subscribe"
    assert fake.sent[1]["cmd"] == "subscribe"
    assert fake.sent[0]["params"]["channels"] == ["orderbook_delta"]
    assert fake.sent[1]["params"]["channels"] == ["fill"]
    assert fake.closed is True


def test_run_once_normalizes_outer_envelope():
    """WsClient hoists type from outer envelope; msg fields are merged in."""
    events = []
    fake = FakeWS([
        {
            "type": "orderbook_snapshot",
            "sid": 2,
            "seq": 5,
            "msg": {
                "market_ticker": "X",
                "yes_dollars_fp": [["0.5000", "10.00"]],
                "no_dollars_fp": [],
            },
        },
    ])
    c = WsClient(
        connect=lambda: fake,
        on_event=events.append,
        on_connect_reconcile=lambda: None,
    )
    asyncio.run(c.run_once())
    # Filter out non-dict or non-WS events
    ws_events = [e for e in events if e.get("type") != "reconcile"]
    assert len(ws_events) == 1
    evt = ws_events[0]
    assert evt["type"] == "orderbook_snapshot"
    assert evt["sid"] == 2
    assert evt["seq"] == 5
    # msg fields hoisted
    assert evt["market_ticker"] == "X"
    assert evt["yes_dollars_fp"] == [["0.5000", "10.00"]]


def test_run_once_no_subscribe_msgs_no_send():
    """When subscribe_msgs is None, no send() calls are made."""
    fake = FakeWS([])
    c = WsClient(
        connect=lambda: fake,
        on_event=lambda e: None,
        on_connect_reconcile=lambda: None,
    )
    asyncio.run(c.run_once())
    assert fake.sent == []


def test_run_forever_stops_cleanly():
    """stop() causes run_forever to exit without re-connecting."""
    call_count = 0
    closed_sockets = []

    def make_fake():
        nonlocal call_count
        call_count += 1
        f = FakeWS([])
        closed_sockets.append(f)
        return f

    c = WsClient(
        connect=make_fake,
        on_event=lambda e: None,
        on_connect_reconcile=lambda: None,
    )
    c.stop()  # stop before run_forever begins
    asyncio.run(c.run_forever())
    # Should not have connected at all (or at most once before checking stop flag)
    assert call_count == 0 or all(s.closed for s in closed_sockets)


def test_run_forever_reconnects_on_exception():
    """run_forever reconnects after a connection error, then stops."""
    call_count = 0
    errors_raised = 0

    class ErrorWS:
        """Fake WS that raises an exception on first message."""
        async def send(self, m):
            pass

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise ConnectionError("simulated disconnect")

        async def close(self):
            pass

    def make_ws():
        nonlocal call_count, errors_raised
        call_count += 1
        if call_count == 1:
            return ErrorWS()
        # Second connect: stop the loop then return empty stream
        c.stop()
        return FakeWS([])

    c = WsClient(
        connect=make_ws,
        on_event=lambda e: None,
        on_connect_reconcile=lambda: None,
    )
    asyncio.run(c.run_forever(max_backoff=0.0))
    # Should have connected at least twice (reconnect after error)
    assert call_count >= 2
