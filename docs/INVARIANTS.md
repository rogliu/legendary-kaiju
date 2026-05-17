# INVARIANTS — the inviolable contract

This is a real-money-capable trading system. These invariants are the rails
that make unsupervised iteration safe. **Each one is enforced by a test.** For
an autonomous loop, a guardrail that isn't a test is not a guardrail — so every
row below names the test that fails if the invariant breaks.

## The prime rule

> If you believe you need to weaken, delete, or work around any invariant
> below — **STOP. Do not.** That is an escalation to a human, never an
> autonomous change. A failing invariant test is the alarm working correctly;
> the response is to fix your change, not to silence the test.

Never make the gate pass by deleting a test, loosening an assertion, editing an
invariant, or touching a danger-zone file (see bottom). `make check` green is a
*precondition* for merge, not a target to game.

---

## A. Money & live-trading safety

These prevent real financial loss. Highest severity. Most encode a bug that was
actually caught during the build — they are scars, not theory.

| # | Invariant | Enforced by |
|---|-----------|-------------|
| A1 | **Single market only.** Trading scope is exactly NYC `KXHIGHNY` (Central Park). The config default, the settlement allowlist, and the station→series map are all frozen to NYC. Multi-city is out of scope until the single-city proof qualifies. | `tests/test_scope_lock.py` (all 5) |
| A2 | **`live` mode requires a non-empty arm token.** `Settings._live_guard` rejects `mode=live` with no `KAIJU_LIVE_ARM_TOKEN`. Whitespace is not a token. | `tests/test_config.py::test_live_requires_arm_token`, `::test_whitespace_arm_token_not_armed` |
| A3 | **`can_trade_live` hard interlock.** Live orders require the promotion gate status == `qualified` **and** armed. `run_intraday` raises `SystemExit` if not (belt-and-suspenders over A2). | `tests/eval/test_gate.py::test_can_trade_live_false_false`, `::test_qualifies_and_arm_required`; wiring in `kaiju/runner.py` `run_intraday` `if mode == "live"` block |
| A4 | **shadow-paper / backtest transmit nothing.** No real order ever leaves these modes; fills are simulated against the live book. | `tests/execution/test_position_manager.py::test_shadow_paper_records_not_sends` |
| A5 | **Live sends are idempotent.** Send-once with stable client order IDs; a re-run never double-submits. | `tests/execution/test_position_manager.py::test_live_sends_once_idempotent` |
| A6 | **Risk gate is fail-closed and pre-trade.** Every order passes `RiskGate.check` first. Empty kill-switch path is rejected at construction; the kill switch wins over all other limits; daily-loss, exposure cap, bankroll-net-of-exposure, zero-after-clamp, and price-range all block. In doubt → reject. | `tests/risk/test_limits.py::test_kill_switch_blocks`, `::test_empty_kill_switch_path_rejected_at_construction`, `::test_kill_switch_wins_even_when_other_limits_breached`, `::test_daily_loss_blocks`, `::test_exposure_cap_blocks`, `::test_bankroll_accounts_for_open_exposure`, `::test_zero_after_clamp_is_rejected_not_approved`, `::test_price_out_of_range_blocked` |
| A7 | **One in-flight order per market.** No oversell, no entry burst; the per-market guard is released only on fill/clear. | `tests/execution/test_position_manager.py::test_exit_not_reissued_while_working_order_open`, `::test_entry_burst_guarded_to_one_per_market`, `::test_clear_working_orders_for_market_releases_guard` |
| A8 | **Promotion gate is fail-closed and real.** Real CRPS vs a uniform-climatology baseline + PIT KS uniformity. Non-finite metric → fail. <5 PIT points → p=0 (fail). It is the only thing that lets you trust an unsupervised contribution — its integrity is itself an invariant. | `tests/eval/test_gate.py::test_gate_fails_closed_on_non_finite_metric`, `::test_fails_on_negative_pnl_or_low_fill_or_few_days`, `::test_gate_boundaries_at_threshold` |

## B. Correctness — break these and the proof is silently invalid

| # | Invariant | Enforced by |
|---|-----------|-------------|
| B1 | **Settlement vs nowcast station seam.** Settlement daily-max uses `iem_station`/`iem_network` (`NYTNYC`/`NYCLIMATE`); intraday nowcast uses `asos_station`/`asos_network` (`NYC`/`NY_ASOS`). Same physical site, different identifiers — never conflate or repoint. (This exact seam was a CRITICAL bug caught in final review: nowcast wired to the wrong station ran never.) | `tests/test_runner_nowcast_wiring.py`, `tests/markets/test_parser.py`, `tests/test_scope_lock.py::test_locked_series_resolves_to_verified_identifiers` |
| B2 | **`resolve_settlement` never guesses.** Unmapped series raise `KeyError` loud; only IEM-cross-checked entries exist in the map. | `tests/test_scope_lock.py::test_non_locked_series_cannot_resolve_settlement`, `tests/markets/test_parser.py` |
| B3 | **Fee model pinned to the recorded Kalshi contract.** The fee coefficient is flagged **UNVERIFIED** and must be cross-checked against a live demo fill before live (GO-LIVE checklist). Do not change the formula casually. | `tests/strategy/test_fees.py` |
| B4 | **`*.5` strike → inclusive integer band.** `lower=ceil(floor_strike)`, `upper=floor(cap_strike)`; adjacent buckets never share an integer (no double-count). | `tests/markets/test_parser.py` |
| B5 | **`settle_day` is idempotent.** Re-running a settled day preserves persisted PnL and only refreshes the gate — it never clobbers real PnL with 0.0 (safe for cron retries). | `tests/test_settlement.py`, `tests/test_runner.py`; guard in `kaiju/runner.py::settle_day` |
| B6 | **`TempPMF` is immutable and validated.** Read-only array, no NaN, normalizes to 1. | `tests/test_types.py`, `tests/test_types_v2.py` |
| B7 | **`Settings` is frozen; secrets are `SecretStr`.** No runtime mutation; secrets never appear in `repr`/logs. | `tests/test_config.py::test_frozen_blocks_mutation`, `::test_secrets_not_in_repr` |

## C. Process invariants (the loop's own rails)

- **`make check` green is a hard precondition for any merge to `main`.** `main`
  must always be runnable — it is the proof harness.
- **Verified contracts in `docs/superpowers/notes/` are ground truth.** They
  encode externally-verified reality (Kalshi API/WS, NOAA, settlement map). Do
  not edit them without re-verifying against the live source; treat a needed
  change as an escalation.
- **One bounded change per iteration** (see `docs/agents/LOOP.md`). No "while
  I'm here" scope. DRY/YAGNI/TDD.

---

## Danger zones (human-escalation, never autonomous)

Changes touching these are off-limits to an autonomous loop and require a human
(this list is the basis for `CODEOWNERS`):

- `kaiju/risk/` — the pre-trade safety gate
- `kaiju/eval/gate.py` — the promotion gate (the trust referee)
- `kaiju/config.py` — `_live_guard`, `live_armed`, the live boundary
- `kaiju/markets/parser.py` — `_SETTLEMENT_MAP` / `resolve_settlement`
- `docs/superpowers/notes/` — the verified external-reality contracts
- `tests/test_scope_lock.py` and this file — the rails themselves

If a task appears to require editing any of the above, the loop **stops and
escalates** (see `docs/agents/LOOP.md` → Stop & Escalate).
