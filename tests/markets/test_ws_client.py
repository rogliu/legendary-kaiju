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
import logging

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


# ---------------------------------------------------------------------------
# New tests for reliability fixes (Fix 1–5)
# ---------------------------------------------------------------------------


class AlwaysErrorWS:
    """Fake WS transport that always raises a non-clean error on iteration."""

    def __init__(self, exc: Exception | None = None) -> None:
        self._exc = exc or ConnectionError("simulated auth failure")

    async def send(self, m: str) -> None:
        pass

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        raise self._exc

    async def close(self) -> None:
        pass


def test_persistent_failure_logs_and_grows_backoff_not_tight_loop(caplog):
    """Fix 1: persistent non-clean errors are logged and produce growing backoff.

    A transport that always raises a real error must:
    (a) produce WARNING/ERROR log messages containing the error text,
    (b) grow the backoff across attempts (non-decreasing, not constant 0.1),
    (c) not treat the error as a clean stream end (i.e. backoff path, not reset path).
    """
    connect_count = 0
    sleep_durations: list[float] = []

    async def fake_wait_for(coro, *, timeout: float) -> None:
        """Monkeypatched stand-in: record the timeout, immediately time-out (no sleep)."""
        sleep_durations.append(timeout)
        # Cancel the coro we were given so it does not linger.
        coro.close()
        raise asyncio.TimeoutError

    def make_ws():
        nonlocal connect_count
        connect_count += 1
        if connect_count >= 4:
            c.stop()
        return AlwaysErrorWS(ConnectionError("simulated auth failure"))

    c = WsClient(
        connect=make_ws,
        on_event=lambda e: None,
        on_connect_reconcile=lambda: None,
    )

    # Patch asyncio.wait_for inside ws_client so the test is instant.
    import kaiju.markets.ws_client as ws_mod
    original_wait_for = asyncio.wait_for
    try:
        ws_mod.asyncio.wait_for = fake_wait_for  # type: ignore[attr-defined]
        with caplog.at_level(logging.WARNING, logger="kaiju.markets.ws_client"):
            asyncio.run(c.run_forever(max_backoff=32.0))
    finally:
        ws_mod.asyncio.wait_for = original_wait_for

    # (a) Error text appeared in logs at WARNING or ERROR level.
    warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("simulated auth failure" in r.getMessage() for r in warning_records), (
        "Expected the connection error to be logged at WARNING/ERROR level"
    )

    # (b) Backoff grew across attempts — sequence must be non-decreasing and
    #     must NOT be all equal to 0.1 (that would be the tight-loop / reset bug).
    assert len(sleep_durations) >= 2, "Expected multiple backoff sleeps"
    assert sleep_durations == sorted(sleep_durations), (
        f"Backoff must be non-decreasing, got {sleep_durations}"
    )
    assert not all(d == sleep_durations[0] for d in sleep_durations), (
        f"Backoff must grow across retries, got constant {sleep_durations}"
    )

    # (c) We connected at least 3 times (error path, not clean-end reset path).
    assert connect_count >= 3


def test_clean_close_is_stream_end_not_error(caplog):
    """Fix 1: a clean stream-end (StopAsyncIteration) does NOT log an error and resets backoff.

    Uses FakeWS which raises StopAsyncIteration on empty — the canonical clean close.
    run_forever should return after stop() without emitting any WARNING/ERROR.
    """
    call_count = 0

    def make_ws():
        nonlocal call_count
        call_count += 1
        c.stop()  # stop after first clean connect
        return FakeWS([])  # empty → immediate StopAsyncIteration → clean end

    c = WsClient(
        connect=make_ws,
        on_event=lambda e: None,
        on_connect_reconcile=lambda: None,
    )

    with caplog.at_level(logging.WARNING, logger="kaiju.markets.ws_client"):
        asyncio.run(c.run_forever(max_backoff=0.0))

    # Clean close must NOT produce any warning/error log.
    warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warning_records == [], (
        f"Clean stream end should not log at WARNING/ERROR, got: {warning_records}"
    )
    assert call_count == 1


def test_reconcile_awaited_when_async():
    """Fix 2: an async on_connect_reconcile is properly awaited.

    Passing an async def reconcile that increments a counter; after run_once
    the counter must be 1 (proves it was awaited, not silently skipped).
    """
    reconcile_count = 0

    async def async_reconcile() -> None:
        nonlocal reconcile_count
        reconcile_count += 1

    fake = FakeWS([])
    c = WsClient(
        connect=lambda: fake,
        on_event=lambda e: None,
        on_connect_reconcile=async_reconcile,
    )
    asyncio.run(c.run_once())
    assert reconcile_count == 1, (
        f"Expected async reconcile to be awaited once, got {reconcile_count}"
    )


def test_reconcile_sync_still_works():
    """Fix 2 regression: sync on_connect_reconcile still works after the async-await fix."""
    reconcile_count = 0

    def sync_reconcile() -> None:
        nonlocal reconcile_count
        reconcile_count += 1

    fake = FakeWS([])
    c = WsClient(
        connect=lambda: fake,
        on_event=lambda e: None,
        on_connect_reconcile=sync_reconcile,
    )
    asyncio.run(c.run_once())
    assert reconcile_count == 1


def test_reconcile_called_on_every_reconnect():
    """Fix 2: async reconcile is called on EACH reconnect, not just the first.

    3-connect scenario: first two raises an error (triggering reconnect), third stops.
    Reconcile count must equal connect count (3).
    """
    connect_count = 0
    reconcile_count = 0

    async def async_reconcile() -> None:
        nonlocal reconcile_count
        reconcile_count += 1

    class OneErrorWS:
        """Raises error on first __anext__ call."""
        async def send(self, m: str) -> None:
            pass

        def __aiter__(self):
            return self

        async def __anext__(self) -> str:
            raise ConnectionError("deliberate failure")

        async def close(self) -> None:
            pass

    def make_ws():
        nonlocal connect_count
        connect_count += 1
        if connect_count >= 3:
            c.stop()
            return FakeWS([])  # clean exit on 3rd connect
        return OneErrorWS()

    c = WsClient(
        connect=make_ws,
        on_event=lambda e: None,
        on_connect_reconcile=async_reconcile,
    )
    asyncio.run(c.run_forever(max_backoff=0.0))

    assert connect_count == 3, f"Expected 3 connects, got {connect_count}"
    assert reconcile_count == connect_count, (
        f"reconcile ({reconcile_count}) must equal connect count ({connect_count})"
    )


def test_stop_interrupts_backoff_sleep_promptly():
    """Fix 3: calling stop() during the backoff wait causes run_forever to exit promptly.

    With a large max_backoff (30s), we trigger one error (so the bot enters the backoff
    sleep), then call stop() from a concurrent task. run_forever must return well under
    max_backoff (< 0.5s wall time).
    """
    import time

    class OneErrorWS:
        async def send(self, m: str) -> None:
            pass

        def __aiter__(self):
            return self

        async def __anext__(self) -> str:
            raise ConnectionError("trigger backoff")

        async def close(self) -> None:
            pass

    connect_count = 0

    def make_ws():
        nonlocal connect_count
        connect_count += 1
        return OneErrorWS()

    async def run_test() -> float:
        c = WsClient(
            connect=make_ws,
            on_event=lambda e: None,
            on_connect_reconcile=lambda: None,
        )

        async def stopper():
            # Wait for the first error log (run_once to have failed once), then stop.
            # We use a tiny sleep to let run_forever enter its wait_for backoff.
            await asyncio.sleep(0.05)
            c.stop()

        start = time.monotonic()
        await asyncio.gather(
            c.run_forever(max_backoff=30.0),
            stopper(),
        )
        return time.monotonic() - start

    elapsed = asyncio.run(run_test())
    assert elapsed < 0.5, (
        f"run_forever should exit promptly when stop() is called during backoff, "
        f"but took {elapsed:.2f}s (max_backoff=30.0)"
    )
