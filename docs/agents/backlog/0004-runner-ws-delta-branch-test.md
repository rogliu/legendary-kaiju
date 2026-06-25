# Task 0004 — test coverage for runner `_on_ws_event` orderbook_delta branch

## Motivation

Task 0002 made `PaperBook.apply_delta` correct and well-unit-tested, but the
`kaiju/runner.py` `_on_ws_event` **delta branch** that feeds it is untested:
the wire parse (`round(float(price_dollars) * 100)`, `int(float(delta_fp))`),
the `side`/`price_dollars`/`delta_fp` extraction, and both WARNING paths
(malformed delta; orphan delta before snapshot) have no test. The parse mirrors
the established, tested `_lvl_to_cents` / `_dollars_str_to_cents` helpers, so the
risk is low — but a field-name or sign regression here would silently corrupt
shadow-paper fills, exactly the failure 0002 set out to close. (Raised by the
`kaiju-reviewer` pass on 0002.)

## Scope

- **Owned module(s):** `kaiju/runner.py` (`_on_ws_event` / a small extracted
  pure delta-parse helper if that is the cleanest way to make it testable) and a
  test file (`tests/test_runner_ws_events.py` or an addition to
  `tests/test_runner.py`).
- **Conflict scope:** the WS handler in `runner.py`. Does not touch
  `paper_sim.py` book logic (0002 owns that).

## Acceptance criteria

- Failing test first: a normalized `orderbook_delta` event dict
  (`{"type": "orderbook_delta", "market_ticker": ..., "side": "yes",
  "price_dollars": "0.96", "delta_fp": "-54.00"}`) routed through the handler
  mutates the `PaperBook` as expected (price→cents, signed size).
- Orphan delta (market not yet snapshotted) → book uncorrupted + a WARNING.
- Malformed delta (missing `side`/`price_dollars`/`delta_fp`) → dropped + a
  WARNING, no exception escaping the handler.
- `make check` green. No behavior change to the delta application itself —
  this task only adds coverage (plus, if needed, a pure-function extraction that
  is byte-for-byte equivalent).

## Out of scope

The two design-level follow-ups the same review flagged (track separately):
- **Quote/fill divergence:** `live_quotes` is refreshed on snapshots only, so the
  fair-value/quote path and the delta-updated fill book diverge between
  snapshots. Reconciling them touches the trading-logic/fair-value path.
- **Seq-gap detection:** a *mid-stream* dropped delta on a seeded market silently
  desyncs until the next snapshot (no `seq` gap detection / re-snapshot). The WS
  `seq` field and `update_subscription`/`get_snapshot` cmd are UNVERIFIED
  (`docs/superpowers/notes/kalshi-ws-contract.md` §4, §8) — confirm on the
  Task-17 live demo before building on them.

## Danger-zone check

Touches `runner.py` (`_on_ws_event`) + a test only. Does NOT touch `risk/`,
`eval/gate.py`, `config.py` live path, `parser._SETTLEMENT_MAP`, `notes/`, or
rail files.

> ☑ Confirmed no danger-zone changes

## Definition of done

Per `CONTRIBUTING.md` — all six conditions.
