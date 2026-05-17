# Kalshi Weather Trading Bot — Design Spec

> **SUPERSEDED (2026-05-17)** by
> `docs/superpowers/specs/2026-05-17-kalshi-weather-mispricing-capture-design.md`
> (v2: mispricing-capture / converge-to-fair strategy, WebSocket intraday loop,
> nowcast fair value). Retained for history. Tasks 1–11 built under this v1
> remain valid and are carried forward per the v2 spec §9.

**Date:** 2026-05-16
**Status:** Superseded by v2
**Codename:** legendary-kaiju (package: `kaiju`)

## 1. Goal

An autonomous bot that trades Kalshi daily city-temperature markets for positive
expected value. Built and proven hands-off; one deliberate human authorization at
the real-money boundary; autonomous thereafter.

Constraints driving the design:

- **Bankroll:** small ($100–$1k). Fees and edge quality matter more than volume.
- **Autonomy:** build and paper-proof fully autonomous; live trading begins only
  after an objective promotion gate passes *and* a one-time human arm switch.
- **Stack:** Python core; Rust deferred until a measured bottleneck appears.
- **Runtime:** runs on the user's Mac first (launchd/cron), portable unchanged to a
  same-region (us-east-1, near Kalshi + free NOAA S3) small EC2 later.

## 2. What we are predicting

Kalshi daily city-temperature events are sets of **mutually-exclusive bracket
binary markets** (≈2°F buckets with open-ended tails, e.g. "NYC high 56–57°F
today"). They **settle on the official NWS daily-maximum temperature** for a
specific station over a specific climate-day window defined in each contract's
rules — *not* a rolling METAR maximum. NWS rounding, the climate-day boundary,
and QC differ from raw METAR.

Therefore the predictand is exactly **the integer-°F official NWS daily maximum
for the contract's station and climate day**. Bias correction trains against that
same official series.

The exact series tickers, bucket edges, settlement station, and climate-day
window are **read from the live Kalshi contract rules / API at runtime, never
hardcoded.** Any per-series fee *parameters* Kalshi exposes via the API are read
at runtime; the fee *formula itself* is encoded from Kalshi docs and pinned with
tests (Section 12). Verifying the current fee formula and RSA request-signing
spec against live docs is an explicit implementation task.

## 3. Data sources (all free)

**Forecast:**
- **NBM (National Blend of Models)** — anchor signal. Publishes already-calibrated
  probabilistic max-temperature percentiles. Best low-overfitting signal given
  limited history.
- **GEFS** (31-member ensemble) — layered on for tail/spread shape.
- Both via the `Herbie` library from NOAA's free AWS buckets (NODD). S3 reads are
  free and fast from a same-region EC2 later.
- ECMWF open-data ensemble — deferred, swappable in behind the distribution
  interface.

**Observations:**
- **IEM (Iowa Environmental Mesonet)** official NWS daily-max / CF6 climate series
  — bias-correction training truth and settlement verification.
- `api.weather.gov` NWS CLI — cross-check.

**Trading:**
- Kalshi REST API (prod). RSA request signing with the account key. WebSocket
  deferred; daily cadence is fine with REST polling.

## 4. The edge pipeline

1. NBM max-temp percentiles → monotone CDF over integer °F; blend with the GEFS
   empirical CDF (NBM-heavy; blend weights configurable).
2. A deliberately **low-parameter** correction on top: a seasonal/station bias
   term plus a spread-calibration factor derived from PIT / rank-histogram
   coverage, **shrunk toward zero-bias / unit-spread when the sample is small.**
   Low-parameter by design — appropriate for limited data and the explicit
   "don't overfit" goal.
3. Integrate the resulting calibrated PMF over each live Kalshi bucket (including
   open tails) → model probability per market. Renormalize across the
   mutually-exclusive set; flag structure mismatches.
4. Trade only where divergence beats **bid-ask spread + the exact Kalshi fee + a
   safety margin** (net-edge threshold ≈7–10¢, tuned conservatively for a small
   bankroll). Bias toward mispriced **tail** buckets where retail crowding and
   NBM-naive pricing diverge most.

Buckets within one city-day are correlated, so risk is sized at the **city-day
event level**, not naively per bucket.

**Honest premise:** if the market already perfectly tracks NBM, the edge is thin.
The paper-proof gate exists to catch exactly that before real money moves. If it
fails, it fails — the bot does not trade real money.

## 5. Run modes

One code path, mode-switched:

- **`backtest`** — light obs-only historical sanity check.
- **`shadow-paper`** — reads *live production* market data and order book,
  simulates realistic fills against that real book, transmits nothing. More
  faithful than Kalshi's separate demo environment (which has thin/synthetic
  liquidity). Demo used only for one-time API/auth wiring tests.
- **`live`** — transmits real orders. Reachable only after the promotion gate
  passes and the one-time human arm switch is set.

## 6. Execution

- Limit orders at / just inside the touch; idempotent client order IDs.
- Every run reconciles open orders and positions from Kalshi *and* local state —
  safe across crashes and re-runs (idempotent daily job).
- Default exit: **hold to same-day settlement** (weather resolves that day;
  avoids churn and extra fees). Take-profit/stop deferred (YAGNI for v1).

## 7. Risk controls (enforced in code, before any order)

Hard caps, all in config:

- Max daily loss → day kill.
- Max total open exposure.
- Max contracts per market; max markets per day.
- Max bankroll fraction deployed.
- Conservative fractional Kelly (default ≈0.25), sized at the city-day event
  level (correlated buckets).

Global **kill switch** (config value + flag file): cancels everything, trades
nothing. Pre-trade sanity gates refuse to trade on: stale/missing forecast data,
degenerate model PMF, unexpected market structure, clock skew, or account balance
below floor.

Governing rule: **if in doubt, don't trade.**

## 8. Promotion gate — the meaning of "autonomous after paper proof"

Run `shadow-paper` for a fixed window (≈30 trading days, configurable). Measure:

- **Forecast calibration:** Brier, CRPS, reliability / PIT vs official max.
- **Strategy result:** full simulated net-of-fee PnL with real sizing/fee logic.

Preset pass criteria (in config): calibration beats the market-implied baseline,
PIT approximately uniform, positive net PnL over a minimum trade count, max
drawdown within bound.

- **Pass:** bot writes a `LIVE_APPROVED` snapshot with the metrics. Live trading
  becomes *eligible* but is gated behind the **one-time human arm switch**
  (Section 9). Once armed, live starts at reduced size with a ramp.
- **Fail:** stays in paper, emits a report, may self-tune thresholds within
  preset bounds, continues. No human action required.

Reports are written for user visibility only; no human action is required to
operate the paper phase.

## 9. Human authorization boundary

Three things are irreducibly human and intentionally not automated:

1. **Funding** — the Kalshi account must hold money.
2. **One-time real-money arm switch** — promotion auto-qualifies the model, but
   crossing from simulated to real dollars requires one durable authorization
   from the user (a single explicit switch, e.g. a config flag + confirmation
   token), not per-trade feedback. Rationale: moving real money is irreversible
   and outward-facing; the bot must not cross that boundary on its own judgment.
   After it is set once, operation is hands-off again. **Default in this design;
   the user may veto this gate and choose full auto-promotion at spec review.**
3. **RSA key rotation** — the user's account credential. The plaintext key
   currently in `.env` should be rotated.

Everything else — building, testing, external-fact verification, the paper-proof
run, ongoing live operation once armed — runs without user feedback.

## 10. Architecture

Python, 12-factor, container-portable. Package `kaiju/` with focused,
independently-testable modules:

| Module | Responsibility |
|---|---|
| `config` | Config + secrets from `.env`/yaml; modes; all thresholds and limits. |
| `data/forecast` | Herbie-based NBM/GEFS fetch; station extraction; cache. |
| `data/obs` | IEM/NWS official daily-max fetch. |
| `model/distribution` | Ensemble → CDF; NBM/GEFS blend. |
| `model/calibration` | Low-parameter bias/spread correction; trainer + store; shrinkage. |
| `markets/kalshi_client` | RSA auth signing; REST; retry/backoff. |
| `markets/parser` | Discover series/events; parse bucket edges; settlement station/window from contract rules. |
| `strategy/edge` | Model P per bucket; exact fee model; EV; trade selection. |
| `strategy/sizing` | Capped fractional Kelly at city-day level. |
| `execution/orders` | Order manager; modes; reconcile; idempotent. |
| `risk/limits` | Hard limits + kill switch; pre-trade gate. |
| `eval/metrics` | Brier/CRPS/reliability/PnL; promotion-gate evaluator. |
| `runner` | Idempotent daily entrypoint orchestrating one full cycle; structured logging. |

**State:** a single **SQLite** file (forecasts, obs, predictions, market
snapshots, orders, fills, PnL, gate status) — portable; later swappable to RDS
via a DSN change.

**Deployment:** `Dockerfile` + `Makefile`. Triggered by launchd/cron on the Mac
now; the *same container* on a same-region small EC2 later — only the trigger
moves, not the code.

**Testing (TDD throughout):** unit tests pin the Kalshi fee formula against
Kalshi's published examples, bucket-integration / PMF sums and tails, Kelly caps,
and that the risk gate actually blocks. A deterministic replay test covers the
runner.

**Observability:** structured JSON logs plus a daily human-readable report
(forecast vs market, trades, PnL, gate status) written to disk. Notifications
deferred.

## 11. Execution model for building this

After spec approval: `writing-plans` produces the implementation plan, then
execution proceeds via **subagent-driven development with parallel agents**. Each
module is built test-first; agents verify their own work against the tests;
progress continues only when checks pass. The user reviews code only if they
choose to.

## 12. Accepted trade-offs and verify-at-implementation items

- Deep historical backtesting is limited (archived NBM/GEFS at the needed cadence
  is hard) → primary proof is forward shadow-paper, with a light obs-only
  historical sanity check. Accepted.
- Kalshi fee formula, RSA request-signing spec, and per-city settlement
  station/window are verified against current Kalshi docs / contract rules at
  implementation and pinned with tests.
- Small bankroll + 1-contract granularity + fees may yield few trades.
  Selectivity is intended, not a defect.
- First implementation step adds `.gitignore` covering `.env`; the user should
  rotate the currently-plaintext RSA key.
- Legal/eligibility/tax for the Kalshi account is the user's responsibility; the
  bot enforces only its own risk limits.

## 13. Out of scope (v1, YAGNI)

- Market making / passive spread capture (thin books; revisit post-proof).
- Intraday take-profit/stop logic.
- ECMWF ensemble (swappable in later).
- WebSocket order-book streaming.
- Rust hot path.
- Multi-city scale-out before single-city proof.
- Notifications/alerting beyond on-disk reports.
