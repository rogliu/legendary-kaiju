# Kaiju — Kalshi Weather Temperature Trading Bot

**OPERATOR SAFETY DOCUMENT.** This bot trades real money. Read every section
before touching `KAIJU_MODE=live`.

---

## 1. What This Is

Kaiju is an autonomous bot that trades Kalshi daily city-temperature bracket
markets. It continuously builds a model fair value for each temperature bucket
by blending NOAA NBM `nbmqmd` percentiles and GEFS ensemble members, applies a
low-parameter bias calibration, and applies an intraday nowcast from live ASOS
observations. It then trades the gap between the live market price and that fair
value: enter the cheap side when the gap clears round-trip cost, close when the
market converges back to fair.

Three exit triggers (in priority order):

1. **Convergence** — the market price has moved back to within the exit margin
   of fair value.
2. **Thesis invalidation** — the nowcast has moved so far that the model no
   longer agrees the entry side is cheap.
3. **Time-stop** — the intraday window ends (30 minutes before local midnight)
   and entries cease; positions held past the time-stop fall through to
   hold-to-settlement.

**Hold-to-settlement is the bounded fallback**, not the plan. An open position
at end-of-day resolves at 0 or 100 cents (pure binary) against the official
Central Park NWS maximum.

**v1 scope:** Single city only — New York City (station identifier `NYC` or
`KNYC`; Kalshi series `KXHIGHNY`). Settlement uses the Central Park official
NWS Daily Maximum Temperature from the IEM `NYCLIMATE` network, station
`NYTNYC`. IEM values have been cross-checked against `KXHIGHNY` `expiration_value`
on settled markets and match exactly.

Authoritative design doc:
`docs/superpowers/specs/2026-05-17-kalshi-weather-mispricing-capture-design.md`

Verified external contracts:
`docs/superpowers/notes/` (Kalshi API, WS, NOAA, settlement map)

---

## 2. Setup

### Install dependencies

```
uv sync
```

### Configure secrets

```
cp .env.example .env
# edit .env and fill in the values below
```

Required variables (see `.env.example` for the full template):

| Variable | Required | Description |
|---|---|---|
| `KALSHI_KEY_ID` | Yes | Kalshi API key ID (UUID) |
| `KALSHI_PRIVATE_KEY` | Yes | RSA private key PEM string |
| `KAIJU_MODE` | No | `shadow-paper` (default), `backtest`, or `live` |
| `KAIJU_DB_PATH` | No | SQLite path (default: `./kaiju.sqlite`) |
| `KAIJU_BANKROLL_USD` | No | Trading bankroll in USD (default: 500) |
| `KAIJU_LIVE_ARM_TOKEN` | Only for live | One-time arm switch (see Section 5) |
| `KAIJU_CITIES` | No | Comma-separated station IDs (default: `KNYC`) |

Additional tuning variables (`KAIJU_NET_EDGE_THRESHOLD`, `KAIJU_KELLY_FRACTION`,
`KAIJU_MAX_BANKROLL_FRAC_PER_EVENT`, `KAIJU_MAX_EVENTS_PER_DAY`,
`KAIJU_MAX_CONTRACTS_PER_MARKET`, `KAIJU_MAX_DAILY_LOSS_USD`,
`KAIJU_PAPER_PROOF_DAYS`) are documented in `kaiju/config.py` with their
defaults.

> **SECURITY — ROTATE THE KEY BEFORE ANY LIVE USE.**
> The RSA private key that was placed in `.env` during development was committed
> in plaintext in the repository history. It MUST be rotated in your Kalshi
> account before this bot touches real money. `.env` is listed in `.gitignore`
> and must NEVER be committed. Generate a fresh API key pair at
> `kalshi.com/account/profile`, update `KALSHI_KEY_ID` and
> `KALSHI_PRIVATE_KEY`, and delete the old key.

---

## 3. Run Modes (`KAIJU_MODE`)

Set via the `KAIJU_MODE` environment variable or the `--mode` flag on the `run`
subcommand.

| Mode | Description |
|---|---|
| `backtest` | Offline replay against historical data; no network required. |
| `shadow-paper` | **DEFAULT.** Connects to the real live Kalshi book, computes fair values, simulates fills — sends NO orders to Kalshi. |
| `live` | Places real orders. Reachable only after the paper-proof gate qualifies **and** `KAIJU_LIVE_ARM_TOKEN` is set. Attempting `live` without the arm token causes `Settings` to raise `ValueError` at startup. |

**Shadow-paper is the proof phase.** Run it for at least 30 calendar days
accumulating real PMF predictions vs official settlements before considering
live. The paper-proof gate (Section 4) is the objective criterion.

---

## 4. CLI / Daily Lifecycle

### CLI reference

```
python -m kaiju.runner --help
python -m kaiju.runner run --help
python -m kaiju.runner settle --help
python -m kaiju.runner retrain --help
```

**`run`** — start the intraday trading loop (long-running; exits at time-stop):

```
python -m kaiju.runner run --station NYC [--mode shadow-paper|backtest|live]
```

`--mode` defaults to `shadow-paper`. `--station` is required.

**`settle`** — score yesterday's held-to-settlement positions and update the
gate:

```
python -m kaiju.runner settle --station NYC --date YYYY-MM-DD
```

`--date` is required (ISO format). Fetches the official daily max from IEM and
writes a `pnl` row and gate status to the SQLite state. If the official max is
not yet available (IEM not ready), the command exits non-zero with a clear
message — retry later.

**`retrain`** — fit bias/spread calibration from stored predictions vs
settlements:

```
python -m kaiju.runner retrain --station NYC [--db /path/to/kaiju.sqlite]
```

`--db` defaults to `Settings.db_path` (`./kaiju.sqlite`). The calibration is
written to the `calibration` table and applied on the next `run` invocation.

### Daily wrapper

`deploy/run_daily.sh` implements the full daily lifecycle in the correct order:

1. `settle YESTERDAY` (non-fatal — data lag is normal)
2. `retrain` (non-fatal — no data yet at startup is normal)
3. `run TODAY` (long-running intraday loop — failure surfaces)

To run manually:

```
KAIJU_CITY=NYC KAIJU_MODE=shadow-paper bash deploy/run_daily.sh
```

The script reads `KAIJU_CITY` (single station, for the `--station` flag) and
`KAIJU_MODE` from the environment. All other secrets are read by `kaiju.runner`
from the same environment or `.env`.

---

## 5. The Paper-Proof Gate

The gate is the objective criterion that must pass before `live` is eligible.
It is computed by `settle_day` after each settled day and persisted in the
`gate` table of the SQLite state (via `state.set_gate_status`).

### Gate metrics and thresholds

All metrics are computed over the trailing window of `climate_date`s that have
both a stored PMF prediction and a settled `pnl` row:

| Metric | Threshold | Pass condition |
|---|---|---|
| Days with paired prediction+settlement | `min_days = 30` | `days >= 30` |
| Trades | `min_trades = 15` | `trades >= 15` |
| Mean CRPS of model PMF vs realized official max | Must beat uniform baseline | `model_crps < baseline_crps` |
| PIT KS-test p-value | `min_pit_pvalue = 0.05` | `p >= 0.05` |
| Simulated PnL (held-to-settlement) | Positive | `sim_pnl_usd > 0` |
| Max drawdown | `max_drawdown_usd = 25.0` | `drawdown <= $25` |
| Fill rate | `min_fill_rate = 0.20` | `fill_rate >= 0.20` |

**CRPS baseline:** A uniform PMF over the observed temperature range for the
trailing window. The model must beat an uninformed uniform-climatology prior.

**PIT uniformity:** PIT values require at least 5 points; with fewer, the
p-value is set to 0.0 (fail-closed — insufficient data means the calibration
check cannot be trusted).

**Fill rate:** Currently a placeholder of 1.0 (see Section 9 — Limitations).

**Fail-closed:** Any non-finite metric, or the `not_ready` path from IEM,
returns `GateResult(qualified=False)`. The gate does not pass on ambiguous data.

### Where the verdict lives

`state.gate` table, written by `state.set_gate_status(status, brier, pnl)` at
the end of each successful `settle_day` call. Status is the string `"qualified"`
or `"not_qualified"`. Check it by querying the SQLite database directly or by
watching the `settle` command output.

```
sqlite3 kaiju.sqlite "SELECT * FROM gate ORDER BY updated_at DESC LIMIT 1;"
```

---

## 6. One-Time Arm Procedure + Go-Live Checklist

The go-live arm sequence is irreversible for the session. Work through every
item below before setting `KAIJU_MODE=live`.

### Go-Live Checklist

- [ ] **Account funded.** Kalshi account has real USD available for trading.

- [ ] **`KAIJU_LIVE_ARM_TOKEN` set.** Set this env var to any non-empty string
  in `.env` (or launchd `EnvironmentVariables`). This is the one-time arm
  switch. `Settings._live_guard` raises `ValueError` at startup if
  `mode=live` and the token is empty. Also set `KAIJU_MODE=live`.

- [ ] **Paper-proof gate shows `qualified`.** The gate SQLite row has
  `status="qualified"`. Do not skip this — the gate thresholds are the
  agreed objective criterion. This is now **programmatically enforced**:
  `run_intraday` calls `can_trade_live(qualified, armed)` before the trading
  loop; if the gate is not qualified or the arm token is missing, the runner
  raises `SystemExit` and refuses to place any live orders (fail-closed).

- [ ] **Daily-loss limit is active.** `KAIJU_MAX_DAILY_LOSS_USD` is set to a
  value you are willing to lose in a single day. The runner logs an `ERROR`
  level `UNSAFE: live mode with INERT daily-loss limit` message if the pnl
  table is not wired — do not ignore this log. Until `settle_day` has run
  at least once for today, the daily-loss check reads 0 from the pnl table
  (safe but conservative — it will start blocking once the row exists).

- [ ] **Live `get_positions` translation built and verified.** The `Position`
  object requires `{ticker, side, count, avg_entry_cents}`. The live Kalshi
  `get_positions` API response translation is a known TODO — reconciliation
  will not work correctly in live mode until this is implemented and verified
  against a real `get_positions` response. (verify before live)

- [ ] **Live demo auth smoke passes.** Run the bot against the Kalshi demo
  environment first. Confirm: the RSA key registered in Kalshi is the one in
  your `.env`; the WS signed path `/trade-api/ws/v2` authenticates successfully.
  Note: the `.env` key is likely a production key only — demo requires a
  separately generated demo key. (verify before live)

- [ ] **Kalshi fee coefficient confirmed against a real fill.** The bot uses
  a quadratic fee formula (`0.07 × C × (1 − C)` per contract) sourced from
  third-party documentation. The official Kalshi fee schedule PDF was
  rate-limited during research and could not be directly verified. The
  `fee_multiplier` field on the `KXHIGHNY` series interaction is also
  unverified. Confirm the formula matches the `fee_cost` field on a real fill
  response before relying on the net-edge calculation to be accurate.
  (verify before live)

- [ ] **Event-ticker format confirmed via live `list_events`.** The bot builds
  event tickers as `KXHIGHNY-{YY}{MON}{DD}` (e.g. `KXHIGHNY-26MAY17`).
  Confirm this format matches what `GET /events` returns for current-day
  events. (verify before live)

- [ ] **`.env` RSA key rotated.** See Section 2 Security note. The key
  committed in repo history must be revoked and replaced before live use.

- [ ] **`docker build .` succeeds AND `docker run <img> python -c "import cfgrib; from herbie import Herbie"` works.** The Dockerfile installs `libeccodes0`
  and `libeccodes-data` for GRIB decode. Verify the build succeeds and the
  runtime smoke-check passes — a missing eccodes definition file will cause a
  silent wrong-forecast failure, not a crash.

- [ ] **Mac launchd plist configured.** Edit
  `deploy/com.kaiju.daily.plist` before loading:
  - Set `ProgramArguments` to the absolute path of `deploy/run_daily.sh` on
    this machine (replace the `/REPLACE/WITH/ABS/PATH/` placeholder).
  - Set `EnvironmentVariables` with the absolute `PATH` that includes the
    directory where `uv` is installed (launchd does NOT inherit your shell
    PATH), plus all `KALSHI_*` and `KAIJU_*` secrets. Missing PATH causes a
    silent job failure.
  - Move `StandardOutPath` / `StandardErrorPath` off `/tmp` to a persistent
    log path (e.g. `~/Library/Logs/kaiju.daily.log`).
  - Install with `cp deploy/com.kaiju.daily.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.kaiju.daily.plist`.

- [ ] **SIGTERM / graceful shutdown verified.** Confirm that a launchd stop
  (`launchctl unload`) delivers SIGTERM to the Python asyncio loop and that
  `run_intraday` shuts down the WS cleanly. An abrupt kill mid-tick can leave
  working orders in an unknown state. (verify before live)

---

## 7. Kill Switch

To halt all trading immediately, create the kill-switch file:

```
touch /tmp/kaiju_kill
```

Every call to `RiskGate.check()` inspects `os.path.exists(kill_switch_path)`.
If the file exists, `check()` returns `RiskDecision(approved=False, reason="kill switch engaged")` and no order is placed. The next tick will also be blocked.

**Default path:** `/tmp/kaiju_kill` — set as the constant `_DEFAULT_KILL_PATH`
in `kaiju/runner.py`. The path is also hardcoded to this default in the
production `run_intraday` wiring.

To use a different path, set it via the `kill_switch_path` argument to
`run_intraday_once` (used in testing). In production `run_intraday`, the path
is `"/tmp/kaiju_kill"` and is not currently configurable via env var.

To re-enable trading after a kill:

```
rm /tmp/kaiju_kill
```

The bot will resume accepting orders on the next tick (within 60 seconds of
the file being removed).

---

## 8. Reading the Daily Report / State

### SQLite database

Default path: `./kaiju.sqlite` (override with `KAIJU_DB_PATH`).

Key tables:

| Table | Contents |
|---|---|
| `predictions` | Stored PMF predictions per `(station, climate_date)` |
| `orders` | Working and filled order records |
| `positions` | Open positions per market |
| `pnl` | Realized PnL per `(climate_date, mode)` — written by `settle_day` |
| `gate` | Latest gate status: `qualified` or `not_qualified`, with brier and pnl |
| `settlements` | Official daily max per `(climate_date, station)` |
| `calibration` | Stored bias/spread_scale calibration params per station |

Quick gate check:

```
sqlite3 kaiju.sqlite "SELECT status, brier, pnl, updated_at FROM gate ORDER BY updated_at DESC LIMIT 1;"
```

### Structured logs

The runner emits structured `logging` output at `INFO` and above. Log level
`WARNING` or `ERROR` indicates a safety or data-quality condition. The
`IEM observed_max not ready` line is `INFO` — it is a normal, expected
condition before afternoon observations accumulate and does not require
operator action. Watch for:

| Log level | Message pattern | Meaning |
|---|---|---|
| `WARNING` | `SAFETY: pnl/realized-loss source not yet wired` | Daily-loss limit is currently inert (always logged at startup). |
| `ERROR` | `UNSAFE: live mode with INERT daily-loss limit` | Running live without functional daily-loss protection — stop. |
| `INFO` | `IEM observed_max not ready` | Intraday nowcast skipped; using base PMF only. Normal/expected until afternoon observations accumulate. |
| `WARNING` | `NBM fetch failed` / `GEFS fetch failed` | Forecast source unavailable; trading tick may be skipped. |
| `ERROR` | `tick error; continuing` | An exception in one evaluation tick was caught and suppressed; check the traceback. |
| `WARNING` | `WS reconnect / backoff` | WS connection dropped and is retrying — normal, watch for frequency. |

Configure log output by setting the root logger before running, or rely on
`logging.basicConfig` in `__main__`.

---

## 9. Mac Now → us-east-1 EC2 Later

The same Docker image runs on Mac (Docker Desktop) and AWS EC2 without
modification.

**Run with Docker:**

```
docker build -t kaiju .
docker run --env-file .env kaiju run --station NYC
```

Secrets are provided at runtime via `--env-file .env`. They are NEVER baked
into the image — the Dockerfile explicitly does not copy `.env`.

**EC2 deployment notes:**

- Use `docker run --env-file .env -v /data/kaiju:/app/data kaiju run --station NYC`
  and set `KAIJU_DB_PATH=/app/data/kaiju.sqlite` to persist the state
  database to a mounted volume across container restarts.
- Run in `us-east-1` for free S3 egress from NOAA NODD (NBM/GEFS data is
  hosted on S3 in us-east-1) and low-latency to `external-api.kalshi.com`.
- Pass secrets via `--env-file .env`, EC2 instance profile + SSM Parameter
  Store, or Docker secrets — never bake credentials into the image or push
  `.env` to any registry.
- The Dockerfile installs eccodes as a system package in the image; no
  separate setup is needed on EC2.

---

## 10. Limitations / Known Gaps

This section is an honest accounting of what is not yet verified or complete.
Do not go live without understanding these gaps.

**1. Intraday round-trip PnL not captured in the gate.**
Fill records are not persisted to the database (`record_fill` is absent in
State v1). The gate's `sim_pnl_usd` metric reflects held-to-settlement outcomes
only. Profitable intraday exits (convergence closes) are not counted. The gate
is conservative in this direction (may undercount profitable trading) but the
PnL signal it uses is incomplete.

**2. `fill_rate` is a placeholder of 1.0.**
Because fill records are not persisted, fill rate is hardcoded to 1.0 in the
gate computation (held-to-settlement positions are "filled by definition").
The `min_fill_rate = 0.20` gate threshold exists in the criteria but is
currently always passed. Real fill rate from limit-order execution is unknown.

**3. Multi-city not supported; two distinct IEM identifiers for the same site.**
v1 is single-city only (`NYC`/`KXHIGHNY`). `resolve_settlement` maps only
`KXHIGHNY`. Passing any station other than `NYC` or `KNYC` to `run` raises
`KeyError` loudly — intentional. Additionally, the Central Park site uses two
different IEM identifier pairs: settlement queries the NYCLIMATE archive
(`iem_station=NYTNYC`, `iem_network=NYCLIMATE`) while intraday nowcast queries
the ASOS observation history (`asos_station=NYC`, `asos_network=NY_ASOS`). These
are distinct identifiers for the same physical station (`ncdc81=USW00094728`).
The runner now correctly routes each query to the right identifier pair via
`resolve_settlement`. `observed_max_so_far` defaults `network="NY_ASOS"` and
must be called with `asos_station` (not `iem_station`).

**4. WS `orderbook_delta` is snapshot-only.**
The WS client receives `orderbook_delta` messages but applies them as full
snapshots (v1 limitation explicitly noted in the code). Incremental delta
application is deferred. This means the local book state may lag the true order
book between snapshots; the impact on fill simulation accuracy is unquantified.

**5. Live `get_positions` translation is a TODO.**
The `PositionManager.reconcile` path that calls the Kalshi live `get_positions`
REST endpoint does not yet parse the API response into the internal `Position`
type. Reconciliation will not correctly reflect live positions until this
translation is implemented and verified against a real API response.

**6. Demo-env auth not confirmed.**
The key in `.env` is likely a production key only. A Kalshi demo key is
separately generated at the demo environment. No smoke-test against the demo
environment has been run. Do not assume the demo smoke passes without testing.

**7. Kalshi fee coefficient UNVERIFIED from official sources.**
The taker fee formula (`0.07 × C × (1 − C)` per contract, round up) is sourced
from third-party blog posts that agree with each other and with Kalshi's
`fee_type=quadratic` API field. The official fee schedule PDF was rate-limited
during research. The `fee_multiplier` field on the `KXHIGHNY` series was not
confirmed to be 1.0. Net-edge calculations depend on this coefficient being
correct; verify against a real fill's `fee_cost` field before trusting trade
sizing.

**8. Daily-loss limit currently inert.**
The runner logs this at `WARNING` on every startup and at `ERROR` if `mode=live`.
The `pnl` table is populated by `settle_day` (run the next morning for the prior
day). Intraday, the realized-loss query reads $0.00 until the settle job runs.
The stop-loss mechanism will only activate after the first settlement.

**References:**
- Authoritative design: `docs/superpowers/specs/2026-05-17-kalshi-weather-mispricing-capture-design.md`
- Verified external contracts: `docs/superpowers/notes/` (Kalshi API, WS, NOAA forecast, settlement map)
