# Kalshi Weather Mispricing-Capture (v2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trade the gap between live Kalshi temperature-bucket prices and a continuously-updated model fair value (forecast PMF + intraday nowcast), exiting on convergence / thesis-invalidation / time-stop, with hold-to-settlement as the bounded fallback, driven by a WebSocket intraday loop.

**Architecture:** Pure deterministic core (nowcast, fair value, gap selection, exit policy, risk, metrics) built test-first with full code. IO layers (IEM obs, Herbie forecast, Kalshi REST + WebSocket, parser) built against the SPIKE-recorded contracts in `docs/superpowers/notes/`, tested offline with committed fixtures + mocks. A long-running intraday runner wires a WebSocket event loop with reconnect/REST-reconcile and independent fair-value/safety timers; shadow-paper simulates intraday fills against the live book.

**Tech Stack:** Python 3.12, `uv`, `pydantic`, `numpy`/`scipy`/`pandas`, `xarray`+`herbie-data`+`cfgrib`, `httpx`, `websockets`, `cryptography`, `structlog`, stdlib `sqlite3`, `pytest`+`respx`, `ruff`, `mypy`, Docker.

**Specs:** v2 `docs/superpowers/specs/2026-05-17-kalshi-weather-mispricing-capture-design.md` (authoritative). Recorded external contracts: `docs/superpowers/notes/kalshi-api-contract.md`, `noaa-forecast-contract.md`, `settlement-map.md`.

---

## Status carried forward (v1 Tasks 1–11 — DONE, do NOT re-implement)

Built, committed, both-reviews-passed on `main`: scaffold; `kaiju/types.py`; `kaiju/config.py` (+`kaiju/logging.py`); `kaiju/state.py`; the 3 SPIKE contracts; `kaiju/strategy/fees.py` (`trade_fee_cents`); `kaiju/strategy/edge.py` `bucket_probabilities`; `kaiju/strategy/edge.py` `select_trades`; `kaiju/strategy/sizing.py` `size_event` + `_kelly_fraction`. The full pytest suite is green. **`select_trades`, `bucket_probabilities`, `size_event`, `trade_fee_cents` keep their signatures and are reused/generalized below.**

**Cross-task contracts (enforce):** `Settings.kalshi_private_key`/`live_arm_token` are `pydantic.SecretStr` → callers use `.get_secret_value()`; `Settings` is `frozen=True`. NBM = Herbie `model="nbmqmd"`. Kalshi fee coefficient UNVERIFIED → keep pinned, cross-check vs a live demo fill. Ticker `KXHIGHNY`; IEM station `NYTNYC`/network `NYCLIMATE` (`max_tmpf`); settlement Central Park, climate day local midnight–midnight `America/New_York`. Kalshi `*.5` bracket strikes MUST become correct inclusive integer `Bucket` bounds (Task 13 enforces).

**Conventions:** TDD per task (failing test → run fail → minimal impl → run pass → commit). `uv run pytest`, `uv run ruff check kaiju tests`, `uv run mypy kaiju` all green before commit. Commit trailer: `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`. Tasks marked **[SPIKE-STEP]** verify a live contract and record it to `docs/superpowers/notes/` before implementing against it — do not fabricate.

---

## File structure (v2 additions/changes)

```
kaiju/types.py            # +Position, +ExitDecision, +ExitAction (extend)
kaiju/config.py           # +validators (Task 1); +v2 knobs (Task 1)
kaiju/state.py            # +positions/working_orders/calibration tables + DAL (Task 9)
kaiju/strategy/sizing.py  # Task 1 review-fixes
kaiju/strategy/edge.py    # +select_gap_trades (Task 5)
kaiju/strategy/fairvalue.py   # NEW pmf->fair cents per bucket (Task 4)
kaiju/strategy/exit_policy.py # NEW convergence/thesis/time-stop (Task 6)
kaiju/model/nowcast.py        # NEW observed-temp conditioning (Task 3)
kaiju/risk/limits.py          # NEW round-trip-aware risk gate (Task 7)
kaiju/eval/metrics.py         # NEW Brier/CRPS/PIT + v2 metrics (Task 8)
kaiju/eval/gate.py            # NEW promotion gate + arm (Task 8)
kaiju/data/obs.py             # NEW IEM daily-max + intraday obs (Task 10)
kaiju/data/forecast.py        # NEW NBM(nbmqmd)/GEFS via Herbie (Task 11)
kaiju/markets/kalshi_client.py# NEW RSA-signed REST (Task 12)
kaiju/markets/parser.py       # NEW event/bucket parse + *.5->int (Task 13)
kaiju/markets/ws_client.py    # NEW WebSocket book/fills (Task 14)
kaiju/execution/position_manager.py # NEW (Task 15)
kaiju/execution/paper_sim.py        # NEW intraday fill sim (Task 16)
kaiju/runner.py               # NEW intraday event loop + lifecycle (Tasks 17/18/19)
Dockerfile, deploy/, README.md      # Tasks 20/21
docs/superpowers/notes/kalshi-ws-contract.md # Task 14 [SPIKE-STEP]
tests/... mirrors kaiju/
```

---

## Task 1: Apply pending Task-11 code-review fixes

**Files:** Modify `kaiju/strategy/sizing.py`, `kaiju/config.py`; Test `tests/strategy/test_sizing.py`, `tests/test_config.py`.

- [ ] **Step 1: Add failing tests** to `tests/strategy/test_sizing.py`:
```python
import pytest
from kaiju.types import TradeIntent
from kaiju.strategy.sizing import size_event

def _it(tkr,p,price,edge,c=1): return TradeIntent(tkr,"yes",price,c,p,edge)

def test_negative_or_zero_net_edge_dropped():
    assert size_event([_it("M",0.5,50,-0.1)], 500, 0.25, 0.10) == []
    assert size_event([_it("M",0.5,50,0.0)], 500, 0.25, 0.10) == []

def test_kelly_fraction_gt_one_still_budget_capped():
    sized = size_event([_it("M",0.9,30,0.5)], 500, 5.0, 0.10)
    assert sum(s.count*0.30 for s in sized) <= 0.10*500 + 1e-9

def test_single_intent_exceeding_budget_capped():
    sized = size_event([_it("A",0.9,10,0.5)], 100, 0.25, 0.10)
    assert sum(s.count*0.10 for s in sized) <= 0.10*100 + 1e-9

def test_invalid_params_raise():
    with pytest.raises(ValueError): size_event([_it("M",0.7,40,0.2)], 500, 0.0, 0.10)
    with pytest.raises(ValueError): size_event([_it("M",0.7,40,0.2)], 500, 1.5, 0.10)
    with pytest.raises(ValueError): size_event([_it("M",0.7,40,0.2)], 500, 0.25, 0.0)
    with pytest.raises(ValueError): size_event([_it("M",0.7,40,0.2)], 500, 0.25, 1.5)
```
Add to `tests/test_config.py`:
```python
def test_config_rejects_out_of_range_kelly_and_frac(monkeypatch):
    base={"KALSHI_KEY_ID":"a","KALSHI_PRIVATE_KEY":"k","KAIJU_MODE":"backtest","KAIJU_CITIES":"KNYC"}
    for k,v in [("KAIJU_KELLY_FRACTION","1.5"),("KAIJU_KELLY_FRACTION","0"),
                ("KAIJU_MAX_BANKROLL_FRAC_PER_EVENT","1.5"),("KAIJU_MAX_BANKROLL_FRAC_PER_EVENT","0")]:
        for bk,bv in base.items(): monkeypatch.setenv(bk,bv)
        monkeypatch.setenv(k,v)
        with pytest.raises(Exception):
            from kaiju.config import Settings; Settings()
```

- [ ] **Step 2: Run** `uv run pytest tests/strategy/test_sizing.py tests/test_config.py -v` → expect FAILs.

- [ ] **Step 3: Implement.** In `kaiju/strategy/sizing.py`: rename `_kelly_fraction` → `_has_positive_edge` returning `bool` (`c=price_cents/100.0; return 0.0 < c < 1.0 and p > c`), update its single call site to `if not _has_positive_edge(it.model_prob, it.limit_price_cents): continue`, update docstring. At the top of `size_event` add:
```python
if not (0.0 < kelly_fraction <= 1.0):
    raise ValueError(f"kelly_fraction must be in (0,1], got {kelly_fraction}")
if not (0.0 < max_bankroll_frac <= 1.0):
    raise ValueError(f"max_bankroll_frac must be in (0,1], got {max_bankroll_frac}")
```
In `kaiju/config.py` add `gt=0, le=1` to the `kelly_fraction` and `max_bankroll_frac_per_event` `Field(...)` definitions (keep `validation_alias`/defaults 0.25 / 0.10).

- [ ] **Step 4: Run** `uv run pytest -q` → all green; `uv run ruff check kaiju tests`; `uv run mypy kaiju`.

- [ ] **Step 5: Commit** `git add kaiju/strategy/sizing.py kaiju/config.py tests/ && git commit -m "fix: Task-11 review (gate rename, fail-loud guards, config validators)"`

## Task 2: v2 domain types

**Files:** Modify `kaiju/types.py`; Test `tests/test_types_v2.py`.

- [ ] **Step 1: Failing test** `tests/test_types_v2.py`:
```python
from kaiju.types import Position, ExitDecision, ExitAction

def test_position_fields():
    p = Position(market_ticker="M", side="yes", count=3, avg_entry_cents=44, climate_date="2026-05-17")
    assert p.count == 3 and p.side == "yes" and p.avg_entry_cents == 44

def test_exit_decision_actions():
    d = ExitDecision(action=ExitAction.EXIT, limit_price_cents=61, reason="converged")
    assert d.action is ExitAction.EXIT and d.limit_price_cents == 61
    h = ExitDecision(action=ExitAction.HOLD, limit_price_cents=None, reason="gap open")
    assert h.action is ExitAction.HOLD and h.limit_price_cents is None
```

- [ ] **Step 2: Run** `uv run pytest tests/test_types_v2.py -v` → FAIL.

- [ ] **Step 3: Append to `kaiju/types.py`:**
```python
from enum import Enum

@dataclass(frozen=True)
class Position:
    market_ticker: str
    side: Literal["yes", "no"]
    count: int
    avg_entry_cents: int
    climate_date: str

class ExitAction(Enum):
    HOLD = "hold"
    EXIT = "exit"      # close via limit at limit_price_cents
    CUT = "cut"        # thesis invalidated; close now

@dataclass(frozen=True)
class ExitDecision:
    action: ExitAction
    limit_price_cents: Optional[int]
    reason: str
```

- [ ] **Step 4: Run** `uv run pytest tests/test_types_v2.py -v` → PASS; full suite green; ruff/mypy clean.

- [ ] **Step 5: Commit** `git add kaiju/types.py tests/test_types_v2.py && git commit -m "feat: v2 domain types (Position, ExitDecision)"`

## Task 3: Nowcast updater

**Files:** Create `kaiju/model/nowcast.py`; Test `tests/model/test_nowcast.py`.

- [ ] **Step 1: Failing test** `tests/model/test_nowcast.py`:
```python
import pytest
from kaiju.types import TempPMF
from kaiju.model.nowcast import nowcast_pmf

def test_running_max_left_truncates():
    base = TempPMF.from_probs(60, [0.2,0.2,0.2,0.2,0.2])  # 60..64
    out = nowcast_pmf(base, observed_max_f=62, minutes_past_peak=-120, remaining_forecast_max_f=70)
    assert out.prob_interval(None, 61) == 0.0          # below observed max removed
    assert pytest.approx(out.probs.sum()) == 1.0       # renormalized
    assert out.prob_interval(62, None) == pytest.approx(1.0)

def test_post_peak_collapses_upside():
    base = TempPMF.from_probs(60, [0.1,0.1,0.2,0.3,0.3])  # 60..64
    out = nowcast_pmf(base, observed_max_f=63, minutes_past_peak=120, remaining_forecast_max_f=63)
    # past peak, remaining max == observed: distribution concentrates at 63
    assert out.prob_at(63) == pytest.approx(1.0)

def test_pre_peak_keeps_upside_above_remaining_forecast_capped():
    base = TempPMF.from_probs(60, [0.2,0.2,0.2,0.2,0.2])
    out = nowcast_pmf(base, observed_max_f=61, minutes_past_peak=-60, remaining_forecast_max_f=63)
    assert out.prob_interval(64, None) == 0.0   # capped at remaining forecast max
    assert out.prob_interval(61, 63) == pytest.approx(1.0)
```

- [ ] **Step 2: Run** `uv run pytest tests/model/test_nowcast.py -v` → FAIL.

- [ ] **Step 3: Implement** `kaiju/model/nowcast.py`:
```python
from __future__ import annotations
import numpy as np
from kaiju.types import TempPMF

def nowcast_pmf(base: TempPMF, observed_max_f: int, minutes_past_peak: int,
                remaining_forecast_max_f: int | None) -> TempPMF:
    """Condition the calibrated daily-max PMF on intraday observations.

    - Left-truncate at observed_max_f (daily max cannot be below it).
    - Cap the upside at the still-attainable max: if past the peak hour
      (minutes_past_peak >= 0) the ceiling is max(observed, remaining
      forecast); pre-peak the ceiling is the remaining forecast max
      (fallback: base high). Mass outside [floor, ceil] is removed and
      the distribution renormalized. No artificial point mass added.
    """
    temps = np.arange(base.low_f, base.high_f + 1)
    floor = observed_max_f
    if remaining_forecast_max_f is None:
        ceil = base.high_f
    elif minutes_past_peak >= 0:
        ceil = max(observed_max_f, remaining_forecast_max_f)
    else:
        ceil = max(observed_max_f, remaining_forecast_max_f)
    mask = (temps >= floor) & (temps <= ceil)
    w = np.where(mask, base.probs, 0.0)
    if w.sum() <= 0:                      # observation outside model support
        idx = np.clip(observed_max_f - base.low_f, 0, len(temps) - 1)
        w = np.zeros_like(base.probs); w[idx] = 1.0
    return TempPMF.from_probs(low_f=base.low_f, probs=w)
```

- [ ] **Step 4: Run** `uv run pytest tests/model/test_nowcast.py -v` → PASS; full suite green; ruff/mypy clean.

- [ ] **Step 5: Commit** `git add kaiju/model/nowcast.py tests/model/test_nowcast.py && git commit -m "feat: nowcast PMF conditioning (running-max floor + upside cap)"`

## Task 4: Fair value (PMF → cents per bucket)

**Files:** Create `kaiju/strategy/fairvalue.py`; Test `tests/strategy/test_fairvalue.py`.

- [ ] **Step 1: Failing test** `tests/strategy/test_fairvalue.py`:
```python
from kaiju.types import TempPMF, Bucket
from kaiju.strategy.fairvalue import fair_prices

def test_fair_prices_are_rounded_cents_summing_near_100():
    pmf = TempPMF.from_probs(48, [0.1,0.2,0.4,0.2,0.1])
    buckets=[Bucket("LO",None,49),Bucket("M",50,51),Bucket("HI",52,None)]
    fp = fair_prices(pmf, buckets)
    assert fp == {"LO":30, "M":60, "HI":10}
    assert 99 <= sum(fp.values()) <= 101
```

- [ ] **Step 2: Run** `uv run pytest tests/strategy/test_fairvalue.py -v` → FAIL.

- [ ] **Step 3: Implement** `kaiju/strategy/fairvalue.py`:
```python
from __future__ import annotations
from kaiju.types import TempPMF, Bucket
from kaiju.strategy.edge import bucket_probabilities

def fair_prices(pmf: TempPMF, buckets: list[Bucket]) -> dict[str, int]:
    """Fair value per bucket in cents = round(100 * P(bucket))."""
    probs = bucket_probabilities(pmf, buckets)
    return {tkr: int(round(100.0 * p)) for tkr, p in probs.items()}
```

- [ ] **Step 4: Run** `uv run pytest tests/strategy/test_fairvalue.py -v` → PASS; full suite; ruff/mypy.

- [ ] **Step 5: Commit** `git add kaiju/strategy/fairvalue.py tests/strategy/test_fairvalue.py && git commit -m "feat: fair value cents per bucket"`

## Task 5: Gap-to-fair, position-aware selection

**Files:** Modify `kaiju/strategy/edge.py` (append); Test `tests/strategy/test_gap_select.py`.

- [ ] **Step 1: Failing test** `tests/strategy/test_gap_select.py`:
```python
from kaiju.types import MarketQuote, Position
from kaiju.strategy.edge import select_gap_trades

def q(t,ya,na,oi=1000): return MarketQuote(t,ya-3,ya,na-3,na,500,oi)

def test_buys_underpriced_side_when_gap_clears_cost():
    fair={"M":70}; quotes={"M":q("M",55,48)}   # fair 70 > yes_ask 55 -> buy yes
    out=select_gap_trades(fair,quotes,positions={},net_edge_threshold=0.08,min_open_interest=100)
    assert len(out)==1 and out[0].side=="yes" and out[0].limit_price_cents==55

def test_skips_when_already_positioned():
    fair={"M":70}; quotes={"M":q("M",55,48)}
    pos={"M":Position("M","yes",2,55,"2026-05-17")}
    assert select_gap_trades(fair,quotes,pos,0.08,100)==[]

def test_skips_thin_book_and_small_gap():
    assert select_gap_trades({"M":52},{"M":q("M",50,52)},{},0.08,100)==[]
    assert select_gap_trades({"M":99},{"M":q("M",5,95,oi=10)},{},0.08,100)==[]
```

- [ ] **Step 2: Run** `uv run pytest tests/strategy/test_gap_select.py -v` → FAIL.

- [ ] **Step 3: Append to `kaiju/strategy/edge.py`** (imports at top with existing ones):
```python
from kaiju.types import Position

def select_gap_trades(fair_cents: dict[str, int], quotes: dict[str, MarketQuote],
                       positions: dict[str, Position], net_edge_threshold: float,
                       min_open_interest: int) -> list[TradeIntent]:
    """Enter the cheap side when |fair-market| clears fee+spread+threshold.
    Position-aware: skip a market we already hold (exits handled elsewhere)."""
    out: list[TradeIntent] = []
    for tkr, fair in fair_cents.items():
        if tkr in positions:
            continue
        q = quotes.get(tkr)
        if q is None or q.open_interest < min_open_interest:
            continue
        p = fair / 100.0
        if q.yes_ask is not None and 1 <= q.yes_ask <= 99:
            edge = p - q.yes_ask/100.0 - trade_fee_cents(q.yes_ask,1)/100.0
            if edge >= net_edge_threshold:
                out.append(TradeIntent(tkr,"yes",q.yes_ask,1,p,edge)); continue
        if q.no_ask is not None and 1 <= q.no_ask <= 99:
            edge = (1.0-p) - q.no_ask/100.0 - trade_fee_cents(q.no_ask,1)/100.0
            if edge >= net_edge_threshold:
                out.append(TradeIntent(tkr,"no",q.no_ask,1,1.0-p,edge))
    return out
```

- [ ] **Step 4: Run** `uv run pytest tests/strategy/test_gap_select.py -v` → PASS; full suite; ruff/mypy.

- [ ] **Step 5: Commit** `git add kaiju/strategy/edge.py tests/strategy/test_gap_select.py && git commit -m "feat: gap-to-fair position-aware trade selection"`

## Task 6: Exit policy

**Files:** Create `kaiju/strategy/exit_policy.py`; Test `tests/strategy/test_exit_policy.py`.

- [ ] **Step 1: Failing test** `tests/strategy/test_exit_policy.py`:
```python
from kaiju.types import Position, MarketQuote, ExitAction
from kaiju.strategy.exit_policy import decide_exit

P = Position("M","yes",3,45,"2026-05-17")
def q(yb,ya): return MarketQuote("M",yb,ya,100-ya,100-yb,500,1000)

def test_converged_triggers_exit_limit_at_fair_minus_margin():
    d = decide_exit(P, fair_cents=70, quote=q(68,71), minutes_to_timestop=120,
                     exit_margin_cents=5, fill_margin_cents=2)
    assert d.action is ExitAction.EXIT and d.limit_price_cents == 68  # fair70 - fill2, sell side

def test_thesis_invalidation_cuts_when_fair_drops_through_entry():
    d = decide_exit(P, fair_cents=40, quote=q(38,41), minutes_to_timestop=120,
                     exit_margin_cents=5, fill_margin_cents=2)
    assert d.action is ExitAction.CUT

def test_time_stop_holds_to_settlement_when_unfillable():
    d = decide_exit(P, fair_cents=90, quote=q(50,55), minutes_to_timestop=-1,
                     exit_margin_cents=5, fill_margin_cents=2)
    assert d.action is ExitAction.HOLD and "time-stop" in d.reason

def test_open_gap_holds():
    d = decide_exit(P, fair_cents=90, quote=q(60,63), minutes_to_timestop=120,
                     exit_margin_cents=5, fill_margin_cents=2)
    assert d.action is ExitAction.HOLD
```

- [ ] **Step 2: Run** `uv run pytest tests/strategy/test_exit_policy.py -v` → FAIL.

- [ ] **Step 3: Implement** `kaiju/strategy/exit_policy.py`:
```python
from __future__ import annotations
from kaiju.types import Position, MarketQuote, ExitDecision, ExitAction

def decide_exit(position: Position, fair_cents: int, quote: MarketQuote,
                minutes_to_timestop: int, exit_margin_cents: int,
                fill_margin_cents: int) -> ExitDecision:
    """Convergence / thesis-invalidation / time-stop exit logic.
    Position held is `side` of `count`; we close by trading the opposite side."""
    entry = position.avg_entry_cents
    # Thesis invalidation: fair has moved against the entry thesis.
    if position.side == "yes" and fair_cents <= entry:
        return ExitDecision(ExitAction.CUT, None, "thesis invalidated (fair<=entry)")
    if position.side == "no" and fair_cents >= entry:
        return ExitDecision(ExitAction.CUT, None, "thesis invalidated (fair>=entry)")
    # Time-stop: stop managing; hold remainder to settlement (bounded fallback).
    if minutes_to_timestop < 0:
        return ExitDecision(ExitAction.HOLD, None, "time-stop: hold to settlement")
    # Convergence: market within exit_margin of fair -> close via limit.
    mkt = quote.yes_bid if position.side == "yes" else quote.no_bid
    if mkt is not None and abs(fair_cents - mkt) <= exit_margin_cents:
        limit = max(1, min(99, fair_cents - fill_margin_cents))
        return ExitDecision(ExitAction.EXIT, limit, "converged")
    return ExitDecision(ExitAction.HOLD, None, "gap open")
```

- [ ] **Step 4: Run** `uv run pytest tests/strategy/test_exit_policy.py -v` → PASS; full suite; ruff/mypy.

- [ ] **Step 5: Commit** `git add kaiju/strategy/exit_policy.py tests/strategy/test_exit_policy.py && git commit -m "feat: exit policy (convergence/thesis/time-stop)"`

## Task 7: Round-trip-aware risk gate

**Files:** Create `kaiju/risk/limits.py`, `kaiju/risk/__init__.py`; Test `tests/risk/test_limits.py`.

- [ ] **Step 1: Failing test** `tests/risk/test_limits.py`:
```python
from kaiju.types import TradeIntent
from kaiju.risk.limits import RiskGate

def it(c=1,price=40): return TradeIntent("M","yes",price,c,0.7,0.15)

def test_kill_switch_blocks(tmp_path):
    ks=tmp_path/"KILL"; ks.write_text("x")
    g=RiskGate(str(ks),max_contracts_per_market=50,max_open_exposure_usd=500,
               max_daily_loss_usd=50,bankroll_usd=500)
    assert g.check(it(),realized_loss_today_usd=0,open_exposure_usd=0).approved is False

def test_daily_loss_blocks(tmp_path):
    g=RiskGate(str(tmp_path/"n"),50,500,50,500)
    d=g.check(it(),realized_loss_today_usd=50,open_exposure_usd=0)
    assert d.approved is False and "daily loss" in d.reason

def test_exposure_cap_blocks(tmp_path):
    g=RiskGate(str(tmp_path/"n"),50,100,50,500)
    d=g.check(it(c=10,price=40),realized_loss_today_usd=0,open_exposure_usd=99)
    assert d.approved is False and "exposure" in d.reason

def test_clamps_to_per_market_cap(tmp_path):
    g=RiskGate(str(tmp_path/"n"),max_contracts_per_market=5,max_open_exposure_usd=500,
               max_daily_loss_usd=50,bankroll_usd=500)
    d=g.check(it(c=999),0,0)
    assert d.approved and d.adjusted_count==5
```

- [ ] **Step 2: Run** `uv run pytest tests/risk/test_limits.py -v` → FAIL.

- [ ] **Step 3: Implement** `kaiju/risk/limits.py`:
```python
from __future__ import annotations
import os
from kaiju.types import TradeIntent, RiskDecision

class RiskGate:
    def __init__(self, kill_switch_path: str, max_contracts_per_market: int,
                 max_open_exposure_usd: float, max_daily_loss_usd: float,
                 bankroll_usd: float):
        self.kill=kill_switch_path; self.max_ct=max_contracts_per_market
        self.max_exp=max_open_exposure_usd; self.max_loss=max_daily_loss_usd
        self.bankroll=bankroll_usd

    def check(self, intent: TradeIntent, realized_loss_today_usd: float,
              open_exposure_usd: float) -> RiskDecision:
        if os.path.exists(self.kill):
            return RiskDecision(False,"kill switch engaged",0)
        if realized_loss_today_usd >= self.max_loss:
            return RiskDecision(False,"daily loss limit reached",0)
        if intent is None or intent.count < 1:
            return RiskDecision(False,"no tradeable intent",0)
        count=min(intent.count,self.max_ct)
        add=count*intent.limit_price_cents/100.0
        if open_exposure_usd+add > self.max_exp:
            return RiskDecision(False,"open exposure cap exceeded",0)
        if add > self.bankroll:
            return RiskDecision(False,"exceeds bankroll",0)
        return RiskDecision(True,"ok",count)
```

- [ ] **Step 4: Run** `uv run pytest tests/risk/test_limits.py -v` → PASS; full suite; ruff/mypy.

- [ ] **Step 5: Commit** `git add kaiju/risk/ tests/risk/test_limits.py && git commit -m "feat: round-trip-aware risk gate (kill/loss/exposure/size)"`

## Task 8: Eval metrics + promotion gate

**Files:** Create `kaiju/eval/metrics.py`, `kaiju/eval/gate.py`, `kaiju/eval/__init__.py`; Test `tests/eval/test_metrics.py`, `tests/eval/test_gate.py`.

- [ ] **Step 1: Failing tests.** `tests/eval/test_metrics.py`:
```python
import pytest
from kaiju.types import TempPMF
from kaiju.eval.metrics import brier_score, crps_pmf, pit_value, roundtrip_pnl_stats

def test_brier_and_crps_and_pit():
    assert brier_score([1.0],[1])==0.0
    assert crps_pmf(TempPMF.from_probs(70,[1.0]),70)==pytest.approx(0.0)
    assert 0.0 <= pit_value(TempPMF.from_probs(60,[0.2,0.3,0.5]),61) <= 1.0

def test_roundtrip_pnl_stats():
    s=roundtrip_pnl_stats([{"pnl_usd":2.0,"exited":True},{"pnl_usd":-1.0,"exited":False}])
    assert s["net_pnl_usd"]==pytest.approx(1.0)
    assert s["fill_rate"]==pytest.approx(0.5)
    assert s["n"]==2
```
`tests/eval/test_gate.py`:
```python
from kaiju.eval.gate import evaluate_promotion, GateCriteria, can_trade_live

def test_qualifies_and_arm_required():
    r=evaluate_promotion(days=30,brier=0.16,market_baseline_brier=0.20,
        pit_uniform_pvalue=0.4,sim_pnl_usd=18.0,trades=25,max_drawdown_usd=8.0,
        fill_rate=0.6,c=GateCriteria())
    assert r.qualified is True
    assert can_trade_live(True,True) and not can_trade_live(True,False) and not can_trade_live(False,True)

def test_fails_on_negative_pnl_or_low_fill_or_few_days():
    c=GateCriteria()
    assert evaluate_promotion(30,0.16,0.20,0.4,-1.0,25,8.0,0.6,c).qualified is False
    assert evaluate_promotion(30,0.16,0.20,0.4,18.0,25,8.0,0.05,c).qualified is False
    assert evaluate_promotion(5,0.16,0.20,0.4,18.0,25,8.0,0.6,c).qualified is False
```

- [ ] **Step 2: Run** `uv run pytest tests/eval -v` → FAIL.

- [ ] **Step 3: Implement.** `kaiju/eval/metrics.py`:
```python
from __future__ import annotations
import numpy as np
from kaiju.types import TempPMF

def brier_score(probs, outcomes) -> float:
    p=np.asarray(probs,float); y=np.asarray(outcomes,float)
    return float(np.mean((p-y)**2))

def crps_pmf(pmf: TempPMF, observed: int) -> float:
    temps=np.arange(pmf.low_f,pmf.high_f+1); cdf=np.cumsum(pmf.probs)
    h=(temps>=observed).astype(float)
    return float(np.sum((cdf-h)**2))

def pit_value(pmf: TempPMF, observed: int) -> float:
    return float(pmf.prob_interval(None,observed))

def roundtrip_pnl_stats(trades: list[dict]) -> dict:
    n=len(trades)
    net=float(sum(t["pnl_usd"] for t in trades))
    fr=float(sum(1 for t in trades if t.get("exited"))/n) if n else 0.0
    return {"n":n,"net_pnl_usd":net,"fill_rate":fr}
```
`kaiju/eval/gate.py`:
```python
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class GateCriteria:
    min_days:int=30; min_trades:int=15; min_pit_pvalue:float=0.05
    max_drawdown_usd:float=25.0; min_fill_rate:float=0.20

@dataclass(frozen=True)
class GateResult:
    qualified:bool; reason:str

def evaluate_promotion(days,brier,market_baseline_brier,pit_uniform_pvalue,
        sim_pnl_usd,trades,max_drawdown_usd,fill_rate,c:GateCriteria)->GateResult:
    if days<c.min_days: return GateResult(False,f"insufficient days ({days})")
    if trades<c.min_trades: return GateResult(False,f"insufficient trades ({trades})")
    if brier>=market_baseline_brier: return GateResult(False,"calibration not better than market")
    if pit_uniform_pvalue<c.min_pit_pvalue: return GateResult(False,"PIT not uniform")
    if sim_pnl_usd<=0: return GateResult(False,"non-positive simulated pnl")
    if max_drawdown_usd>c.max_drawdown_usd: return GateResult(False,"drawdown exceeds bound")
    if fill_rate<c.min_fill_rate: return GateResult(False,"fill rate too low")
    return GateResult(True,"qualified")

def can_trade_live(qualified:bool,armed:bool)->bool:
    return bool(qualified and armed)
```

- [ ] **Step 4: Run** `uv run pytest tests/eval -v` → PASS; full suite; ruff/mypy.

- [ ] **Step 5: Commit** `git add kaiju/eval/ tests/eval/ && git commit -m "feat: eval metrics + promotion gate (v2: fill-rate, roundtrip pnl)"`

## Task 9: State extensions (positions / working orders / calibration)

**Files:** Modify `kaiju/state.py`; Test `tests/test_state_v2.py`.

- [ ] **Step 1: Failing test** `tests/test_state_v2.py`:
```python
from kaiju.state import State

def test_position_and_working_order_and_calibration(tmp_path):
    db=State(str(tmp_path/"s.sqlite")); db.init_schema()
    db.upsert_position("M","yes",3,45,"2026-05-17")
    db.upsert_position("M","yes",5,46,"2026-05-17")     # idempotent upsert (latest wins)
    p=db.get_position("M"); assert p["count"]==5 and p["avg_entry_cents"]==46
    db.record_working_order("c1","M","yes",55,1,"shadow-paper")
    db.record_working_order("c1","M","yes",55,1,"shadow-paper")
    assert len(db.list_working_orders())==1               # idempotent client_id
    db.set_calibration("KNYC",bias=-1.2,spread_scale=1.05,n=40)
    c=db.get_calibration("KNYC"); assert c["bias"]==-1.2 and c["n"]==40
```

- [ ] **Step 2: Run** `uv run pytest tests/test_state_v2.py -v` → FAIL.

- [ ] **Step 3: Implement.** Append to `SCHEMA` in `kaiju/state.py`:
```sql
CREATE TABLE IF NOT EXISTS positions(
  market TEXT PRIMARY KEY, side TEXT, count INT, avg_entry_cents INT,
  climate_date TEXT, updated_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS working_orders(
  client_id TEXT PRIMARY KEY, market TEXT, side TEXT, price INT, count INT,
  mode TEXT, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS calibration(
  station TEXT PRIMARY KEY, bias REAL, spread_scale REAL, n INT,
  updated_at TEXT DEFAULT (datetime('now')));
```
Add methods: `upsert_position(market,side,count,avg_entry_cents,climate_date)` (INSERT … ON CONFLICT(market) DO UPDATE SET … latest wins), `get_position(market)->dict|None`, `list_positions()->list[dict]`, `record_working_order(client_id,market,side,price,count,mode)` (INSERT OR IGNORE), `list_working_orders()->list[dict]`, `clear_working_order(client_id)`, `set_calibration(station,bias,spread_scale,n)` (upsert), `get_calibration(station)->dict|None`. Commit after each write (match existing style).

- [ ] **Step 4: Run** `uv run pytest tests/test_state_v2.py -v` → PASS; full suite; ruff/mypy.

- [ ] **Step 5: Commit** `git add kaiju/state.py tests/test_state_v2.py && git commit -m "feat: state v2 (positions, working orders, calibration)"`

## Task 10: IEM observation client (settlement max + intraday obs)

**Files:** Create `kaiju/data/obs.py`, `kaiju/data/__init__.py`; Test `tests/data/test_obs.py`.

- [ ] **Step 1: [SPIKE-STEP]** Confirm the IEM endpoint for **intraday observed temperatures** (METAR/ASOS) for Central Park and save a trimmed real response to `tests/fixtures/iem_knyc_asos.json`; append its endpoint+JSON-path+mock-regex to `docs/superpowers/notes/settlement-map.md` (the daily-max endpoint is already recorded there + fixture `iem_knyc_dailymax.json` exists). Use IEM ASOS JSON (e.g. `https://mesonet.agron.iastate.edu/api/1/...` ASOS service) for station `NYC` air temp `tmpf` by timestamp. Commit fixture+notes update separately:
`git add tests/fixtures/iem_knyc_asos.json docs/superpowers/notes/settlement-map.md && git commit -m "docs: recorded IEM intraday ASOS contract + fixture"`

- [ ] **Step 2: Failing test** `tests/data/test_obs.py` (offline, respx + fixtures):
```python
import json, respx, httpx
from kaiju.data.obs import IEMClient

def test_official_daily_max_parses_int():
    fx=json.load(open("tests/fixtures/iem_knyc_dailymax.json"))
    with respx.mock:
        respx.get(url__regex=r".*mesonet\.agron\.iastate\.edu.*").mock(
            return_value=httpx.Response(200,json=fx))
        v=IEMClient().official_daily_max("NYTNYC","NYCLIMATE","2026-05-14")
        assert isinstance(v,int) and v==66      # known value in fixture

def test_observed_max_so_far_returns_running_max_int():
    fx=json.load(open("tests/fixtures/iem_knyc_asos.json"))
    with respx.mock:
        respx.get(url__regex=r".*mesonet\.agron\.iastate\.edu.*").mock(
            return_value=httpx.Response(200,json=fx))
        m=IEMClient().observed_max_so_far("NYC","2026-05-14")
        assert isinstance(m,int)
```
(Set the asserted daily-max to the real `2026-05-14` value present in the committed fixture.)

- [ ] **Step 3: Run** `uv run pytest tests/data/test_obs.py -v` → FAIL.

- [ ] **Step 4: Implement** `kaiju/data/obs.py` with `IEMClient` using the EXACT endpoints/JSON paths recorded in `settlement-map.md`: `official_daily_max(station,network,date)->int` (parse `max_tmpf`, round to int, raise `LookupError` if null/`tmpf_est` true), `observed_max_so_far(station,date)->int` (max of `tmpf` rows ≤ now for that date). `httpx` with timeout+retry.

- [ ] **Step 5: Run** `uv run pytest tests/data/test_obs.py -v` → PASS; full suite; ruff/mypy.

- [ ] **Step 6: Commit** `git add kaiju/data/ tests/data/test_obs.py && git commit -m "feat: IEM obs client (settlement max + intraday running max)"`

## Task 11: Herbie forecast fetcher (NBM nbmqmd + GEFS)

**Files:** Create `kaiju/data/forecast.py`; Test `tests/data/test_forecast.py`.

- [ ] **Step 1: Failing test** `tests/data/test_forecast.py` (offline, committed fixtures from SPIKE Task 6):
```python
from kaiju.data.forecast import nbm_percentiles_from_fixture, gefs_members_from_fixture
def test_nbm_fixture_parses_monotone():
    pct=nbm_percentiles_from_fixture("tests/fixtures/nbm_knyc.json")
    ks=sorted(pct); assert pct[ks[0]] <= pct[ks[-1]] and all(0<=k<=100 for k in pct)
def test_gefs_fixture_member_list():
    m=gefs_members_from_fixture("tests/fixtures/gefs_knyc.json")
    assert len(m)>=20 and all(isinstance(x,float) for x in m)
```

- [ ] **Step 2: Run** `uv run pytest tests/data/test_forecast.py -v` → FAIL.

- [ ] **Step 3: Implement** `kaiju/data/forecast.py` per `docs/superpowers/notes/noaa-forecast-contract.md`: pure parsers `nbm_percentiles_from_fixture(path)->dict[float,float]`, `gefs_members_from_fixture(path)->list[float]` (consume the committed fixture shapes); live `fetch_nbm_percentiles(station_id,run_dt,climate_date)->dict[float,float]` using `model="nbmqmd"`, `product`/`fxx`/`search` strings recorded in the notes, scipy-cKDTree point pick (scikit-learn unavailable), K→°F; `fetch_gefs_members(...)->list[float]` (member loop c00,p01..p30; max over the recorded fxx window). Cache raw under `data/cache/` (gitignored).

- [ ] **Step 4: Run** `uv run pytest tests/data/test_forecast.py -v` → PASS; full suite; ruff/mypy.

- [ ] **Step 5: [manual smoke, not CI]** `uv run python -m kaiju.data.forecast --smoke NYC` prints a plausible percentile map.

- [ ] **Step 6: Commit** `git add kaiju/data/forecast.py tests/data/test_forecast.py && git commit -m "feat: Herbie NBM(nbmqmd)/GEFS fetch (offline-tested)"`

## Task 12: RSA-signed Kalshi REST client

**Files:** Create `kaiju/markets/kalshi_client.py`, `kaiju/markets/__init__.py`; Test `tests/markets/test_kalshi_client.py`.

- [ ] **Step 1: Failing test** `tests/markets/test_kalshi_client.py` (signing round-trip + mocked REST):
```python
import respx, httpx
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from kaiju.markets.kalshi_client import KalshiClient, sign_request, _verify_for_test

def _pem():
    k=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    return k,k.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,serialization.NoEncryption()).decode()

def test_signature_round_trip():
    k,pem=_pem()
    sig,ts=sign_request(pem,"GET","/trade-api/v2/markets",timestamp_ms=1700000000000)
    assert _verify_for_test(k.public_key(),sig,"1700000000000"+"GET"+"/trade-api/v2/markets")

def test_get_quote_parses_orderbook():
    _,pem=_pem()
    body={"orderbook":{"yes":[[40,100]],"no":[[58,100]]}}  # adjust to recorded shape
    with respx.mock:
        respx.get(url__regex=r".*/markets/.*/orderbook").mock(
            return_value=httpx.Response(200,json=body))
        c=KalshiClient(key_id="k",private_key_pem=pem,base_url="https://x")
        q=c.get_quote("M"); assert q.market_ticker=="M" and q.yes_ask is not None
```

- [ ] **Step 2: Run** `uv run pytest tests/markets/test_kalshi_client.py -v` → FAIL.

- [ ] **Step 3: Implement** `kaiju/markets/kalshi_client.py` per `docs/superpowers/notes/kalshi-api-contract.md`: `sign_request(private_key_pem,method,path,timestamp_ms)->(sig_b64,ts)` using RSA-PSS/SHA256/MGF1(SHA256)/salt=DIGEST_LENGTH, message `ts+METHOD+path` (path sans query), standard base64; `_verify_for_test` mirrors it. `KalshiClient` (headers `KALSHI-ACCESS-KEY/TIMESTAMP/SIGNATURE`): `list_events/list_markets/get_quote(MarketQuote)/get_balance/get_positions/create_order/cancel_order/get_fills`, `httpx` retry/backoff on 5xx. Construct from `Settings.kalshi_key_id` and `Settings.kalshi_private_key.get_secret_value()` (SecretStr contract).

- [ ] **Step 4: Run** `uv run pytest tests/markets/test_kalshi_client.py -v` → PASS; full suite; ruff/mypy.

- [ ] **Step 5: [manual demo smoke]** one-off script vs demo base URL: list markets, one orderbook, balance → 200s. No keys/output committed.

- [ ] **Step 6: Commit** `git add kaiju/markets/ tests/markets/test_kalshi_client.py && git commit -m "feat: RSA-signed Kalshi REST client"`

## Task 13: Event/bucket parser + settlement mapping (`*.5`→int)

**Files:** Create `kaiju/markets/parser.py`; Test `tests/markets/test_parser.py`.

- [ ] **Step 1: Failing test** `tests/markets/test_parser.py`:
```python
from kaiju.markets.parser import parse_event_snapshot, resolve_settlement

def test_half_strikes_become_inclusive_integer_bounds_no_double_count():
    # Kalshi *.5 strikes; adjacent buckets must NOT both claim integer 70
    raw=[{"ticker":"B69.5","floor_strike":68.5,"cap_strike":69.5,
          "yes_bid":4,"yes_ask":7,"no_bid":93,"no_ask":96,"volume":10,"open_interest":300},
         {"ticker":"B70.5","floor_strike":69.5,"cap_strike":70.5,
          "yes_bid":40,"yes_ask":45,"no_bid":55,"no_ask":60,"volume":50,"open_interest":900}]
    snap=parse_event_snapshot("E","NYTNYC","2026-05-17",raw)
    b={x.market_ticker:x for x in snap.buckets}
    assert (b["B69.5"].lower_f,b["B69.5"].upper_f)==(69,69)
    assert (b["B70.5"].lower_f,b["B70.5"].upper_f)==(70,70)   # no shared integer
    assert snap.quotes["B70.5"].yes_ask==45

def test_resolve_settlement_knyc():
    s=resolve_settlement("KXHIGHNY")
    assert s["iem_station"]=="NYTNYC" and s["iem_network"]=="NYCLIMATE"
    assert s["tz"]=="America/New_York"
```

- [ ] **Step 2: Run** `uv run pytest tests/markets/test_parser.py -v` → FAIL.

- [ ] **Step 3: Implement** `kaiju/markets/parser.py`. `parse_event_snapshot(event_ticker,station_id,climate_date,raw_markets)->EventSnapshot`: map recorded Kalshi fields (`floor_strike`/`cap_strike` are the recorded names; quote `*_dollars`/cent fields per `kalshi-api-contract.md` — convert to integer cents for `MarketQuote`). **Strike conversion (enforce the recorded hazard):** a market with `floor_strike=f`, `cap_strike=c` covers the inclusive integer band `[ceil(f), floor(c)]` for interior buckets (e.g. 69.5/70.5 → [70,70]); open low (`floor_strike` None) → `lower_f=None, upper_f=floor(c)`; open high → `lower_f=ceil(f), upper_f=None`. Verify adjacent interior buckets never share an integer. `resolve_settlement(series_ticker)->dict` from `docs/superpowers/notes/settlement-map.md` (`KXHIGHNY`→{station_human:"Central Park", iem_station:"NYTNYC", iem_network:"NYCLIMATE", tz:"America/New_York"}); raise for unmapped/ambiguous series.

- [ ] **Step 4: Run** `uv run pytest tests/markets/test_parser.py -v` → PASS; full suite; ruff/mypy.

- [ ] **Step 5: Commit** `git add kaiju/markets/parser.py tests/markets/test_parser.py && git commit -m "feat: Kalshi event/bucket parser (*.5->inclusive int) + settlement map"`

## Task 14: Kalshi WebSocket client

**Files:** Create `kaiju/markets/ws_client.py`; Test `tests/markets/test_ws_client.py`; add `websockets` to `pyproject.toml`.

- [ ] **Step 1: [SPIKE-STEP]** Record the Kalshi WebSocket contract to `docs/superpowers/notes/kalshi-ws-contract.md`: WS URL (prod+demo), the auth handshake (same RSA signing as REST, per `kalshi-api-contract.md`), subscribe message format for `orderbook_delta`/`orderbook_snapshot` and `fill` channels, and the message JSON shapes. Source: Kalshi WS docs (WebFetch). If a field is unconfirmable, mark UNVERIFIED with how Task 17's demo smoke will confirm. Add `websockets>=12` to `pyproject.toml` deps; `uv sync`. Commit: `git add docs/superpowers/notes/kalshi-ws-contract.md pyproject.toml uv.lock && git commit -m "docs: recorded Kalshi WS contract; add websockets dep"`

- [ ] **Step 2: Failing test** `tests/markets/test_ws_client.py` (fake transport — no network):
```python
import asyncio, json
from kaiju.markets.ws_client import WsClient

class FakeWS:
    def __init__(self,msgs): self.msgs=list(msgs); self.sent=[]
    async def send(self,m): self.sent.append(json.loads(m))
    async def __aiter__(self):
        for m in self.msgs: yield json.dumps(m)
    async def close(self): pass

def test_dispatches_book_and_fill_events_and_reconciles_on_connect():
    events=[]
    fake=FakeWS([{"type":"orderbook_snapshot","market_ticker":"M","yes":[[40,100]],"no":[[58,50]]},
                 {"type":"fill","market_ticker":"M","price":40,"count":2,"side":"yes"}])
    c=WsClient(connect=lambda: fake, on_event=events.append,
               on_connect_reconcile=lambda: events.append({"type":"reconcile"}))
    asyncio.run(c.run_once())
    kinds=[e["type"] for e in events]
    assert kinds[0]=="reconcile" and "orderbook_snapshot" in kinds and "fill" in kinds
```

- [ ] **Step 3: Run** `uv run pytest tests/markets/test_ws_client.py -v` → FAIL.

- [ ] **Step 4: Implement** `kaiju/markets/ws_client.py` against the recorded WS contract. `WsClient(connect, on_event, on_connect_reconcile)` where `connect` is an injectable async-context factory (real default builds the signed `websockets` connection + subscribe msgs). `run_once()`: open → call `on_connect_reconcile()` → async-iterate messages → normalize → `on_event(dict)`. `run_forever()`: wrap `run_once` in reconnect loop with exponential backoff + heartbeat/idle timeout; on any disconnect, the next connect re-triggers reconcile. Keep network construction behind `connect` so tests inject `FakeWS`.

- [ ] **Step 5: Run** `uv run pytest tests/markets/test_ws_client.py -v` → PASS; full suite; ruff/mypy.

- [ ] **Step 6: [manual demo smoke]** connect to demo WS read-only, log a few book messages, confirm shapes vs recorded notes; update notes if reality differs.

- [ ] **Step 7: Commit** `git add kaiju/markets/ws_client.py tests/markets/test_ws_client.py && git commit -m "feat: Kalshi WebSocket client (reconnect + reconcile)"`

## Task 15: Position manager (modes, idempotent, reconcile)

**Files:** Create `kaiju/execution/position_manager.py`, `kaiju/execution/__init__.py`; Test `tests/execution/test_position_manager.py`.

- [ ] **Step 1: Failing test** `tests/execution/test_position_manager.py`:
```python
from kaiju.types import TradeIntent
from kaiju.state import State
from kaiju.execution.position_manager import PositionManager

class FakeK:
    def __init__(self): self.sent=[]
    def create_order(self,**k): self.sent.append(k); return {"order_id":"x"}
    def cancel_order(self,**k): pass
    def get_positions(self): return []

def test_shadow_paper_records_not_sends(tmp_path):
    st=State(str(tmp_path/"s.sqlite")); st.init_schema(); k=FakeK()
    pm=PositionManager(mode="shadow-paper",kalshi=k,state=st)
    pm.execute_entries([TradeIntent("M","yes",55,2,0.7,0.15)],"2026-05-17")
    assert k.sent==[] and len(st.list_working_orders())==1

def test_live_sends_once_idempotent(tmp_path):
    st=State(str(tmp_path/"s.sqlite")); st.init_schema(); k=FakeK()
    pm=PositionManager(mode="live",kalshi=k,state=st)
    i=[TradeIntent("M","yes",55,2,0.7,0.15)]
    pm.execute_entries(i,"2026-05-17"); pm.execute_entries(i,"2026-05-17")
    assert len(k.sent)==1
```

- [ ] **Step 2: Run** `uv run pytest tests/execution/test_position_manager.py -v` → FAIL.

- [ ] **Step 3: Implement** `kaiju/execution/position_manager.py`: `PositionManager(mode,kalshi,state)` with `execute_entries(intents,climate_date)`, `execute_exits(decisions,climate_date)`, `reconcile()`. Deterministic client id = `sha1(day|market|side|price|count)[:16]`; skip if `state.list_working_orders()`/orders already has it (idempotent). `live` → `kalshi.create_order(client_order_id=…,…)`; `shadow-paper`/`backtest` → record only. `reconcile()` pulls `kalshi.get_positions()` and rewrites `state` positions as source of truth. Exits place opposite-side limits / cancels via `kalshi.cancel_order`.

- [ ] **Step 4: Run** `uv run pytest tests/execution/test_position_manager.py -v` → PASS; full suite; ruff/mypy.

- [ ] **Step 5: Commit** `git add kaiju/execution/ tests/execution/test_position_manager.py && git commit -m "feat: position manager (modes, idempotent, reconcile)"`

## Task 16: Intraday shadow-paper fill simulator

**Files:** Create `kaiju/execution/paper_sim.py`; Test `tests/execution/test_paper_sim.py`.

- [ ] **Step 1: Failing test** `tests/execution/test_paper_sim.py`:
```python
from kaiju.execution.paper_sim import PaperBook

def test_marketable_limit_fills_against_book():
    pb=PaperBook()
    pb.update("M",yes=[[55,100]],no=[[45,100]])
    # buy yes limit 55 -> fills at 55 up to resting size
    f=pb.try_fill("M","yes",limit_price=55,count=2)
    assert f["filled"]==2 and f["price"]==55

def test_unmarketable_limit_no_fill():
    pb=PaperBook(); pb.update("M",yes=[[60,100]],no=[[40,100]])
    f=pb.try_fill("M","yes",limit_price=55,count=2)
    assert f["filled"]==0
```

- [ ] **Step 2: Run** `uv run pytest tests/execution/test_paper_sim.py -v` → FAIL.

- [ ] **Step 3: Implement** `kaiju/execution/paper_sim.py`: `PaperBook` holding latest book per market (`update(market,yes,no)` from WS snapshots/deltas), `try_fill(market,side,limit_price,count)->{"filled":int,"price":int}` filling marketable limits against the opposite resting level up to its size (partial fills supported), no fill if unmarketable. Used by `PositionManager` in `shadow-paper` mode so the same code path runs.

- [ ] **Step 4: Run** `uv run pytest tests/execution/test_paper_sim.py -v` → PASS; full suite; ruff/mypy.

- [ ] **Step 5: Commit** `git add kaiju/execution/paper_sim.py tests/execution/test_paper_sim.py && git commit -m "feat: intraday shadow-paper fill simulator"`

## Task 17: Intraday runner / event loop

**Files:** Create `kaiju/runner.py`; Test `tests/test_runner.py`.

- [ ] **Step 1: Failing test** `tests/test_runner.py` (deterministic; all IO injected):
```python
from kaiju.runner import run_intraday_once

class Deps:
    def __init__(self): self.placed=[]
    def fair_prices(self): return {"MID":70}
    def quotes(self): 
        from kaiju.types import MarketQuote
        return {"MID":MarketQuote("MID",50,55,45,50,500,1000)}
    def positions(self): return {}
    def place(self,intents,cd): self.placed+=intents
    def exits(self): return []

def test_one_tick_enters_mispriced_market(tmp_path):
    d=Deps()
    res=run_intraday_once(station="NYC",climate_date="2026-05-17",
        db_path=str(tmp_path/"s.sqlite"),mode="shadow-paper",deps=d,
        net_edge_threshold=0.08,min_open_interest=100)
    assert len(d.placed)>=1 and res["station"]=="NYC"
```

- [ ] **Step 2: Run** `uv run pytest tests/test_runner.py -v` → FAIL.

- [ ] **Step 3: Implement** `kaiju/runner.py`. `run_intraday_once(station,climate_date,db_path,mode,deps,net_edge_threshold,min_open_interest)`: one evaluation tick — `select_gap_trades(deps.fair_prices(),deps.quotes(),deps.positions(),…)` → per-intent `RiskGate` → `deps.place(...)`; also apply `deps.exits()` exit decisions; return a report dict. `run_intraday(...)`: production wiring — build real `Deps` (forecast+nowcast+fair value recompute on a timer, `WsClient` feeding `quotes`/positions via `PaperBook`/`PositionManager`, safety timer), event loop calling `run_intraday_once` on book/fill/timer events, clean shutdown. `if __name__=="__main__"` CLI: subcommands `run|settle|retrain` with `--station/--date/--mode`. Real deps only in `__main__`/`run_intraday`; tests inject `Deps`.

- [ ] **Step 4: Run** `uv run pytest tests/test_runner.py -v` → PASS; full suite; ruff/mypy.

- [ ] **Step 5: Commit** `git add kaiju/runner.py tests/test_runner.py && git commit -m "feat: intraday runner event loop (tick + production wiring)"`

## Task 18: Settlement + PnL + gate update

**Files:** Modify `kaiju/runner.py` (add `settle_day`); Test `tests/test_settlement.py`.

- [ ] **Step 1: Failing test** `tests/test_settlement.py`:
```python
from kaiju.runner import settle_day
class Deps:
    def official_daily_max(self): return 66
def test_settles_positions_and_updates_gate(tmp_path):
    from kaiju.state import State
    st=State(str(tmp_path/"s.sqlite")); st.init_schema()
    st.record_prediction("NYC","2026-05-17",64,[0.2,0.6,0.2])
    st.upsert_position("MID","yes",2,40,"2026-05-17")
    r=settle_day(station="NYC",climate_date="2026-05-17",
                 db_path=str(tmp_path/"s.sqlite"),deps=Deps())
    assert r["realized_max"]==66 and st.get_gate_status() is not None
```

- [ ] **Step 2: Run** `uv run pytest tests/test_settlement.py -v` → FAIL.

- [ ] **Step 3: Implement** `settle_day(station,climate_date,db_path,deps)` in `kaiju/runner.py`: official daily max via `deps.official_daily_max()` (real = `IEMClient.official_daily_max`), score held positions (held-to-settlement payoff) + recorded round-trip pnl, write `pnl`, recompute Brier/CRPS/PIT + `roundtrip_pnl_stats` over the trailing window via `kaiju.eval.metrics`, `evaluate_promotion` (`kaiju.eval.gate`), `state.set_gate_status(...)`. CLI subcommand wired in Task 17.

- [ ] **Step 4: Run** `uv run pytest tests/test_settlement.py -v` → PASS; full suite; ruff/mypy.

- [ ] **Step 5: Commit** `git add kaiju/runner.py tests/test_settlement.py && git commit -m "feat: settlement scoring + gate update"`

## Task 19: Calibration retrain job

**Files:** Modify `kaiju/runner.py` (add `retrain_calibration`); Test `tests/test_retrain.py`.

- [ ] **Step 1: Failing test** `tests/test_retrain.py`:
```python
from kaiju.runner import retrain_calibration
def test_retrain_persists_params(tmp_path):
    from kaiju.state import State
    st=State(str(tmp_path/"s.sqlite")); st.init_schema()
    for i,(fc,ob) in enumerate([(60,57),(65,62),(70,67),(55,52)]):
        st.record_prediction("NYC",f"2026-04-0{i+1}",fc,[1.0])
    cal=retrain_calibration(station="NYC",db_path=str(tmp_path/"s.sqlite"),
        realized={f"2026-04-0{i+1}":ob for i,(_,ob) in enumerate([(0,57),(0,62),(0,67),(0,52)])})
    assert cal.n_samples==4 and cal.bias<0
    assert st.get_calibration("NYC")["n"]==4
```

- [ ] **Step 2: Run** `uv run pytest tests/test_retrain.py -v` → FAIL.

- [ ] **Step 3: Implement** `retrain_calibration(station,db_path,realized)` in `kaiju/runner.py`: read stored prediction medians + realized maxes, call `kaiju.model.calibration.fit_calibration(...,min_samples=Settings().paper_proof_days)`, persist via `State.set_calibration`. `run_intraday` loads these (identity default) before nowcast.

- [ ] **Step 4: Run** `uv run pytest tests/test_retrain.py -v` → PASS; full suite; ruff/mypy.

- [ ] **Step 5: Commit** `git add kaiju/runner.py tests/test_retrain.py && git commit -m "feat: calibration retrain job"`

## Task 20: Deploy artifacts

**Files:** Create `Dockerfile`, `deploy/run_daily.sh`, `deploy/com.kaiju.daily.plist`; Test `tests/test_deploy_smoke.py`.

- [ ] **Step 1: Failing test** `tests/test_deploy_smoke.py`:
```python
import subprocess,sys
def test_cli_help():
    o=subprocess.run([sys.executable,"-m","kaiju.runner","--help"],capture_output=True,text=True)
    assert o.returncode==0 and "station" in o.stdout.lower()
```

- [ ] **Step 2: Run** `uv run pytest tests/test_deploy_smoke.py -v` → FAIL (if `--help` not wired) else proceed to artifacts.

- [ ] **Step 3: Create artifacts.** `Dockerfile` (python:3.12-slim + `libeccodes0`, `uv sync --no-dev`, `ENTRYPOINT ["uv","run","python","-m","kaiju.runner"]`). `deploy/run_daily.sh`: `settle` yesterday → `retrain` → `run` today's trading window (long-running until time-stop). `deploy/com.kaiju.daily.plist`: launchd job invoking the wrapper once daily before the NBM run window (UTC hour from `noaa-forecast-contract.md`), with stdout/stderr to a log path.

- [ ] **Step 4: Run** `chmod +x deploy/run_daily.sh && uv run pytest tests/test_deploy_smoke.py -v` → PASS.

- [ ] **Step 5: Commit** `git add Dockerfile deploy/ tests/test_deploy_smoke.py && git commit -m "feat: Docker + launchd intraday-run wrapper"`

## Task 21: README / operator runbook

**Files:** Create `README.md`.

- [ ] **Step 1: Write README** covering: setup (`uv sync`, `.env` from `.env.example`, **rotate the leaked RSA key**); the three run modes; the v2 strategy in plain terms (fair value, the three exits, hold-to-settlement fallback); the paper-proof gate + metrics; the **one-time arm procedure** (`KAIJU_LIVE_ARM_TOKEN`, requires gate `qualified`); the kill switch (create the kill-switch file); reading the daily report; Mac→same-region-EC2 migration (same Docker image, persistent `KAIJU_DB_PATH`).

- [ ] **Step 2: Commit** `git add README.md && git commit -m "docs: v2 operator runbook"`

---

## Self-Review (completed by plan author)

**1. Spec coverage:** v2 §3 nowcast→T3; §3 forecast PMF reused (built) + fair value T4; §4 entry→T5, exits→T6; §5 WS loop→T14+T17, timers/reconcile→T17, lifecycle→T17/T18/T19; §6 position mgr→T15, risk gate→T7; §7 modes/paper-sim→T16, gate metrics→T8, arm→T8; §2 data contracts→T10/T11/T12/T13 (recorded notes); §8 module map→all; §9 Task-11 fixes→T1, types→T2, state ext→T9; deploy→T20, runbook→T21. All spec sections mapped.

**2. Placeholder scan:** External specifics are bound by recorded notes / explicit [SPIKE-STEP] tasks (T10 step1, T14 step1) before dependent code; fixture-asserted values say "set to the real value in the committed fixture" — these are verification anchors, not unfilled placeholders. No "TODO/handle edge cases" instructions remain.

**3. Type consistency:** `Position`/`ExitDecision`/`ExitAction` defined T2, used T5/T6/T15. `fair_prices`→`dict[str,int]` cents consumed by T5/T6/T17. `select_gap_trades`/`decide_exit`/`RiskGate.check`/`PositionManager.execute_*`/`run_intraday_once`/`settle_day`/`retrain_calibration` signatures consistent across references. Reused built fns (`bucket_probabilities`,`trade_fee_cents`,`size_event`,`fit_calibration`) keep their existing signatures. SecretStr `.get_secret_value()` enforced in T12.

## Risks carried from spec (not re-litigated)

- WS live-failure surface → reconnect/heartbeat/REST-reconcile (T14/T17) + paper-proof gate is the safeguard.
- Convergence-not-guaranteed / market-converges-to-truth → nowcast (T3) + thesis-invalidation exit (T6) + bounded hold-to-settlement.
- Kalshi fee coefficient + WS schema UNVERIFIED → pinned + [SPIKE-STEP]/demo-smoke confirmation (T12/T14).
- `*.5` strike double-count → enforced + tested in T13.
