# Task 0005 — fix shadow-paper exit fill simulation (exits must close, not grow)

**Prerequisite for task 0003.** Discovered while scoping 0003.

## Motivation

`execute_exits` places an exit as a **sell** of the held side
(`action="sell"`, `side=pos["side"]`; `position_manager.py`), but the
shadow-paper fill simulator `simulate_fills` runs *every* working order through
`PaperBook.try_fill` (a **buy** model) and then takes the same-side
**"accumulate"** branch (`paper_sim.py`), so a paper exit **grows** the position
instead of closing it. The `simulate_fills`-after-exits call (`runner.py`) was
added only to release the one-in-flight guard; the position growth is an
unintended side effect.

Consequence: in the shadow-paper proof, exits never close positions, no real
round-trips occur, and held-to-settlement scores **inflated** positions. Any
round-trip-PnL work (0003) built on this would double-count and inflate the
promotion gate's PnL — the real-money go-live criterion. This must be correct
first.

## Root cause

Neither `orders` nor `working_orders` records trade direction, and
`simulate_fills` has no concept of buy vs sell — it assumes every fill is a buy.

## Scope

- **`kaiju/state.py`** — add an `action` column to the `orders` table (values
  `"buy"` / `"sell"`), with an idempotent migration for existing DBs;
  `record_order` gains an `action` parameter (default `"buy"`).
- **`kaiju/execution/position_manager.py`** — `execute_entries` records
  `action="buy"`; `execute_exits` records `action="sell"`.
- **`kaiju/execution/paper_sim.py`** — `try_fill` gains a sell mode (marketable
  when `limit <= top-of-book`, mirror of buy); `simulate_fills` reads the
  order's action via `state.get_order(client_id)` and, for a sell, **reduces**
  the position (count down by the fill qty, remaining avg unchanged; closed at 0)
  instead of accumulating. The sell fill is still recorded via `record_fill`.
- **Conflict scope:** state schema + position_manager + paper_sim. Overlaps
  0002's `paper_sim.py` (sequenced after it; already merged on this branch).

## Acceptance criteria

- Failing test first: buy N then sell N (full exit) leaves the position
  **closed** (count 0), not grown to 2N. Cover a partial sell too (sell M < N →
  count N-M, avg unchanged).
- Entries still accumulate (regression: existing `simulate_fills` buy tests pass
  unchanged).
- `orders.action` round-trips; migration adds the column to a pre-existing
  `orders` table and is idempotent.
- `make check` green. No gate/PnL logic changed here (that is 0003); this task
  only makes the position correct. Direction is now recoverable from the orders
  ledger, which 0003 will use for round-trip PnL.

## Out of scope

Round-trip realized PnL in `settle_day` (that is **0003**, now unblocked).
Live WS fill recording (live fills are not persisted to `fills` at all — a
separate gap). The exact sell-price microstructure beyond the simple
top-of-book model.

## Danger-zone check

Touches `state.py`, `position_manager.py`, `paper_sim.py`. Does NOT touch
`risk/`, `eval/gate.py`, `config.py` live path, `parser._SETTLEMENT_MAP`,
`notes/`, or rail files.

> ☑ Confirmed no danger-zone changes

## Definition of done

Per `CONTRIBUTING.md` — all six conditions.
