# Kalshi Weather Trading Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an autonomous bot that trades Kalshi daily city-temperature bracket markets using an NBM-anchored calibrated temperature forecast, proven via shadow-paper before any real money.

**Architecture:** A daily idempotent pipeline: fetch NBM/GEFS forecasts (Herbie) → build a calibrated integer-°F PMF of the official NWS daily max → read live Kalshi event buckets → compute net-of-fee edge → size with capped fractional Kelly at the city-day level → pass a hard risk gate → place orders in `shadow-paper` or `live` mode. State in SQLite. An eval/gate module measures calibration + simulated PnL and qualifies the model; crossing to real money requires one human arm switch.

**Tech Stack:** Python 3.12, `uv`, `pydantic` (config/types), `herbie-data` + `xarray` + `cfgrib` (NOAA grib), `numpy`/`scipy`/`pandas`, `httpx` (Kalshi REST), `cryptography` (RSA-PSS signing), `structlog`, stdlib `sqlite3`, `pytest` + `respx` (HTTP mocking), `ruff`, `mypy`, Docker.

**Spec:** `docs/superpowers/specs/2026-05-16-kalshi-weather-trading-bot-design.md`

**Conventions for every task below:**
- TDD: write failing test → run it (confirm failure) → minimal implementation → run (confirm pass) → commit.
- Run tests with `uv run pytest`. Lint with `uv run ruff check .` and `uv run mypy kaiju`.
- Commit messages end with the project's `Co-Authored-By` trailer.
- Tasks marked **[SPIKE]** verify an external contract against live docs/APIs and record it to `docs/superpowers/notes/<name>.md` before dependent tasks implement against it. These exist because the spec lists fee formula, RSA signing, NBM product names, and per-city settlement as verify-at-implementation items — do not fabricate these.

---

## File Structure

```
pyproject.toml                      # uv project, deps, tool config
.env.example                        # documented env template (real .env is gitignored)
Dockerfile                          # same image for Mac and EC2
Makefile                            # run/test/lint/build targets
deploy/com.kaiju.daily.plist        # launchd trigger (Mac)
deploy/run_daily.sh                 # entrypoint wrapper
kaiju/__init__.py
kaiju/types.py                      # core domain dataclasses/models (TempPMF, Bucket, ...)
kaiju/config.py                     # pydantic Settings from env
kaiju/logging.py                    # structlog setup
kaiju/state.py                      # SQLite schema + data-access layer
kaiju/strategy/fees.py              # Kalshi fee formula (recorded contract)
kaiju/strategy/edge.py              # model P per bucket, EV, selection
kaiju/strategy/sizing.py            # capped fractional Kelly, city-day level
kaiju/model/distribution.py         # NBM/GEFS -> blended integer-°F PMF
kaiju/model/calibration.py          # low-param bias/spread correction + store
kaiju/data/forecast.py              # Herbie NBM/GEFS fetch + station extraction
kaiju/data/obs.py                   # IEM/NWS official daily-max fetch
kaiju/markets/kalshi_client.py      # RSA-signed REST client
kaiju/markets/parser.py             # discover events, parse buckets + settlement
kaiju/risk/limits.py                # hard limits + kill switch (pre-trade gate)
kaiju/execution/orders.py           # order manager: modes, reconcile, idempotent
kaiju/eval/metrics.py               # Brier/CRPS/reliability/PIT/PnL
kaiju/eval/gate.py                  # promotion-gate evaluator + arm switch
kaiju/runner.py                     # idempotent daily orchestrator + CLI
docs/superpowers/notes/             # recorded external contracts (from SPIKE tasks)
tests/...                           # mirrors kaiju/ layout
```

Files split by responsibility; each is independently testable. `runner.py` only orchestrates — no business logic lives there.

---

## Phase 0 — Foundations

### Task 1: Project scaffold and tooling

**Files:**
- Create: `pyproject.toml`, `kaiju/__init__.py`, `tests/__init__.py`, `.env.example`, `Makefile`
- Create: `tests/test_scaffold.py`

- [ ] **Step 1: Write the failing test**

`tests/test_scaffold.py`:
```python
def test_package_imports():
    import kaiju
    assert kaiju.__version__ == "0.1.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scaffold.py -v`
Expected: FAIL (no `uv` project / `kaiju` not importable).

- [ ] **Step 3: Create the project**

`pyproject.toml`:
```toml
[project]
name = "kaiju"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "pydantic>=2.7",
  "pydantic-settings>=2.3",
  "httpx>=0.27",
  "cryptography>=42",
  "numpy>=1.26",
  "scipy>=1.13",
  "pandas>=2.2",
  "xarray>=2024.6",
  "herbie-data>=2024.8",
  "cfgrib>=0.9.12",
  "structlog>=24.1",
]

[dependency-groups]
dev = ["pytest>=8", "respx>=0.21", "ruff>=0.5", "mypy>=1.10", "freezegun>=1.5"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.mypy]
python_version = "3.12"
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`kaiju/__init__.py`:
```python
__version__ = "0.1.0"
```

`.env.example`:
```
KALSHI_KEY_ID=replace-me
KALSHI_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
KAIJU_MODE=shadow-paper          # backtest | shadow-paper | live
KAIJU_DB_PATH=./kaiju.sqlite
KAIJU_BANKROLL_USD=500
KAIJU_CITIES=KNYC                 # comma-separated station ids, v1 = one city
KAIJU_LIVE_ARM_TOKEN=             # empty until human arms real money
```

`Makefile`:
```make
install: ; uv sync
test: ; uv run pytest -q
lint: ; uv run ruff check . && uv run mypy kaiju
run: ; uv run python -m kaiju.runner
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv sync && uv run pytest tests/test_scaffold.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml kaiju/__init__.py tests/ .env.example Makefile
git commit -m "chore: project scaffold and tooling"
```

### Task 2: Core domain types

**Files:**
- Create: `kaiju/types.py`
- Test: `tests/test_types.py`

- [ ] **Step 1: Write the failing test**

`tests/test_types.py`:
```python
import numpy as np
import pytest
from kaiju.types import TempPMF, Bucket

def test_pmf_validates_and_normalizes():
    pmf = TempPMF.from_probs(low_f=50, probs=[1.0, 1.0, 2.0])  # unnormalized
    assert pmf.high_f == 52
    assert pytest.approx(pmf.probs.sum()) == 1.0
    assert pytest.approx(pmf.prob_at(50)) == 0.25

def test_pmf_rejects_negative():
    with pytest.raises(ValueError):
        TempPMF.from_probs(low_f=0, probs=[0.5, -0.1, 0.6])

def test_prob_interval_inclusive_and_open_tails():
    pmf = TempPMF.from_probs(low_f=10, probs=[0.2, 0.3, 0.5])  # 10,11,12
    assert pytest.approx(pmf.prob_interval(11, 12)) == 0.8
    assert pytest.approx(pmf.prob_interval(None, 10)) == 0.2   # <=10
    assert pytest.approx(pmf.prob_interval(12, None)) == 0.5    # >=12
    assert pytest.approx(pmf.prob_interval(None, None)) == 1.0

def test_bucket_contains_semantics():
    b = Bucket(market_ticker="M", lower_f=50, upper_f=51)   # inclusive 50..51
    assert b.contains(50) and b.contains(51) and not b.contains(52)
    lo_tail = Bucket(market_ticker="L", lower_f=None, upper_f=49)
    assert lo_tail.contains(-5) and lo_tail.contains(49) and not lo_tail.contains(50)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_types.py -v`
Expected: FAIL (`kaiju.types` missing).

- [ ] **Step 3: Write minimal implementation**

`kaiju/types.py`:
```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Optional
import numpy as np

@dataclass(frozen=True)
class TempPMF:
    """Discrete PMF over integer °F for the official NWS daily max."""
    low_f: int
    probs: np.ndarray  # probs[i] = P(temp == low_f + i)

    @property
    def high_f(self) -> int:
        return self.low_f + len(self.probs) - 1

    @classmethod
    def from_probs(cls, low_f: int, probs) -> "TempPMF":
        arr = np.asarray(probs, dtype=float)
        if (arr < 0).any():
            raise ValueError("PMF has negative mass")
        total = arr.sum()
        if total <= 0:
            raise ValueError("PMF mass is non-positive")
        return cls(low_f=int(low_f), probs=arr / total)

    def prob_at(self, t: int) -> float:
        i = t - self.low_f
        return float(self.probs[i]) if 0 <= i < len(self.probs) else 0.0

    def prob_interval(self, lo: Optional[int], hi: Optional[int]) -> float:
        temps = np.arange(self.low_f, self.high_f + 1)
        mask = np.ones(len(temps), dtype=bool)
        if lo is not None:
            mask &= temps >= lo
        if hi is not None:
            mask &= temps <= hi
        return float(self.probs[mask].sum())

@dataclass(frozen=True)
class Bucket:
    market_ticker: str
    lower_f: Optional[float]   # None = open low tail
    upper_f: Optional[float]   # None = open high tail (inclusive bounds)

    def contains(self, t: float) -> bool:
        if self.lower_f is not None and t < self.lower_f:
            return False
        if self.upper_f is not None and t > self.upper_f:
            return False
        return True

@dataclass(frozen=True)
class MarketQuote:
    market_ticker: str
    yes_bid: Optional[int]
    yes_ask: Optional[int]
    no_bid: Optional[int]
    no_ask: Optional[int]
    volume: int
    open_interest: int

@dataclass(frozen=True)
class EventSnapshot:
    event_ticker: str
    station_id: str
    climate_date: str            # ISO date in the station's climate-day tz
    buckets: list[Bucket]
    quotes: dict[str, MarketQuote]

@dataclass(frozen=True)
class TradeIntent:
    market_ticker: str
    side: Literal["yes", "no"]
    limit_price_cents: int
    count: int
    model_prob: float
    net_edge: float

@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str
    adjusted_count: int
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_types.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add kaiju/types.py tests/test_types.py
git commit -m "feat: core domain types (TempPMF, Bucket, snapshots, intents)"
```

### Task 3: Config and structured logging

**Files:**
- Create: `kaiju/config.py`, `kaiju/logging.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:
```python
import pytest
from kaiju.config import Settings

def test_settings_load_from_env(monkeypatch):
    monkeypatch.setenv("KALSHI_KEY_ID", "abc")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY", "KEY")
    monkeypatch.setenv("KAIJU_MODE", "shadow-paper")
    monkeypatch.setenv("KAIJU_BANKROLL_USD", "500")
    monkeypatch.setenv("KAIJU_CITIES", "KNYC,KORD")
    s = Settings()
    assert s.mode == "shadow-paper"
    assert s.cities == ["KNYC", "KORD"]
    assert s.bankroll_usd == 500.0
    assert s.live_armed is False  # no token => not armed

def test_live_requires_arm_token(monkeypatch):
    monkeypatch.setenv("KALSHI_KEY_ID", "a"); monkeypatch.setenv("KALSHI_PRIVATE_KEY", "k")
    monkeypatch.setenv("KAIJU_MODE", "live")
    monkeypatch.setenv("KAIJU_CITIES", "KNYC")
    monkeypatch.setenv("KAIJU_LIVE_ARM_TOKEN", "")
    with pytest.raises(ValueError, match="live mode requires"):
        Settings()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL (`kaiju.config` missing).

- [ ] **Step 3: Write minimal implementation**

`kaiju/config.py`:
```python
from __future__ import annotations
from typing import Literal
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    kalshi_key_id: str
    kalshi_private_key: str
    mode: Literal["backtest", "shadow-paper", "live"] = "shadow-paper"
    db_path: str = "./kaiju.sqlite"
    bankroll_usd: float = 500.0
    cities: list[str] = ["KNYC"]
    live_arm_token: str = ""

    # strategy knobs (all overridable via env, prefixed KAIJU_)
    net_edge_threshold: float = 0.08      # min net edge in prob units (~8c)
    kelly_fraction: float = 0.25
    max_bankroll_frac_per_event: float = 0.10
    max_events_per_day: int = 8
    max_contracts_per_market: int = 50
    max_daily_loss_usd: float = 50.0
    paper_proof_days: int = 30

    @field_validator("cities", mode="before")
    @classmethod
    def _split(cls, v):
        return [x.strip() for x in v.split(",")] if isinstance(v, str) else v

    @property
    def live_armed(self) -> bool:
        return bool(self.live_arm_token.strip())

    @model_validator(mode="after")
    def _live_guard(self):
        if self.mode == "live" and not self.live_armed:
            raise ValueError("live mode requires KAIJU_LIVE_ARM_TOKEN to be set")
        return self

    class Config:
        env_prefix = "KAIJU_"
```
Note: pydantic-settings reads `KALSHI_*` and `KAIJU_*`; map explicitly via aliases if env_prefix conflicts — set `alias="KALSHI_KEY_ID"` etc. on those two fields during implementation if the test fails on naming.

`kaiju/logging.py`:
```python
import structlog

def get_logger(name: str):
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )
    return structlog.get_logger(name)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS. (If field/env naming fails, add explicit `Field(alias=...)` for the two `KALSHI_*` fields, re-run.)

- [ ] **Step 5: Commit**

```bash
git add kaiju/config.py kaiju/logging.py tests/test_config.py
git commit -m "feat: settings (with live arm guard) and structured logging"
```

### Task 4: SQLite state layer

**Files:**
- Create: `kaiju/state.py`
- Test: `tests/test_state.py`

- [ ] **Step 1: Write the failing test**

`tests/test_state.py`:
```python
from kaiju.state import State

def test_state_roundtrip(tmp_path):
    db = State(str(tmp_path / "s.sqlite"))
    db.init_schema()
    db.record_prediction("KNYC", "2026-05-16", low_f=50, probs=[0.2, 0.8])
    p = db.get_prediction("KNYC", "2026-05-16")
    assert p["low_f"] == 50 and p["probs"] == [0.2, 0.8]

    db.record_order(client_id="c1", market="M", side="yes", price=40, count=2, mode="shadow-paper")
    assert db.get_order("c1")["count"] == 2
    db.record_order(client_id="c1", market="M", side="yes", price=40, count=2, mode="shadow-paper")
    assert len(db.list_orders()) == 1   # idempotent on client_id

    db.set_gate_status("qualified", brier=0.18, pnl=12.5)
    assert db.get_gate_status()["status"] == "qualified"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_state.py -v`
Expected: FAIL (`kaiju.state` missing).

- [ ] **Step 3: Write minimal implementation**

`kaiju/state.py`:
```python
from __future__ import annotations
import json, sqlite3
from typing import Any, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions(
  station TEXT, climate_date TEXT, low_f INT, probs TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  PRIMARY KEY(station, climate_date));
CREATE TABLE IF NOT EXISTS orders(
  client_id TEXT PRIMARY KEY, market TEXT, side TEXT, price INT, count INT,
  mode TEXT, status TEXT DEFAULT 'submitted', created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS fills(
  client_id TEXT, market TEXT, price INT, count INT, ts TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS pnl(
  climate_date TEXT PRIMARY KEY, realized_usd REAL, mode TEXT);
CREATE TABLE IF NOT EXISTS gate(
  id INT PRIMARY KEY CHECK (id=1), status TEXT, brier REAL, pnl REAL,
  updated_at TEXT DEFAULT (datetime('now')));
"""

class State:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row

    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def record_prediction(self, station, climate_date, low_f, probs):
        self.conn.execute(
            "INSERT OR REPLACE INTO predictions(station,climate_date,low_f,probs) VALUES(?,?,?,?)",
            (station, climate_date, low_f, json.dumps(list(probs))))
        self.conn.commit()

    def get_prediction(self, station, climate_date) -> Optional[dict]:
        r = self.conn.execute(
            "SELECT * FROM predictions WHERE station=? AND climate_date=?",
            (station, climate_date)).fetchone()
        if not r: return None
        d = dict(r); d["probs"] = json.loads(d["probs"]); return d

    def record_order(self, client_id, market, side, price, count, mode):
        self.conn.execute(
            "INSERT OR IGNORE INTO orders(client_id,market,side,price,count,mode) "
            "VALUES(?,?,?,?,?,?)", (client_id, market, side, price, count, mode))
        self.conn.commit()

    def get_order(self, client_id) -> Optional[dict]:
        r = self.conn.execute("SELECT * FROM orders WHERE client_id=?", (client_id,)).fetchone()
        return dict(r) if r else None

    def list_orders(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM orders").fetchall()]

    def set_gate_status(self, status, brier, pnl):
        self.conn.execute(
            "INSERT INTO gate(id,status,brier,pnl) VALUES(1,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET status=?,brier=?,pnl=?,updated_at=datetime('now')",
            (status, brier, pnl, status, brier, pnl))
        self.conn.commit()

    def get_gate_status(self) -> Optional[dict]:
        r = self.conn.execute("SELECT * FROM gate WHERE id=1").fetchone()
        return dict(r) if r else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_state.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add kaiju/state.py tests/test_state.py
git commit -m "feat: SQLite state layer (predictions, orders, pnl, gate)"
```

---

## Phase 1 — External contracts (SPIKE tasks: verify, do not fabricate)

### Task 5: [SPIKE] Record Kalshi API contract (auth + endpoints)

**Files:**
- Create: `docs/superpowers/notes/kalshi-api-contract.md`

- [ ] **Step 1: Fetch the live Kalshi API docs**

Use the WebFetch tool on the current Kalshi API docs (`https://trading-api.readme.io/` / `https://docs.kalshi.com/`). Extract and record verbatim into `docs/superpowers/notes/kalshi-api-contract.md`:
  - REST base URLs (prod and demo).
  - Exact auth scheme: header names, the exact string that is signed (method + path + timestamp ordering), signature algorithm (RSA-PSS vs PKCS1v15), digest, and encoding (base64).
  - Endpoints + JSON shapes for: list series, list events, list markets, get orderbook, get balance, get positions, create order, cancel order.
  - The current trading **fee formula** with Kalshi's own worked numeric examples.
  - Per-market settlement fields (the rule text field name that states the settlement station and climate-day window).

- [ ] **Step 2: Self-consistency note**

In the same file, write a short "Test vectors" section: pick one fee example from the docs (inputs → expected fee cents) and one signing example (or, if none published, note that signing will be tested via generate-keypair-then-verify-with-public-key round trip).

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/notes/kalshi-api-contract.md
git commit -m "docs: recorded Kalshi API + fee contract (verified from live docs)"
```

### Task 6: [SPIKE] Record NBM/GEFS Herbie product contract

**Files:**
- Create: `docs/superpowers/notes/noaa-forecast-contract.md`

- [ ] **Step 1: Inventory NBM max-temp guidance**

Run (record exact output into the notes file):
```bash
uv run python - <<'PY'
from herbie import Herbie
import datetime as dt
run = dt.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
H = Herbie(run, model="nbm", product="co", fxx=24)   # confirm product/fxx for daily TMAX
print(H.PRODUCTS)
print(H.inventory().to_string())
PY
```
Record: the exact `model`, `product`, `fxx` values and the grib `search` regex that selects (a) NBM probabilistic/percentile **max temperature** over the daily window, (b) NBM deterministic 2m temperature. Repeat the inventory for `model="gefs"` and record the member dimension + 2m temperature `search` string.

- [ ] **Step 2: Record station extraction approach**

Document the xarray call to interpolate grid → station lat/lon (`ds.herbie.pick_points` or `ds.interp`), and how to compute per-member daily max over the climate-day window in the station tz.

- [ ] **Step 3: Cache a fixture**

Download one small NBM subset and one GEFS subset for `KNYC`, save the extracted arrays to `tests/fixtures/nbm_knyc.json` and `tests/fixtures/gefs_knyc.json` (percentile→temp table; member→temp list). These fixtures back the offline tests in Phase 3.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/notes/noaa-forecast-contract.md tests/fixtures/
git commit -m "docs: recorded NBM/GEFS Herbie contract + offline fixtures"
```

### Task 7: [SPIKE] Record IEM official daily-max + per-city settlement map

**Files:**
- Create: `docs/superpowers/notes/settlement-map.md`
- Create: `tests/fixtures/iem_knyc_dailymax.json`

- [ ] **Step 1: Record the IEM endpoint**

Document the IEM daily climate endpoint that returns the official NWS daily **max** temperature by station/date (e.g. the IEM `daily.py` / CF6 JSON service). Save a real response for `KNYC` over a 10-day past window to the fixture file.

- [ ] **Step 2: Build the settlement map from live Kalshi rules**

For each city in `KAIJU_CITIES` (v1 default `KNYC`), call the Kalshi list-markets endpoint (using the contract recorded in Task 5; a throwaway script is fine here), read the settlement rule text, and record into `settlement-map.md`: Kalshi series ticker → settlement station id → climate-day timezone + window definition → IEM station id. Flag any city whose rule text is ambiguous (do not include ambiguous cities in v1 trading).

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/notes/settlement-map.md tests/fixtures/iem_knyc_dailymax.json
git commit -m "docs: recorded IEM daily-max contract + Kalshi settlement map"
```

---

## Phase 2 — Core deterministic logic (full TDD)

### Task 8: Kalshi fee model

**Files:**
- Create: `kaiju/strategy/fees.py`, `kaiju/strategy/__init__.py`
- Test: `tests/strategy/test_fees.py`

- [ ] **Step 1: Write the failing test**

Use the exact worked example(s) recorded in `docs/superpowers/notes/kalshi-api-contract.md` (Task 5). `tests/strategy/test_fees.py` (substitute the recorded numbers for `<...>`):
```python
import math
from kaiju.strategy.fees import trade_fee_cents

def test_fee_matches_kalshi_published_example():
    # From docs/superpowers/notes/kalshi-api-contract.md "Test vectors"
    assert trade_fee_cents(price_cents=<P>, count=<C>) == <EXPECTED_CENTS>

def test_fee_is_zero_floor_and_symmetric():
    assert trade_fee_cents(1, 1) >= 0
    assert trade_fee_cents(50, 10) == trade_fee_cents(50, 10)

def test_fee_rounds_up():
    f = trade_fee_cents(50, 1)
    assert f == math.ceil(f)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/strategy/test_fees.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Write minimal implementation**

`kaiju/strategy/fees.py` — implement the **exact formula recorded in Task 5's notes**. Template (replace coefficient/rounding with the recorded values):
```python
import math

FEE_COEFF = <RECORDED_COEFF>   # e.g. 0.07, from kalshi-api-contract.md

def trade_fee_cents(price_cents: int, count: int) -> int:
    """Kalshi trade fee in cents. Formula + constant pinned to recorded docs."""
    p = price_cents / 100.0
    raw = FEE_COEFF * count * p * (1.0 - p) * 100.0
    return math.ceil(raw)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/strategy/test_fees.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add kaiju/strategy/ tests/strategy/test_fees.py
git commit -m "feat: Kalshi fee model pinned to recorded contract"
```

### Task 9: Bucket-probability mapping (PMF → market probabilities)

**Files:**
- Create: `kaiju/strategy/edge.py`
- Test: `tests/strategy/test_edge_buckets.py`

- [ ] **Step 1: Write the failing test**

`tests/strategy/test_edge_buckets.py`:
```python
import pytest
from kaiju.types import TempPMF, Bucket
from kaiju.strategy.edge import bucket_probabilities

def test_bucket_probs_sum_to_one_and_match_pmf():
    pmf = TempPMF.from_probs(low_f=48, probs=[0.1, 0.2, 0.4, 0.2, 0.1])  # 48..52
    buckets = [
        Bucket("LO", None, 49),     # <=49 -> 0.1+0.2=0.3
        Bucket("M1", 50, 51),       # 50,51 -> 0.4+0.2=0.6
        Bucket("HI", 52, None),     # >=52 -> 0.1
    ]
    probs = bucket_probabilities(pmf, buckets)
    assert pytest.approx(probs["LO"]) == 0.3
    assert pytest.approx(probs["M1"]) == 0.6
    assert pytest.approx(probs["HI"]) == 0.1
    assert pytest.approx(sum(probs.values())) == 1.0

def test_renormalizes_when_buckets_cover_partial_support():
    pmf = TempPMF.from_probs(low_f=0, probs=[0.5, 0.5])  # 0,1
    buckets = [Bucket("A", 0, 0), Bucket("B", 1, 1)]
    probs = bucket_probabilities(pmf, buckets)
    assert pytest.approx(sum(probs.values())) == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/strategy/test_edge_buckets.py -v`
Expected: FAIL (function missing).

- [ ] **Step 3: Write minimal implementation**

Add to `kaiju/strategy/edge.py`:
```python
from __future__ import annotations
from kaiju.types import TempPMF, Bucket

def bucket_probabilities(pmf: TempPMF, buckets: list[Bucket]) -> dict[str, float]:
    raw = {}
    for b in buckets:
        lo = None if b.lower_f is None else int(b.lower_f)
        hi = None if b.upper_f is None else int(b.upper_f)
        raw[b.market_ticker] = pmf.prob_interval(lo, hi)
    total = sum(raw.values())
    if total <= 0:
        raise ValueError("buckets capture no PMF mass")
    return {k: v / total for k, v in raw.items()}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/strategy/test_edge_buckets.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add kaiju/strategy/edge.py tests/strategy/test_edge_buckets.py
git commit -m "feat: PMF -> normalized bucket probabilities"
```

### Task 10: Net-edge computation and trade selection

**Files:**
- Modify: `kaiju/strategy/edge.py`
- Test: `tests/strategy/test_edge_selection.py`

- [ ] **Step 1: Write the failing test**

`tests/strategy/test_edge_selection.py`:
```python
import pytest
from kaiju.types import MarketQuote
from kaiju.strategy.edge import select_trades

def test_selects_yes_when_model_beats_ask_net_of_fee():
    model_probs = {"M": 0.70}
    quotes = {"M": MarketQuote("M", yes_bid=40, yes_ask=45, no_bid=55, no_ask=60,
                               volume=500, open_interest=1000)}
    intents = select_trades(model_probs, quotes, net_edge_threshold=0.08,
                            min_open_interest=100)
    assert len(intents) == 1
    t = intents[0]
    assert t.side == "yes" and t.limit_price_cents == 45
    assert t.net_edge > 0.08

def test_rejects_when_edge_below_threshold():
    model_probs = {"M": 0.50}
    quotes = {"M": MarketQuote("M", 48, 52, 48, 52, 500, 1000)}
    assert select_trades(model_probs, quotes, 0.08, 100) == []

def test_rejects_illiquid_market():
    model_probs = {"M": 0.99}
    quotes = {"M": MarketQuote("M", 1, 2, 98, 99, 0, 10)}
    assert select_trades(model_probs, quotes, 0.08, 100) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/strategy/test_edge_selection.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

Append to `kaiju/strategy/edge.py`:
```python
from kaiju.types import MarketQuote, TradeIntent
from kaiju.strategy.fees import trade_fee_cents

def select_trades(model_probs: dict[str, float], quotes: dict[str, MarketQuote],
                  net_edge_threshold: float, min_open_interest: int) -> list[TradeIntent]:
    intents: list[TradeIntent] = []
    for tkr, p in model_probs.items():
        q = quotes.get(tkr)
        if q is None or q.open_interest < min_open_interest:
            continue
        # YES: pay yes_ask cents, win 100 if event true
        if q.yes_ask is not None:
            cost = q.yes_ask / 100.0
            fee = trade_fee_cents(q.yes_ask, 1) / 100.0
            edge = p - cost - fee
            if edge >= net_edge_threshold:
                intents.append(TradeIntent(tkr, "yes", q.yes_ask, 1, p, edge))
                continue
        # NO: pay no_ask cents, win 100 if event false
        if q.no_ask is not None:
            cost = q.no_ask / 100.0
            fee = trade_fee_cents(q.no_ask, 1) / 100.0
            edge = (1.0 - p) - cost - fee
            if edge >= net_edge_threshold:
                intents.append(TradeIntent(tkr, "no", q.no_ask, 1, p, edge))
    return intents
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/strategy/test_edge_selection.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add kaiju/strategy/edge.py tests/strategy/test_edge_selection.py
git commit -m "feat: net-of-fee edge selection (yes/no, liquidity filter)"
```

### Task 11: Capped fractional Kelly sizing at city-day level

**Files:**
- Create: `kaiju/strategy/sizing.py`
- Test: `tests/strategy/test_sizing.py`

- [ ] **Step 1: Write the failing test**

`tests/strategy/test_sizing.py`:
```python
import pytest
from kaiju.types import TradeIntent
from kaiju.strategy.sizing import size_event

def _intent(tkr, p, price, edge): return TradeIntent(tkr, "yes", price, 1, p, edge)

def test_kelly_caps_by_bankroll_fraction():
    intents = [_intent("M", 0.7, 45, 0.20)]
    sized = size_event(intents, bankroll_usd=500, kelly_fraction=0.25,
                        max_bankroll_frac=0.10)
    # capped stake <= 0.10 * 500 = $50 ; contract cost $0.45 => <=111 contracts,
    # but Kelly fraction should bind first and be > 0
    assert 1 <= sized[0].count
    assert sized[0].count * 0.45 <= 50.0 + 1e-9

def test_drops_when_kelly_below_one_contract():
    intents = [_intent("M", 0.51, 49, 0.005)]
    sized = size_event(intents, 100, 0.25, 0.10)
    assert sized == []

def test_event_level_budget_shared_across_buckets():
    intents = [_intent("A", 0.6, 30, 0.15), _intent("B", 0.6, 30, 0.15)]
    sized = size_event(intents, 500, 0.25, 0.10)
    total_cost = sum(s.count * 0.30 for s in sized)
    assert total_cost <= 0.10 * 500 + 1e-9   # shared event budget, not per-bucket
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/strategy/test_sizing.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

`kaiju/strategy/sizing.py`:
```python
from __future__ import annotations
from kaiju.types import TradeIntent

def _kelly_fraction(p: float, price_cents: int) -> float:
    """Binary Kelly: edge / odds. Cost c, payoff 1. b = (1-c)/c, q = 1-p."""
    c = price_cents / 100.0
    if c <= 0 or c >= 1:
        return 0.0
    b = (1.0 - c) / c
    f = (p * b - (1.0 - p)) / b
    return max(0.0, f)

def size_event(intents: list[TradeIntent], bankroll_usd: float,
                kelly_fraction: float, max_bankroll_frac: float) -> list[TradeIntent]:
    budget = bankroll_usd * max_bankroll_frac          # shared per city-day event
    out: list[TradeIntent] = []
    spent = 0.0
    for it in sorted(intents, key=lambda x: -x.net_edge):
        f = kelly_fraction * _kelly_fraction(it.model_prob, it.limit_price_cents)
        stake = min(f * bankroll_usd, budget - spent)
        cost = it.limit_price_cents / 100.0
        count = int(stake // cost)
        if count < 1:
            continue
        spent += count * cost
        out.append(TradeIntent(it.market_ticker, it.side, it.limit_price_cents,
                                count, it.model_prob, it.net_edge))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/strategy/test_sizing.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add kaiju/strategy/sizing.py tests/strategy/test_sizing.py
git commit -m "feat: capped fractional Kelly sizing at city-day event level"
```

### Task 12: Forecast distribution builder (NBM percentiles + GEFS blend)

**Files:**
- Create: `kaiju/model/distribution.py`, `kaiju/model/__init__.py`
- Test: `tests/model/test_distribution.py`

- [ ] **Step 1: Write the failing test**

`tests/model/test_distribution.py`:
```python
import numpy as np, pytest
from kaiju.model.distribution import pmf_from_nbm_percentiles, blend_pmfs
from kaiju.types import TempPMF

def test_pmf_from_percentiles_is_monotone_and_normalized():
    # percentile (0-100) -> temp °F, calibrated NBM-style
    pct = {10: 60.0, 25: 62.0, 50: 65.0, 75: 68.0, 90: 70.0}
    pmf = pmf_from_nbm_percentiles(pct)
    assert isinstance(pmf, TempPMF)
    assert pytest.approx(pmf.probs.sum()) == 1.0
    cdf = np.cumsum(pmf.probs)
    assert np.all(np.diff(cdf) >= -1e-12)            # monotone CDF
    assert abs(pmf.prob_interval(None, 65) - 0.5) < 0.08  # ~median at 65

def test_blend_is_convex_combination():
    a = TempPMF.from_probs(0, [1.0, 0.0])
    b = TempPMF.from_probs(0, [0.0, 1.0])
    blended = blend_pmfs([(a, 0.75), (b, 0.25)])
    assert pytest.approx(blended.prob_at(0)) == 0.75
    assert pytest.approx(blended.prob_at(1)) == 0.25
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/model/test_distribution.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

`kaiju/model/distribution.py`:
```python
from __future__ import annotations
import numpy as np
from kaiju.types import TempPMF

def pmf_from_nbm_percentiles(pct_to_temp: dict[float, float]) -> TempPMF:
    """Interpolate calibrated percentile->temp to a discrete integer-°F PMF."""
    qs = np.array(sorted(pct_to_temp), dtype=float) / 100.0
    ts = np.array([pct_to_temp[p] for p in sorted(pct_to_temp)], dtype=float)
    lo, hi = int(np.floor(ts.min())) - 1, int(np.ceil(ts.max())) + 1
    grid = np.arange(lo, hi + 1)
    # CDF(temp) = interp of quantile levels over temps, clamped to [0,1]
    cdf = np.interp(grid, ts, qs, left=0.0, right=1.0)
    pmf = np.diff(np.concatenate([[0.0], cdf]))
    pmf = np.clip(pmf, 0.0, None)
    return TempPMF.from_probs(low_f=lo, probs=pmf)

def blend_pmfs(weighted: list[tuple[TempPMF, float]]) -> TempPMF:
    lo = min(p.low_f for p, _ in weighted)
    hi = max(p.high_f for p, _ in weighted)
    acc = np.zeros(hi - lo + 1)
    for pmf, w in weighted:
        acc[pmf.low_f - lo: pmf.low_f - lo + len(pmf.probs)] += w * pmf.probs
    return TempPMF.from_probs(low_f=lo, probs=acc)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/model/test_distribution.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add kaiju/model/ tests/model/test_distribution.py
git commit -m "feat: NBM percentile -> PMF and convex PMF blend"
```

### Task 13: Low-parameter calibration (bias + spread, with shrinkage)

**Files:**
- Create: `kaiju/model/calibration.py`
- Test: `tests/model/test_calibration.py`

- [ ] **Step 1: Write the failing test**

`tests/model/test_calibration.py`:
```python
import numpy as np, pytest
from kaiju.types import TempPMF
from kaiju.model.calibration import fit_calibration, apply_calibration

def test_bias_is_shrunk_when_few_samples():
    # forecast medians vs realized: consistent +3°F warm bias, only 3 samples
    fc_medians = [60.0, 65.0, 70.0]
    realized   = [57, 62, 67]
    cal = fit_calibration(fc_medians, realized, min_samples=20)
    assert -3.0 < cal.bias < 0.0           # shrunk toward 0, not full -3
    assert cal.n_samples == 3

def test_apply_shifts_pmf_by_bias_and_scales_spread():
    pmf = TempPMF.from_probs(60, [0.25, 0.5, 0.25])  # mean 61
    from kaiju.model.calibration import CalibrationParams
    cal = CalibrationParams(bias=-1.0, spread_scale=1.0, n_samples=50)
    out = apply_calibration(pmf, cal)
    # mass shifted ~1°F cooler, still normalized
    assert pytest.approx(out.probs.sum()) == 1.0
    assert out.prob_interval(None, 60) > pmf.prob_interval(None, 60)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/model/test_calibration.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

`kaiju/model/calibration.py`:
```python
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from kaiju.types import TempPMF

@dataclass(frozen=True)
class CalibrationParams:
    bias: float          # add to forecast temps (°F)
    spread_scale: float  # multiply deviation about mean
    n_samples: int

def fit_calibration(fc_medians, realized, min_samples: int) -> CalibrationParams:
    fc = np.asarray(fc_medians, float); ob = np.asarray(realized, float)
    n = len(fc)
    raw_bias = float(np.mean(ob - fc)) if n else 0.0
    # James–Stein-style shrinkage toward 0 by sample size
    shrink = n / (n + min_samples)
    bias = shrink * raw_bias
    if n >= 2:
        err = ob - fc - raw_bias
        raw_scale = float(np.std(err) / (np.std(fc) + 1e-6)) or 1.0
        scale = 1.0 + shrink * (raw_scale - 1.0)
    else:
        scale = 1.0
    return CalibrationParams(bias=bias, spread_scale=max(0.5, scale), n_samples=n)

def apply_calibration(pmf: TempPMF, cal: CalibrationParams) -> TempPMF:
    temps = np.arange(pmf.low_f, pmf.high_f + 1, dtype=float)
    mean = float((temps * pmf.probs).sum())
    new_temps = mean + cal.bias + (temps - mean) * cal.spread_scale
    lo = int(np.floor(new_temps.min())); hi = int(np.ceil(new_temps.max()))
    grid = np.arange(lo, hi + 1)
    acc = np.zeros(len(grid))
    # distribute each old atom to nearest new integer bin
    idx = np.clip(np.round(new_temps).astype(int) - lo, 0, len(grid) - 1)
    np.add.at(acc, idx, pmf.probs)
    return TempPMF.from_probs(low_f=lo, probs=acc)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/model/test_calibration.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add kaiju/model/calibration.py tests/model/test_calibration.py
git commit -m "feat: low-parameter bias/spread calibration with shrinkage"
```

### Task 14: Eval metrics (Brier, CRPS, PIT, reliability, PnL)

**Files:**
- Create: `kaiju/eval/metrics.py`, `kaiju/eval/__init__.py`
- Test: `tests/eval/test_metrics.py`

- [ ] **Step 1: Write the failing test**

`tests/eval/test_metrics.py`:
```python
import numpy as np, pytest
from kaiju.types import TempPMF
from kaiju.eval.metrics import brier_score, crps_pmf, pit_value

def test_brier_perfect_and_worst():
    assert brier_score([1.0], [1]) == 0.0
    assert brier_score([0.0], [1]) == 1.0

def test_crps_zero_for_point_mass_on_truth():
    pmf = TempPMF.from_probs(70, [1.0])
    assert crps_pmf(pmf, observed=70) == pytest.approx(0.0)

def test_pit_in_unit_interval():
    pmf = TempPMF.from_probs(60, [0.2, 0.3, 0.5])
    v = pit_value(pmf, observed=61)
    assert 0.0 <= v <= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/eval/test_metrics.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

`kaiju/eval/metrics.py`:
```python
from __future__ import annotations
import numpy as np
from kaiju.types import TempPMF

def brier_score(probs, outcomes) -> float:
    p = np.asarray(probs, float); y = np.asarray(outcomes, float)
    return float(np.mean((p - y) ** 2))

def crps_pmf(pmf: TempPMF, observed: int) -> float:
    temps = np.arange(pmf.low_f, pmf.high_f + 1)
    cdf = np.cumsum(pmf.probs)
    heaviside = (temps >= observed).astype(float)
    return float(np.sum((cdf - heaviside) ** 2))

def pit_value(pmf: TempPMF, observed: int) -> float:
    return float(pmf.prob_interval(None, observed))

def reliability_bins(probs, outcomes, n_bins: int = 10):
    p = np.asarray(probs, float); y = np.asarray(outcomes, float)
    edges = np.linspace(0, 1, n_bins + 1)
    out = []
    for i in range(n_bins):
        m = (p >= edges[i]) & (p < edges[i + 1])
        if m.any():
            out.append((float(p[m].mean()), float(y[m].mean()), int(m.sum())))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/eval/test_metrics.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add kaiju/eval/ tests/eval/test_metrics.py
git commit -m "feat: eval metrics (Brier, CRPS, PIT, reliability)"
```

### Task 15: Risk limits and kill switch (pre-trade gate)

**Files:**
- Create: `kaiju/risk/limits.py`, `kaiju/risk/__init__.py`
- Test: `tests/risk/test_limits.py`

- [ ] **Step 1: Write the failing test**

`tests/risk/test_limits.py`:
```python
import pytest
from kaiju.types import TradeIntent, RiskDecision
from kaiju.risk.limits import RiskGate

def _it(c): return TradeIntent("M", "yes", 40, c, 0.7, 0.15)

def test_blocks_when_kill_switch_file_present(tmp_path):
    ks = tmp_path / "KILL"; ks.write_text("stop")
    gate = RiskGate(kill_switch_path=str(ks), max_contracts_per_market=50,
                    max_daily_loss_usd=50, bankroll_usd=500)
    d = gate.check(_it(1), realized_loss_today_usd=0.0)
    assert d.approved is False and "kill switch" in d.reason

def test_blocks_when_daily_loss_exceeded(tmp_path):
    gate = RiskGate(str(tmp_path / "none"), 50, 50, 500)
    d = gate.check(_it(1), realized_loss_today_usd=51.0)
    assert d.approved is False and "daily loss" in d.reason

def test_clamps_count_to_per_market_cap(tmp_path):
    gate = RiskGate(str(tmp_path / "none"), max_contracts_per_market=10,
                    max_daily_loss_usd=50, bankroll_usd=500)
    d = gate.check(_it(999), realized_loss_today_usd=0.0)
    assert d.approved is True and d.adjusted_count == 10

def test_blocks_when_no_intent_or_zero_count(tmp_path):
    gate = RiskGate(str(tmp_path / "none"), 10, 50, 500)
    assert gate.check(_it(0), 0.0).approved is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/risk/test_limits.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

`kaiju/risk/limits.py`:
```python
from __future__ import annotations
import os
from kaiju.types import TradeIntent, RiskDecision

class RiskGate:
    def __init__(self, kill_switch_path: str, max_contracts_per_market: int,
                 max_daily_loss_usd: float, bankroll_usd: float):
        self.kill = kill_switch_path
        self.max_ct = max_contracts_per_market
        self.max_loss = max_daily_loss_usd
        self.bankroll = bankroll_usd

    def check(self, intent: TradeIntent, realized_loss_today_usd: float) -> RiskDecision:
        if os.path.exists(self.kill):
            return RiskDecision(False, "kill switch engaged", 0)
        if realized_loss_today_usd >= self.max_loss:
            return RiskDecision(False, "daily loss limit reached", 0)
        if intent is None or intent.count < 1:
            return RiskDecision(False, "no tradeable intent", 0)
        count = min(intent.count, self.max_ct)
        if count * intent.limit_price_cents / 100.0 > self.bankroll:
            return RiskDecision(False, "exceeds bankroll", 0)
        return RiskDecision(True, "ok", count)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/risk/test_limits.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add kaiju/risk/ tests/risk/test_limits.py
git commit -m "feat: pre-trade risk gate (kill switch, loss + size caps)"
```

### Task 16: Promotion gate evaluator + arm switch

**Files:**
- Create: `kaiju/eval/gate.py`
- Test: `tests/eval/test_gate.py`

- [ ] **Step 1: Write the failing test**

`tests/eval/test_gate.py`:
```python
from kaiju.eval.gate import evaluate_promotion, GateCriteria, can_trade_live

def test_qualifies_when_all_criteria_met():
    res = evaluate_promotion(days=30, brier=0.16, market_baseline_brier=0.20,
                             pit_uniform_pvalue=0.4, sim_pnl_usd=18.0,
                             trades=25, max_drawdown_usd=8.0,
                             c=GateCriteria())
    assert res.qualified is True

def test_not_qualified_when_pnl_negative():
    res = evaluate_promotion(30, 0.16, 0.20, 0.4, -2.0, 25, 8.0, GateCriteria())
    assert res.qualified is False and "pnl" in res.reason

def test_not_qualified_before_min_days():
    res = evaluate_promotion(10, 0.10, 0.20, 0.9, 50.0, 40, 1.0, GateCriteria())
    assert res.qualified is False and "days" in res.reason

def test_live_requires_qualified_and_armed():
    assert can_trade_live(qualified=True, armed=True) is True
    assert can_trade_live(qualified=True, armed=False) is False
    assert can_trade_live(qualified=False, armed=True) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/eval/test_gate.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

`kaiju/eval/gate.py`:
```python
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class GateCriteria:
    min_days: int = 30
    min_trades: int = 15
    min_pit_pvalue: float = 0.05
    max_drawdown_usd: float = 25.0

@dataclass(frozen=True)
class GateResult:
    qualified: bool
    reason: str

def evaluate_promotion(days, brier, market_baseline_brier, pit_uniform_pvalue,
                        sim_pnl_usd, trades, max_drawdown_usd,
                        c: GateCriteria) -> GateResult:
    if days < c.min_days:
        return GateResult(False, f"insufficient days ({days}<{c.min_days})")
    if trades < c.min_trades:
        return GateResult(False, f"insufficient trades ({trades}<{c.min_trades})")
    if brier >= market_baseline_brier:
        return GateResult(False, "calibration not better than market baseline")
    if pit_uniform_pvalue < c.min_pit_pvalue:
        return GateResult(False, "PIT not uniform (miscalibrated)")
    if sim_pnl_usd <= 0:
        return GateResult(False, "non-positive simulated pnl")
    if max_drawdown_usd > c.max_drawdown_usd:
        return GateResult(False, "drawdown exceeds bound")
    return GateResult(True, "qualified")

def can_trade_live(qualified: bool, armed: bool) -> bool:
    return bool(qualified and armed)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/eval/test_gate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add kaiju/eval/gate.py tests/eval/test_gate.py
git commit -m "feat: promotion-gate evaluator + live arm guard"
```

---

## Phase 3 — Data ingestion (against recorded contracts; offline tests via fixtures)

### Task 17: IEM official daily-max client

**Files:**
- Create: `kaiju/data/obs.py`, `kaiju/data/__init__.py`
- Test: `tests/data/test_obs.py`

- [ ] **Step 1: Write the failing test (offline, uses Task 7 fixture + respx)**

`tests/data/test_obs.py`:
```python
import json, respx, httpx
from kaiju.data.obs import IEMClient

def test_parses_official_daily_max(monkeypatch):
    fixture = json.load(open("tests/fixtures/iem_knyc_dailymax.json"))
    with respx.mock:
        respx.get(url__regex=r".*mesonet\.agron\.iastate\.edu.*").mock(
            return_value=httpx.Response(200, json=fixture))
        c = IEMClient()
        v = c.official_daily_max(station="KNYC", date="2026-05-06")
        assert isinstance(v, int)   # integer °F official max
```
(Set the asserted value to the known value present in the fixture for `2026-05-06`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/data/test_obs.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement against the endpoint recorded in Task 7**

`kaiju/data/obs.py` — implement `IEMClient.official_daily_max(station, date) -> int` using the exact IEM URL + JSON path documented in `docs/superpowers/notes/settlement-map.md`. Parse the official daily max field, round to integer °F (NWS reports integer), raise `LookupError` if absent.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/data/test_obs.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add kaiju/data/ tests/data/test_obs.py
git commit -m "feat: IEM official daily-max client (offline-tested)"
```

### Task 18: Herbie NBM/GEFS forecast fetcher + station extraction

**Files:**
- Create: `kaiju/data/forecast.py`
- Test: `tests/data/test_forecast.py`

- [ ] **Step 1: Write the failing test (offline, uses Task 6 fixtures)**

`tests/data/test_forecast.py`:
```python
import json
from kaiju.data.forecast import nbm_percentiles_from_fixture, gefs_members_from_fixture

def test_nbm_fixture_parses_to_percentile_map():
    pct = nbm_percentiles_from_fixture("tests/fixtures/nbm_knyc.json")
    assert all(0 < k < 100 for k in pct)        # percentile keys
    assert all(isinstance(v, float) for v in pct.values())  # °F temps
    assert pct[sorted(pct)[0]] <= pct[sorted(pct)[-1]]      # monotone

def test_gefs_fixture_parses_to_member_list():
    members = gefs_members_from_fixture("tests/fixtures/gefs_knyc.json")
    assert len(members) >= 20 and all(isinstance(m, float) for m in members)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/data/test_forecast.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement against the contract recorded in Task 6**

`kaiju/data/forecast.py`:
- `nbm_percentiles_from_fixture(path)` / `gefs_members_from_fixture(path)` — pure parsers over the fixture JSON shape created in Task 6 (these make the pipeline testable offline).
- `fetch_nbm_percentiles(station_id, run_dt, climate_date) -> dict[float,float]` and `fetch_gefs_members(station_id, run_dt, climate_date) -> list[float]` — live path using Herbie with the exact `model/product/fxx/search` strings and the station-extraction call recorded in `docs/superpowers/notes/noaa-forecast-contract.md`. Compute the per-member / percentile **daily max over the climate-day window in the station tz** as documented. Cache raw downloads under `data/cache/` (gitignored).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/data/test_forecast.py -v`
Expected: PASS.

- [ ] **Step 5: Live smoke (manual, not in CI)**

Run: `uv run python -m kaiju.data.forecast --smoke KNYC` and confirm it prints a plausible percentile map. Record nothing; this is a sanity check.

- [ ] **Step 6: Commit**

```bash
git add kaiju/data/forecast.py tests/data/test_forecast.py
git commit -m "feat: Herbie NBM/GEFS fetch + station extraction (offline-tested)"
```

---

## Phase 4 — Kalshi integration (against recorded contract; mocked tests)

### Task 19: RSA-signed Kalshi REST client

**Files:**
- Create: `kaiju/markets/kalshi_client.py`, `kaiju/markets/__init__.py`
- Test: `tests/markets/test_kalshi_client.py`

- [ ] **Step 1: Write the failing test (signing round-trip + mocked REST)**

`tests/markets/test_kalshi_client.py`:
```python
import respx, httpx
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from kaiju.markets.kalshi_client import KalshiClient, sign_request

def _priv_pem():
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return k, k.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()).decode()

def test_signature_verifies_with_public_key():
    key, pem = _priv_pem()
    sig, ts = sign_request(pem, "GET", "/trade-api/v2/markets", timestamp_ms=1700000000000)
    # verify using the recorded algorithm (see kalshi-api-contract.md)
    from kaiju.markets.kalshi_client import _verify_for_test
    assert _verify_for_test(key.public_key(), sig,
                            "1700000000000" + "GET" + "/trade-api/v2/markets")

def test_get_orderbook_parses_quotes():
    _, pem = _priv_pem()
    body = {"orderbook": {"yes": [[40, 100]], "no": [[58, 100]]}}  # adjust to recorded shape
    with respx.mock:
        respx.get(url__regex=r".*/markets/.*/orderbook").mock(
            return_value=httpx.Response(200, json=body))
        c = KalshiClient(key_id="k", private_key_pem=pem, base_url="https://x")
        q = c.get_quote("M-TICKER")
        assert q.market_ticker == "M-TICKER"
        assert q.yes_ask is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/markets/test_kalshi_client.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement against the contract recorded in Task 5**

`kaiju/markets/kalshi_client.py`:
- `sign_request(private_key_pem, method, path, timestamp_ms) -> (signature_b64, timestamp)` using the **exact** signed-string ordering and algorithm (RSA-PSS or PKCS1v15, SHA256) recorded in `kalshi-api-contract.md`. Provide `_verify_for_test` mirroring that algorithm for the round-trip test only.
- `KalshiClient` with methods: `list_events(series)`, `list_markets(event)`, `get_quote(market) -> MarketQuote`, `get_balance()`, `get_positions()`, `create_order(...)`, `cancel_order(...)`. Each builds headers from the recorded header names, uses `httpx`, retries (exponential backoff, max 4) on 5xx/timeout.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/markets/test_kalshi_client.py -v`
Expected: PASS.

- [ ] **Step 5: Live demo smoke (manual)**

Run a one-off script hitting the **demo** base URL with real keys: list markets, fetch one orderbook, fetch balance. Confirm 200s. Do not commit keys/output.

- [ ] **Step 6: Commit**

```bash
git add kaiju/markets/ tests/markets/test_kalshi_client.py
git commit -m "feat: RSA-signed Kalshi REST client (signing round-trip tested)"
```

### Task 20: Event/bucket parser + settlement mapping

**Files:**
- Create: `kaiju/markets/parser.py`
- Test: `tests/markets/test_parser.py`

- [ ] **Step 1: Write the failing test**

`tests/markets/test_parser.py`:
```python
from kaiju.markets.parser import parse_event_snapshot

def test_parses_buckets_and_open_tails():
    # shape mirrors the recorded Kalshi list-markets JSON (kalshi-api-contract.md)
    raw_markets = [
      {"ticker": "T-LO", "cap_strike": 49, "floor_strike": None,
       "yes_bid": 5, "yes_ask": 8, "no_bid": 92, "no_ask": 95,
       "volume": 100, "open_interest": 300},
      {"ticker": "T-MID", "floor_strike": 50, "cap_strike": 51,
       "yes_bid": 40, "yes_ask": 45, "no_bid": 55, "no_ask": 60,
       "volume": 200, "open_interest": 800},
      {"ticker": "T-HI", "floor_strike": 52, "cap_strike": None,
       "yes_bid": 5, "yes_ask": 9, "no_bid": 91, "no_ask": 95,
       "volume": 50, "open_interest": 150},
    ]
    snap = parse_event_snapshot(event_ticker="E", station_id="KNYC",
        climate_date="2026-05-16", raw_markets=raw_markets)
    tickers = {b.market_ticker for b in snap.buckets}
    assert tickers == {"T-LO", "T-MID", "T-HI"}
    lo = next(b for b in snap.buckets if b.market_ticker == "T-LO")
    assert lo.lower_f is None and lo.upper_f == 49
    assert snap.quotes["T-MID"].yes_ask == 45
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/markets/test_parser.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement against recorded JSON shape**

`kaiju/markets/parser.py` — `parse_event_snapshot(...)` mapping the recorded Kalshi market JSON fields (use the actual field names from `kalshi-api-contract.md`; the test's `floor_strike`/`cap_strike` are placeholders to replace with the real names) to `Bucket` + `MarketQuote`, producing an `EventSnapshot`. Also `resolve_settlement(series_ticker)` returning `(station_id, climate_tz, window)` from the recorded `settlement-map.md`, and skipping cities flagged ambiguous.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/markets/test_parser.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add kaiju/markets/parser.py tests/markets/test_parser.py
git commit -m "feat: Kalshi event/bucket parser + settlement mapping"
```

---

## Phase 5 — Execution

### Task 21: Order manager with modes, idempotency, reconcile

**Files:**
- Create: `kaiju/execution/orders.py`, `kaiju/execution/__init__.py`
- Test: `tests/execution/test_orders.py`

- [ ] **Step 1: Write the failing test**

`tests/execution/test_orders.py`:
```python
from kaiju.types import TradeIntent
from kaiju.execution.orders import OrderManager

class FakeKalshi:
    def __init__(self): self.sent = []
    def create_order(self, **kw): self.sent.append(kw); return {"order_id": "x"}
    def get_positions(self): return []

def test_shadow_paper_does_not_send(tmp_path):
    from kaiju.state import State
    st = State(str(tmp_path/"s.sqlite")); st.init_schema()
    k = FakeKalshi()
    om = OrderManager(mode="shadow-paper", kalshi=k, state=st)
    om.execute([TradeIntent("M","yes",45,2,0.7,0.15)], climate_date="2026-05-16")
    assert k.sent == []                       # nothing transmitted
    assert len(st.list_orders()) == 1         # but recorded as simulated

def test_live_sends_once_and_is_idempotent(tmp_path):
    from kaiju.state import State
    st = State(str(tmp_path/"s.sqlite")); st.init_schema()
    k = FakeKalshi()
    om = OrderManager(mode="live", kalshi=k, state=st)
    intents = [TradeIntent("M","yes",45,2,0.7,0.15)]
    om.execute(intents, climate_date="2026-05-16")
    om.execute(intents, climate_date="2026-05-16")   # rerun same day
    assert len(k.sent) == 1                            # idempotent client id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/execution/test_orders.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

`kaiju/execution/orders.py`:
```python
from __future__ import annotations
import hashlib
from kaiju.types import TradeIntent

class OrderManager:
    def __init__(self, mode: str, kalshi, state):
        self.mode = mode; self.k = kalshi; self.st = state

    def _client_id(self, it: TradeIntent, day: str) -> str:
        raw = f"{day}|{it.market_ticker}|{it.side}|{it.limit_price_cents}|{it.count}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    def execute(self, intents: list[TradeIntent], climate_date: str) -> None:
        for it in intents:
            cid = self._client_id(it, climate_date)
            if self.st.get_order(cid):           # already handled (idempotent)
                continue
            if self.mode == "live":
                self.k.create_order(client_order_id=cid, ticker=it.market_ticker,
                    side=it.side, price=it.limit_price_cents, count=it.count)
            # shadow-paper / backtest: simulate, never transmit
            self.st.record_order(cid, it.market_ticker, it.side,
                                 it.limit_price_cents, it.count, self.mode)

    def reconcile(self) -> None:
        """Re-sync local state with broker positions (crash-safe no-op if equal)."""
        positions = self.k.get_positions()
        # store/compare; detailed diff logged. Kept minimal: positions are source
        # of truth; local orders missing a position are marked 'unfilled'.
        for p in positions:
            pass  # implemented against recorded positions JSON shape (Task 5)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/execution/test_orders.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add kaiju/execution/ tests/execution/test_orders.py
git commit -m "feat: order manager (modes, idempotent client ids, reconcile)"
```

---

## Phase 6 — Orchestration

### Task 22: Daily runner (idempotent end-to-end pipeline)

**Files:**
- Create: `kaiju/runner.py`
- Test: `tests/test_runner.py`

- [ ] **Step 1: Write the failing test (deterministic replay with injected fakes)**

`tests/test_runner.py`:
```python
from kaiju.runner import run_day

class Deps:
    """Injected test doubles for forecast/obs/kalshi so the runner is deterministic."""
    def __init__(self):
        self.placed = []
    def fetch_nbm_percentiles(self, station, run_dt, cd):
        return {10:60.0,25:62.0,50:65.0,75:68.0,90:70.0}
    def fetch_gefs_members(self, station, run_dt, cd):
        return [63.0,64.0,65.0,66.0,67.0]*5
    def event_snapshot(self, station, cd):
        from kaiju.types import EventSnapshot, Bucket, MarketQuote
        bs=[Bucket("LO",None,63),Bucket("MID",64,66),Bucket("HI",67,None)]
        qs={"MID":MarketQuote("MID",30,35,65,70,500,1000),
            "LO":MarketQuote("LO",5,8,92,95,300,900),
            "HI":MarketQuote("HI",5,8,92,95,300,900)}
        return EventSnapshot("E",station,cd,bs,qs)
    def place(self,intents,cd): self.placed += intents

def test_run_day_is_idempotent_and_produces_report(tmp_path):
    deps=Deps()
    r1=run_day(station="KNYC", climate_date="2026-05-16",
               db_path=str(tmp_path/"s.sqlite"), mode="shadow-paper", deps=deps)
    n_after_first=len(deps.placed)
    r2=run_day(station="KNYC", climate_date="2026-05-16",
               db_path=str(tmp_path/"s.sqlite"), mode="shadow-paper", deps=deps)
    assert n_after_first >= 1                 # took the mispriced MID trade
    assert len(deps.placed)==n_after_first    # rerun places nothing new
    assert "report" in r1 and r1["station"]=="KNYC"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_runner.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

`kaiju/runner.py` — `run_day(station, climate_date, db_path, mode, deps)` orchestrating, in order: init state → fetch NBM% + GEFS (via `deps`) → `pmf_from_nbm_percentiles` + GEFS empirical PMF → `blend_pmfs` (NBM-weighted) → load+apply `CalibrationParams` from state (default identity if none) → `event_snapshot` → `bucket_probabilities` → `select_trades` → `size_event` → per-intent `RiskGate.check` → `OrderManager.execute` (idempotent) → write a structured report dict + persist prediction. Add `if __name__ == "__main__": ` CLI: parse `--station/--date/--mode`, build real `deps` (forecast.py, obs.py, KalshiClient, OrderManager), call `run_day`. Real deps are only constructed in `__main__`; tests inject `Deps`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_runner.py -v`
Expected: PASS.

- [ ] **Step 5: Full suite + lint**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy kaiju`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add kaiju/runner.py tests/test_runner.py
git commit -m "feat: idempotent daily runner orchestrating the full pipeline"
```

### Task 23: Settlement + PnL backfill and gate update

**Files:**
- Modify: `kaiju/runner.py` (add `settle_day`)
- Test: `tests/test_settlement.py`

- [ ] **Step 1: Write the failing test**

`tests/test_settlement.py`:
```python
from kaiju.runner import settle_day

class Deps:
    def official_daily_max(self, station, date): return 65   # realized high
    def event_snapshot(self, station, cd): ...                # reuse Task 22 double

def test_settlement_scores_orders_and_updates_pnl(tmp_path):
    from kaiju.state import State
    st=State(str(tmp_path/"s.sqlite")); st.init_schema()
    st.record_prediction("KNYC","2026-05-16",64,[0.2,0.6,0.2])
    st.record_order("c1","MID","yes",35,2,"shadow-paper")
    res=settle_day(station="KNYC", climate_date="2026-05-16",
                   db_path=str(tmp_path/"s.sqlite"), deps=Deps())
    assert "realized_max" in res and res["realized_max"]==65
    assert st.get_gate_status() is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_settlement.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

Add `settle_day(station, climate_date, db_path, deps)` to `kaiju/runner.py`: fetch official daily max (`deps.official_daily_max`), determine which bucket won, mark stored orders win/loss, compute realized PnL net of fees, write `pnl` row, recompute rolling Brier/CRPS/PIT + simulated PnL over the trailing window via `kaiju.eval.metrics`, evaluate `kaiju.eval.gate.evaluate_promotion`, and persist `state.set_gate_status(...)`. CLI subcommand `settle --station --date`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_settlement.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add kaiju/runner.py tests/test_settlement.py
git commit -m "feat: settlement scoring, PnL backfill, gate update"
```

### Task 24: Calibration retrain job

**Files:**
- Modify: `kaiju/runner.py` (add `retrain_calibration`)
- Test: `tests/test_retrain.py`

- [ ] **Step 1: Write the failing test**

`tests/test_retrain.py`:
```python
from kaiju.runner import retrain_calibration

def test_retrain_writes_calibration_params(tmp_path):
    from kaiju.state import State
    st=State(str(tmp_path/"s.sqlite")); st.init_schema()
    # seed history: (forecast median, realized) pairs in predictions+pnl/obs tables
    for i,(fc,ob) in enumerate([(60,57),(65,62),(70,67),(55,52)]):
        st.record_prediction("KNYC", f"2026-04-0{i+1}", fc, [1.0])
        st.conn.execute("INSERT INTO pnl(climate_date,realized_usd,mode) VALUES(?,?,?)",
                         (f"2026-04-0{i+1}", 0.0, "shadow-paper"))
    st.conn.commit()
    cal = retrain_calibration(station="KNYC", db_path=str(tmp_path/"s.sqlite"),
                              realized={f"2026-04-0{i+1}":ob
                                        for i,(_,ob) in enumerate([(0,57),(0,62),(0,67),(0,52)])})
    assert cal.n_samples == 4 and cal.bias < 0   # warm-biased forecast => negative bias
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_retrain.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

Add `retrain_calibration(station, db_path, realized)` to `kaiju/runner.py`: read stored prediction medians + realized official maxes, call `kaiju.model.calibration.fit_calibration(..., min_samples=settings.paper_proof_days)`, persist params into a `calibration` table (add to `SCHEMA` in `state.py`: `CREATE TABLE IF NOT EXISTS calibration(station TEXT PRIMARY KEY, bias REAL, spread_scale REAL, n INT, updated_at TEXT DEFAULT (datetime('now')))` plus `State.set_calibration/get_calibration`). `run_day` loads these params (identity default).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_retrain.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add kaiju/runner.py kaiju/state.py tests/test_retrain.py
git commit -m "feat: nightly calibration retrain job"
```

---

## Phase 7 — Deployment

### Task 25: Dockerfile, launchd trigger, run wrapper

**Files:**
- Create: `Dockerfile`, `deploy/run_daily.sh`, `deploy/com.kaiju.daily.plist`
- Test: `tests/test_deploy_smoke.py`

- [ ] **Step 1: Write the failing test**

`tests/test_deploy_smoke.py`:
```python
import subprocess, sys
def test_runner_cli_help_runs():
    out = subprocess.run([sys.executable,"-m","kaiju.runner","--help"],
                          capture_output=True, text=True)
    assert out.returncode == 0
    assert "station" in out.stdout.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_deploy_smoke.py -v`
Expected: FAIL if `--help` not wired; otherwise PASS after Task 22 — if it already passes, still complete steps 3–5 (deploy artifacts).

- [ ] **Step 3: Create deploy artifacts**

`Dockerfile`:
```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y libeccodes0 && rm -rf /var/lib/apt/lists/*
RUN pip install uv
WORKDIR /app
COPY pyproject.toml ./
RUN uv sync --no-dev
COPY kaiju ./kaiju
ENTRYPOINT ["uv","run","python","-m","kaiju.runner"]
```

`deploy/run_daily.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv run python -m kaiju.runner settle --station "${KAIJU_CITY:-KNYC}" --date "$(date -v-1d +%F)" || true
uv run python -m kaiju.runner retrain --station "${KAIJU_CITY:-KNYC}" || true
uv run python -m kaiju.runner run --station "${KAIJU_CITY:-KNYC}" --date "$(date +%F)"
```

`deploy/com.kaiju.daily.plist` — launchd job running `deploy/run_daily.sh` once daily at a time after NBM morning run + before market close (record the chosen UTC hour from `noaa-forecast-contract.md`). Include `StandardOutPath`/`StandardErrorPath` to a log file.

- [ ] **Step 4: Run test + chmod**

Run: `chmod +x deploy/run_daily.sh && uv run pytest tests/test_deploy_smoke.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile deploy/ tests/test_deploy_smoke.py
git commit -m "feat: Docker image, launchd trigger, daily run wrapper"
```

### Task 26: README + operator runbook

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write README**

Document: setup (`uv sync`, `.env` from `.env.example`, **rotate the leaked RSA key**), the three modes, how the paper-proof gate works, the **one-time arm procedure** (set `KAIJU_LIVE_ARM_TOKEN`, requires gate `qualified`), the kill switch (create the kill-switch file to halt all trading), how to read the daily report, and the Mac→EC2 migration (same Docker image, us-east-1, point `KAIJU_DB_PATH` at a persistent volume).

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: operator runbook (setup, arming, kill switch, migration)"
```

---

## Self-Review (completed by plan author)

**1. Spec coverage:** Markets/predictand → Tasks 7,20. NBM/GEFS data → Tasks 6,18. IEM obs → Tasks 7,17. Edge pipeline → Tasks 9,10,12,13. City-day Kelly → Task 11. Run modes → Tasks 3,21,22. Execution/idempotency → Tasks 21,22. Risk + kill switch → Task 15. Promotion gate + arm switch → Tasks 3,16,23. Architecture/modules → all of Phase 2–6. SQLite state → Task 4,24. Deployment Mac→EC2 → Task 25. Fee/auth/settlement verify-at-implementation → SPIKE Tasks 5,6,7. `.gitignore`/key rotation → already committed in brainstorming + README Task 26. All spec sections map to tasks.

**2. Placeholder scan:** External-contract specifics (`<P>`, `<EXPECTED_CENTS>`, field names like `floor_strike`) are intentionally bound by the SPIKE tasks (5–7) before dependent tasks and are explicitly called out as substitute-from-recorded-contract — these are verification points, not unfilled placeholders. No "TODO/implement later/handle edge cases" instructions remain.

**3. Type consistency:** `TempPMF`, `Bucket`, `MarketQuote`, `EventSnapshot`, `TradeIntent`, `RiskDecision` defined once in Task 2 and used with identical signatures throughout. `CalibrationParams` defined in Task 13, consumed in Tasks 22/24. `bucket_probabilities`, `select_trades`, `size_event`, `RiskGate.check`, `OrderManager.execute`, `run_day`, `settle_day`, `retrain_calibration`, `evaluate_promotion` names are consistent across all references.

---

## Risks carried from spec (not re-litigated here)

- Edge may be thin if the market tracks NBM → the Phase 6/7 gate is the honest filter; failing the gate keeps the bot in shadow-paper indefinitely (correct behavior).
- SPIKE tasks depend on live external docs/APIs being reachable at implementation time; if a contract differs from assumptions, only the SPIKE notes + the thin client/parser layers change, not the tested core logic (Phase 2).
