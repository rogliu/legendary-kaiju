# Task 0002 — apply orderbook_delta incrementally

## Motivation

`kaiju/runner.py` `_on_ws_event` currently treats `orderbook_delta`
WebSocket messages as full snapshots (it logs: *"v1 limitation: delta
messages are applied as snapshots; incremental delta application is deferred
to a future task"*). Under a real Kalshi stream, deltas carry only level
changes — applying them as snapshots silently corrupts the `PaperBook` and
the derived intraday quotes, which biases shadow-paper fills (and thus the
proof). Correct incremental application makes the paper-proof faithful.

## Scope

- **Owned module(s):** `kaiju/markets/ws_client.py` and/or the delta-apply
  helper; `kaiju/execution/paper_sim.py` `PaperBook` (incremental update).
- **Files expected to change:** the book-update path + the runner WS handler
  branch; tests in `tests/markets/test_ws_client.py` and/or
  `tests/execution/test_paper_sim.py`.
- **Conflict scope:** WS handler + `PaperBook`. Does not overlap Task 0001.

## Acceptance criteria

- Failing test first: feed a `orderbook_snapshot` then a `orderbook_delta`
  that changes one price level; assert the resulting book equals the book
  built by applying the change incrementally (not by replacing with the
  delta payload). Cover add / modify / remove-to-zero of a level.
- Snapshots still fully replace; deltas mutate the existing book.
- Out-of-order / missing-snapshot delta → safe resync (request/await a fresh
  snapshot), never a corrupted book.
- `make check` green.

## Out of scope

Changing the trading logic, fair value, or fill simulation math beyond the
book representation. Live-order behavior.

## Danger-zone check

Touches WS/paper-sim only. Does NOT touch `risk/`, `eval/gate.py`,
`config.py` live path, `parser._SETTLEMENT_MAP`, `notes/`, or rail files.

> ☑ Confirmed no danger-zone changes

## Definition of done

Per `CONTRIBUTING.md` — all six conditions.
