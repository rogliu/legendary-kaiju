# Task 0006 — harden runner orderbook_delta against non-numeric wire fields

## Motivation

`_apply_orderbook_delta` (kaiju/runner.py, the WS `orderbook_delta` branch
extracted in task 0004) guards on field **presence** (`side in {yes,no}`,
`price_dollars`/`delta_fp` not None) but not numeric **validity**. A
present-but-non-numeric value — e.g. `price_dollars="abc"`, a wire-protocol
violation — passes the guard and raises `ValueError` at
`round(float(price_dollars) * 100)`. That exception escapes `_on_ws_event` into
the `WsClient` event dispatch.

This is **pre-existing** behavior (identical before the 0004 extraction), not a
regression — surfaced by the kaiju-reviewer pass on 0004. It is a latent
robustness gap on the live money path: one malformed delta could disrupt the WS
read loop rather than being dropped like a missing-field delta.

## Open question to resolve first

Determine the blast radius: does `WsClient`'s `on_event` call site catch and log
exceptions (so today the connection survives and only the one event is lost), or
does the exception propagate up and tear down the read loop? The right fix
depends on this:
- If the loop already survives → this is cosmetic; a local catch just makes the
  drop explicit + logged (preferred for auditability).
- If the loop dies → this is a real availability bug and the catch is required.

Check `kaiju/` for the WS client (`make_kalshi_ws_connect` / `WsClient`) and its
`on_event` invocation before deciding.

## Scope

- **Owned module(s):** `kaiju/runner.py` (`_apply_orderbook_delta`) and possibly
  the `WsClient` event-dispatch site; a test addition to
  `tests/test_runner_ws_events.py`.
- Wrap the `float(...)` parse so a non-numeric `price_dollars`/`delta_fp` is
  dropped with the same `malformed orderbook_delta dropped` WARNING as the
  missing-field path (consistent treatment), NOT silently swallowed (Pattern 3).

## Acceptance criteria

- Failing test first: a delta with `price_dollars="abc"` (or `delta_fp="x"`)
  routed through `_apply_orderbook_delta` does NOT raise and leaves the book
  unmutated, with a WARNING logged.
- The existing missing-field / invalid-side / orphan / valid-parse tests still
  pass unchanged.
- `make check` green.

## Out of scope

- Any change to the numeric parse semantics for VALID inputs (round-to-cents and
  signed-size truncation stay exactly as task 0002/0004 fixed them).
- Seq-gap detection and quote/fill divergence (tracked as 0004's out-of-scope
  follow-ups).

## Danger-zone check

Touches `runner.py` (WS handler) + possibly the WS client wrapper + a test. Does
NOT touch `risk/`, `eval/gate.py`, `config.py` live path, `parser._SETTLEMENT_MAP`,
`notes/`, or rail files.

> ☑ Confirmed no danger-zone changes

## Definition of done

Per `CONTRIBUTING.md` — all six conditions.
