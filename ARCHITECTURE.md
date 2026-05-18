# ARCHITECTURE — the system as it is now

The map an agent reads before touching code. Intent/history lives in
`docs/superpowers/specs/`; this describes the *current* system. Rules you
cannot break: `docs/INVARIANTS.md`.

## One sentence

A single long-running intraday process trades **one** Kalshi market (NYC
daily-high `KXHIGHNY`) by computing a continuously-updated fair price per
temperature bucket and trading the gap between fair and the live book,
closing on convergence — with hold-to-settlement as a bounded fallback.

## Data flow (one trading day)

```
discover event (markets/parser ← docs/superpowers/notes/settlement-map)
  → open WS stream: book + fills (markets/ws_client)  +  two timers
  → recompute fair value:
        data/forecast (Herbie NBM %iles + GEFS)        [SEAM]
          → model/distribution (→ CDF, NBM/GEFS blend)  [SEAM]
          → model/calibration (bias/spread + shrinkage) [SEAM]
          → model/nowcast (observed-temp conditioning)  [SEAM]
          → strategy/fairvalue (PMF → cents per bucket)
  → per-market gap → strategy/edge.select_gap_trades    [SEAM]
          → strategy/sizing (capped fractional Kelly, city-day level)
          → risk/limits.RiskGate.check  (fail-closed, pre-trade)  [DANGER]
          → execution/position_manager (place/cancel/replace; idempotent)
                 shadow-paper: execution/paper_sim simulates fills
  → exits: strategy/exit_policy.decide_exit              [SEAM]
  → at day end: runner.settle_day → retrain_calibration → eval/gate  [DANGER]
```

`runner.py` orchestrates all of the above (`run_intraday`, the deterministic
`run_intraday_once`, `settle_day`, `retrain_calibration`, the CLI).

## Module map (`kaiju/`)

| Module | Responsibility |
|---|---|
| `types.py` | `TempPMF` (immutable, validated), `Bucket`, `MarketQuote`, `TradeIntent`, `Position`, `ExitDecision`/`ExitAction`, `EventSnapshot`, `RiskDecision` |
| `config.py` | `Settings` (frozen, `SecretStr` secrets, `_live_guard`, `live_armed`) — **DANGER (live path)** |
| `state.py` | SQLite DAL: predictions, orders, fills, pnl, gate, positions, working_orders, calibration, settlements |
| `logging.py` | structured logging (configured once) |
| `data/forecast.py` | Herbie NBM (`nbmqmd` %iles) + GEFS member fetch |
| `data/obs.py` | `IEMClient`: `official_daily_max` (settlement), `observed_max_so_far` (nowcast) |
| `model/distribution.py` | percentiles → monotone CDF; NBM/GEFS blend — **SEAM** |
| `model/calibration.py` | low-param bias/spread + shrinkage; `fit_calibration`/`apply_calibration` — **SEAM** |
| `model/nowcast.py` | condition the PMF on observed temps (running-max truncation, post-peak) — **SEAM** |
| `strategy/fairvalue.py` | calibrated PMF + buckets → fair cents per market |
| `strategy/edge.py` | `select_gap_trades` (gap-to-fair, position-aware) — **SEAM** |
| `strategy/sizing.py` | `size_event` — capped fractional Kelly at city-day level |
| `strategy/exit_policy.py` | `decide_exit` — convergence / thesis-invalidation / time-stop — **SEAM** |
| `strategy/fees.py` | exact Kalshi fee model (coefficient flagged UNVERIFIED) |
| `risk/limits.py` | `RiskGate` — fail-closed pre-trade gate — **DANGER** |
| `eval/metrics.py` | `crps_pmf`, `pit_value`, drawdown helpers |
| `eval/gate.py` | `evaluate_promotion`, `GateCriteria`/`GateResult`, `can_trade_live` — **DANGER** |
| `markets/kalshi_client.py` | RSA-PSS auth signing, REST (orders/positions/snapshot), retry/backoff |
| `markets/parser.py` | `resolve_settlement`, `_SETTLEMENT_MAP`, `parse_event_snapshot`, `*.5→int` band — **DANGER (`_SETTLEMENT_MAP`)** |
| `markets/ws_client.py` | WebSocket book/fills + reconnect/backoff + REST reconcile |
| `execution/position_manager.py` | position-aware order/exit manager; one-in-flight-per-market guard; idempotent IDs |
| `execution/paper_sim.py` | `PaperBook`, `simulate_fills` — shadow-paper intraday fills |
| `runner.py` | intraday loop + timers + daily lifecycle + CLI |

## The pluggable seams (where parallel work scales)

These five interfaces are the surfaces a loop/experiment-agent improves
*independently*. Keep the signature; add a competing implementation; let
`eval/gate` score it. See `docs/agents/EXPERIMENTS.md`.

- `model/distribution` — `pmf_from_nbm_percentiles`, `blend_pmfs`
- `model/calibration` — `fit_calibration`, `apply_calibration`
- `model/nowcast` — `nowcast_pmf`
- `strategy/edge` — `select_gap_trades`
- `strategy/exit_policy` — `decide_exit`

## Danger zones (human-only — see `docs/INVARIANTS.md` bottom)

`kaiju/risk/`, `kaiju/eval/gate.py`, `kaiju/config.py` (live path),
`kaiju/markets/parser.py` (`_SETTLEMENT_MAP`), `docs/superpowers/notes/`,
and the rail files (`docs/INVARIANTS.md`, `tests/test_scope_lock.py`,
`AGENTS.md`, `docs/agents/LOOP.md`). A task that needs these → Stop &
Escalate.

## State & deploy

Single SQLite file (path = `Settings.db_path`). Deploy: Docker image,
launchd/cron on Mac → same container on a same-region (us-east-1) EC2 for
the qualifying window and live. The daily process is long-running for the
trading window, then exits.
