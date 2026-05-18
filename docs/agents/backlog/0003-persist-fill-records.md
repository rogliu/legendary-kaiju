# Task 0003 — persist fill records for round-trip PnL honesty

## Motivation

`kaiju/runner.py` `settle_day` documents: *"KNOWN LIMITATION: Intraday
round-trip realized PnL is NOT captured here because fill records are not
persisted (record_fill is absent in State v1). This means the gate's
sim_pnl_usd reflects ONLY held-to-settlement outcomes."* The strategy's
entire premise is convergence round-trips, so the gate currently *undercounts
exactly the PnL the strategy exists to produce*. Persisting fills makes the
proof honest.

## Scope

- **Owned module(s):** `kaiju/state.py` (add a `fills` table + `record_fill`
  + a reader); `kaiju/execution/position_manager.py` (record fills on
  fill/clear); `kaiju/runner.py` `settle_day` (include realized round-trip
  PnL from persisted fills in `realized_usd`).
- **Files expected to change:** the above + tests in `tests/test_state_v2.py`,
  `tests/execution/test_position_manager.py`, `tests/test_settlement.py`.
- **Conflict scope:** state schema + position_manager + settle_day. May
  overlap Task 0001 only if 0001 also edits runner — sequence after 0001 or
  coordinate file regions.

## Acceptance criteria

- Failing test first: a buy fill then a sell fill at a better price produces
  a positive realized round-trip PnL in `settle_day`'s `realized_usd`,
  distinct from held-to-settlement PnL.
- `record_fill` is idempotent on a stable fill id (no double-count on replay).
- Held-to-settlement scoring is unchanged for positions with no round-trip.
- `make check` green; settle idempotency invariant (B5) still holds.

## Out of scope — and a hard boundary

Do **not** change the promotion-gate criteria or logic. This task makes the
realized-PnL *input* complete; it must not touch `kaiju/eval/gate.py` or the
`GateCriteria` thresholds. **If completing this appears to require editing
`kaiju/eval/gate.py`, STOP — re-scope or escalate (that file is a danger
zone, invariant A8).**

## Danger-zone check

Touches `state.py`, `position_manager.py`, `runner.settle_day` — none are
danger zones. `eval/gate.py` is explicitly NOT touched.

> ☑ Confirmed no danger-zone changes (gate logic frozen; only PnL data source completed)

## Definition of done

Per `CONTRIBUTING.md` — all six conditions, plus invariant B5 (settle
idempotency) and A8 (gate untouched) explicitly re-verified.
