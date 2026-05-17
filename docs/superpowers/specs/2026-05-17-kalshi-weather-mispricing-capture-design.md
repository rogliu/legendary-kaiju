# Kalshi Weather Mispricing-Capture Bot — Design Spec (v2)

**Date:** 2026-05-17
**Status:** Approved design, pending spec review
**Supersedes:** `docs/superpowers/specs/2026-05-16-kalshi-weather-trading-bot-design.md`
**Codename:** legendary-kaiju (package: `kaiju`)

## 0. Why v2

v1 placed a directional bet on a mispriced temperature bucket and passively
held to same-day settlement. That throws information away: even when the model
is right on average, each binary still resolves 0/100 (pure variance) and
capital is locked until end of day.

v2 reframes the model as a **continuously-updated fair price per bucket** and
trades the *gap* between live market price and fair value: take the cheap side
when the gap clears round-trip cost, close when the market converges back to
fair. Hold-to-settlement becomes a bounded-risk *fallback*, not the plan. Same
expected edge, materially lower variance, faster capital recycling, and a
stepping stone toward true market-making later.

## 1. Goal and constraints (unchanged from v1)

- **Bankroll:** small ($100–$1k). Round-trip fees/spreads matter; trade only
  sizable mispricings.
- **Autonomy:** build + paper-proof fully autonomous; live trading only after
  an objective promotion gate passes *and* a one-time human arm switch.
- **Stack:** Python core; Rust deferred.
- **Runtime:** runs on the user's Mac first, portable unchanged to a
  same-region (us-east-1) small EC2 later.

## 2. Predictand and data (unchanged core; SPIKE-verified)

Settlement predictand: the **official NWS daily maximum temperature** (integer
°F) for the contract's station and climate day. Verified contracts live in
`docs/superpowers/notes/` and are authoritative:

- Kalshi NYC daily-high series: **`KXHIGHNY`**; settles on **Central Park**,
  climate day = local midnight–midnight **America/New_York**
  (`kalshi-api-contract.md`, `settlement-map.md`).
- Forecast: **NBM probabilistic max-temp percentiles** via Herbie
  `model="nbmqmd"` (NOT the v1-guessed `product="co"`), plus **GEFS** 31-member
  ensemble (`noaa-forecast-contract.md`).
- Observations / settlement truth: **IEM** station `NYTNYC`, network
  `NYCLIMATE`, `max_tmpf` (`settlement-map.md`). Verified to match Kalshi
  `expiration_value` on a real settled day.
- Kalshi fee formula coefficient remains **UNVERIFIED** (PDF rate-limited in
  SPIKE) — pinned to recorded contract, cross-check against a live demo fill.
- Kalshi `*.5` bracket strikes must be converted to correct inclusive integer
  `Bucket` bounds (Task-20 hazard recorded in project memory).

## 3. Fair-value engine

Two layers; layer A already built (Tasks 12–13), layer B is new.

**A. Calibrated forecast PMF (built).** NBM percentiles → monotone CDF, blended
NBM-heavy with GEFS, then low-parameter bias/spread correction with shrinkage
→ calibrated integer-°F PMF of the official daily max.

**B. Nowcast updater (new).** Given today's observed temps so far (IEM/METAR),
condition the daily-max PMF on:
1. **Running-max floor:** the max observed temperature so far is a hard lower
   bound on the daily max — PMF mass for temperatures strictly below it is
   removed and the distribution renormalized (a left-truncation at the
   observed max; the bucket spanning that value absorbs the residual). No
   artificial point mass is added.
2. **Post-peak collapse:** after the station's typical afternoon peak hour,
   remaining upside shrinks toward zero; the PMF concentrates on
   `max(observed_so_far, short-horizon forecast remaining high)`.

Output: **fair price per bucket = 100 × P(bucket)** in cents, recomputed on a
timer through the trading window so it sharpens predictably as the day
progresses. This is the safety-critical property: it lets the bot distinguish
*market is mispriced* (trade it) from *market correctly moved on new
information* (do not fight it).

## 4. Entry / exit policy

Reuses the existing edge + capped fractional-Kelly machinery (Tasks 10–11),
generalized to act on the price-vs-fair gap and made position-aware.

- **Entry:** `|fair − market|` exceeds a threshold that already nets out
  fee + half-spread + safety margin, and book depth is sufficient → take the
  cheap side. Size with capped fractional Kelly at the city-day event level,
  **position-aware** (size the delta; never double-up a held position).
- **Exit — convergence:** when market price comes within an exit-margin of
  *current* fair value → close via a limit at `fair ∓ fill-margin` (priced to
  actually fill on thin books).
- **Exit — thesis invalidation:** if a freshly recomputed fair value moves
  through the entry level (the market was right, our prior fair was stale),
  cut the position. Never average down on a stale target.
- **Exit — time-stop:** after a configurable pre-settlement cutoff, stop
  opening; any remainder that will not fill at an acceptable price is **held to
  settlement** — the bounded-risk fallback (max loss capped by the binary
  payoff).
- **Cost discipline:** maker-preferred limit placement (lower maker fee); only
  act when captured convergence comfortably exceeds 2 × (fee + half-spread).

## 5. Runtime architecture — WebSocket event loop with safety net

A Kalshi WebSocket client subscribes to order-book + fills for the active
event's markets. It is never trusted bare:

- Auto-reconnect with exponential backoff; heartbeat liveness check.
- On every (re)connect: REST snapshot of book + positions + fills to reconcile
  authoritative state.
- Two independent timers alongside the stream:
  - **Fair-value recompute timer:** pull latest forecast + nowcast every N
    minutes regardless of stream activity.
  - **Safety/settlement timer:** force an evaluation near the time-stop /
    settlement even if the stream is silent.

Event flow: book/fill event or timer tick → recompute fair → per-market gap →
**hard risk gate** → place / cancel / replace orders. Daily lifecycle wraps it:
discover event (settlement-map) → open stream → trade window → close stream →
existing `settle_day` → `retrain` → promotion `gate`.

## 6. Execution / position manager

Position-aware manager tracking, per market: net position, average entry,
current fair, target exit, working orders. Maker-preferred limit placement;
cancel/replace as fair drifts; partial-fill aware; idempotent client order IDs;
reconciles against Kalshi positions/fills on (re)connect. Every order passes
the hard risk gate before transmission.

Risk gate (extends Task 15): global kill switch (config + flag file); caps on
per-position size, aggregate open exposure, max markets, bankroll fraction;
daily-loss day-stop; round-trip-aware (refuse churn that bleeds fees). Pre-trade
sanity gates: stale/missing forecast or nowcast, degenerate PMF, unexpected
market structure, clock skew, balance below floor. Governing rule: **if in
doubt, don't trade.**

## 7. Run modes and promotion gate

Same discipline: `backtest` → `shadow-paper` → (gate) → one-time human arm →
`live`. Changes:

- **Shadow-paper** now simulates **intraday fills against the live production
  book through the day** (entries and convergence exits), not a single
  end-of-day fill. Sends nothing.
- **Gate metrics** add: realized round-trip net PnL, fill rate, mean adverse
  excursion, and fraction of positions exited early vs. held to settlement —
  in addition to forecast calibration (Brier/CRPS/PIT) and net PnL.
- **One-time real-money arm switch** unchanged: gate qualification makes live
  *eligible*; a single durable human authorization is still required before
  any real order; hands-off thereafter.

## 8. Module / architecture map (revised)

| Module | Status |
|---|---|
| `types`, `config`, `state`, `logging` | built (Tasks 1–4) |
| `strategy/fees` | built (Task 8) |
| `model/distribution`, `model/calibration` | built (Tasks 12–13) |
| `data/forecast` (NBM `nbmqmd` + GEFS), `data/obs` (IEM) | per recorded contracts (Tasks 17–18) |
| `markets/kalshi_client` (REST: orders/positions/snapshot) | per recorded contract (Task 19) |
| `markets/parser` (event/buckets; `*.5`→int bounds) | (Task 20) |
| `strategy/edge`, `strategy/sizing` | built; **generalized** to gap-to-fair, position-aware |
| `model/nowcast` | **new** — observed-temp conditioning of the PMF |
| `markets/ws_client` | **new** — WebSocket book/fills + reconnect + REST reconcile |
| `execution/position_manager` | **new/replaces** the v1 "hold to settlement" order manager |
| `strategy/exit_policy` | **new** — convergence / thesis-invalidation / time-stop |
| `risk/limits` | built-target; extended round-trip-aware |
| `runner` | **upgraded** — intraday event loop + timers + daily lifecycle |
| `eval/metrics`, `eval/gate` | built-target; metrics extended |
| intraday shadow-paper fill simulator | **new** |

State remains a single SQLite file (positions, fills, working orders,
predictions, pnl, gate). Deployment unchanged: Docker image, launchd/cron
trigger on Mac, same container on a same-region EC2 later (the daily lifecycle
process is long-running for the trading window, then exits).

## 9. Impact on work already done (Tasks 1–11)

Extension, not restart:

- **Keep as-is:** types, config, state, fee model, the three verified SPIKE
  contracts, distribution + bias-calibration. The **pending Task 11 code-review
  fixes** (rename `_kelly_fraction`→`_has_positive_edge`; fail-loud
  `ValueError` + Pydantic `gt=0,le=1` guards on `kelly_fraction` /
  `max_bankroll_frac_per_event`; sizing test gaps) are carried into the revised
  plan and applied.
- **Generalized (not discarded):** `edge.select_trades` and `sizing.size_event`
  → gap-to-fair, position-aware; same math, new inputs.
- **Replaced/expanded:** simple order manager → position/exit manager;
  once-daily runner → intraday event loop; REST-only client gains a WebSocket
  client (REST retained).
- **New:** `model/nowcast`, `markets/ws_client`, `strategy/exit_policy`,
  intraday shadow-paper simulator.

## 10. Accepted trade-offs / verify-at-implementation

- WebSocket adds real live-failure surface (drops, partial fills, reconnect
  races) → mitigated by reconnect/heartbeat, REST reconcile, independent
  timers, and the unchanged paper-proof gate (which matters *more* here).
- Convergence is not guaranteed and the market converges to truth, not to our
  model → mitigated by the nowcast (fair value tracks latest reality),
  thesis-invalidation exit, and the bounded hold-to-settlement fallback.
- Round-trip fee/spread drag on a small bankroll → only trade sizable
  mispricings; maker-preferred; explicit 2×cost hurdle.
- Thin-book exits may not fill at target → limit at fair ∓ fill-margin, partial
  fills accepted, unfilled remainder held to settlement.
- Nowcast modeling risk (peak-hour climatology, observation latency/estimated
  flags) → verify against IEM `tmpf_est` handling; treat estimated values
  cautiously.
- Kalshi fee coefficient + WebSocket message schema verified against live
  docs/demo at implementation; `.env` RSA key should be rotated by the user.

## 11. Out of scope (v2, YAGNI)

- Full market-making (continuous two-sided quoting, inventory/adverse-selection
  optimization) — this design is the stepping stone, not that.
- Multi-city scale-out before single-city (KNYC) proof.
- ECMWF ensemble; Rust hot path; multi-day markets; WebSocket for anything
  beyond book/fills (orders stay REST).
- Notifications/alerting beyond on-disk reports.
