# Python Language Pack — kaiju

Loaded by `kaiju-engineer` and `kaiju-reviewer`. Encodes Python patterns that
ruff/mypy don't already catch. If ruff/mypy is tightened later to cover one of
these, remove the pattern here (kit principle 4: patterns in this file should be
the ones the linter can't catch).

## Format

Each pattern entry:

- **ENFORCE:** the one-line rule
- **WHY:** the failure mode it prevents (postmortem-grounded where possible)
- **DETECT:** how a reviewer spots a violation (regex, structural pattern)
- **FIX:** the correct form, with a minimal bad/good example

---

## Pattern 1: Frozen dataclasses for value types

**ENFORCE:** Types that cross module boundaries are `@dataclass(frozen=True)`.

**WHY:** Kaiju runs an intraday loop where the same object can be observed by
multiple components in sequence; mutation in one shifts behavior elsewhere
unpredictably.

**DETECT:** `@dataclass` without `frozen=True` in `kaiju/types.py`, or as a
return type from `data/`, `model/`, `markets/`.

**FIX:**

```python
# BAD
@dataclass
class TempPMF:
    probs: tuple[float, ...]

# OK
@dataclass(frozen=True)
class TempPMF:
    probs: tuple[float, ...]
```

If mutation is genuinely required, refactor to return a new instance with
`dataclasses.replace`.

---

## Pattern 2: Integer cents, never float, for prices and fees

**ENFORCE:** Kalshi prices/fees are `int` cents (0–99 or fee bps). Only PMF
probabilities are `float`.

**WHY:** Float equality against fee thresholds drifts
(`0.30 + 0.05 != 0.35` in IEEE 754); a fees regression would be silent.

**DETECT:** `float` in a function signature in `kaiju/strategy/fees.py`,
`kaiju/strategy/sizing.py`, or any `==`/`!=`/`<=`/`>=` comparison involving a
price/fee.

**FIX:**

```python
# BAD
def fee(notional: float) -> float:
    return notional * 0.07

# OK
def fee(notional_cents: int) -> int:
    # round-half-even or floor — decide explicitly per call site
    return (notional_cents * 7 + 50) // 100
```

---

## Pattern 3: No silent exception swallowing in `runner.py`, `markets/`, `execution/`

**ENFORCE:** Every `except` in these modules either re-raises, logs at ERROR
with `exc_info=True`, or has a *named* recovery action documented in a comment.

**WHY:** In an autonomous loop, silently eaten exceptions hide market
disconnections, broker rejections, settlement errors. The loop keeps
"succeeding" with stale state.

**DETECT:** `except Exception` or `except BaseException` followed by anything
other than `raise`, `log.exception(...)`, `log.error(..., exc_info=True)`, or a
documented recovery (`# recovery: <reason>`).

**FIX:**

```python
# BAD
try:
    ws.send(msg)
except Exception:
    pass  # silently dropped — bug hides forever

# OK (re-raise)
try:
    ws.send(msg)
except Exception:
    log.error("ws.send failed", exc_info=True)
    raise

# OK (named recovery)
try:
    ws.send(msg)
except websockets.ConnectionClosed:
    # recovery: reconnect loop will re-establish; queued msg is lost by design
    log.warning("ws closed during send; queued msg dropped")
```

---

## Pattern 4: Pytest fixtures + `tmp_path`, no hardcoded `/tmp/...`

**ENFORCE:** Tests get filesystem paths from `tmp_path` / `tmp_path_factory`.

**WHY:** Hardcoded `/tmp/...` breaks CI parallelism and leaks state between
runs — a flake the loop can't diagnose.

**DETECT:** Literal `"/tmp/"` or `tempfile.mkdtemp(` in `tests/`.

**FIX:**

```python
# BAD
def test_state():
    db = "/tmp/test.sqlite"
    ...

# OK
def test_state(tmp_path):
    db = tmp_path / "test.sqlite"
    ...
```

---

## Pattern 5: SEAM functions are pure

**ENFORCE:** The five SEAMs — `model/distribution.pmf_from_nbm_percentiles`,
`model/distribution.blend_pmfs`, `model/calibration.fit_calibration`,
`model/calibration.apply_calibration`, `model/nowcast.nowcast_pmf`,
`strategy/edge.select_gap_trades`, `strategy/exit_policy.decide_exit` — take
all inputs as parameters. No `time.time()`, `datetime.now()`, network I/O, DB
reads, or unparametrized module-level globals.

**WHY:** `eval/gate` scores competing SEAM implementations on replay.
Non-determinism breaks the ranking and the primary safety mechanism for
experimentation.

**DETECT:** `time.`, `datetime.now`, `requests.`, `httpx.`, `sqlite3.`, or
unparametrized module-level state inside a SEAM body.

**FIX:**

```python
# BAD
def decide_exit(position):
    if datetime.now() > position.entry_time + timedelta(hours=4):
        return ExitDecision.TIME_STOP

# OK
def decide_exit(position, now: datetime):
    if now > position.entry_time + timedelta(hours=4):
        return ExitDecision.TIME_STOP
```

Tests provide deterministic stubs; production injects the real clock/client.

---

## Pattern 6: DB access only through `kaiju.state`

**ENFORCE:** No `sqlite3.connect`, no raw SQL outside `kaiju/state.py`.

**WHY:** Migration and schema discipline live in one place; ad-hoc queries in
`runner.py` or `execution/` drift from the schema model.

**DETECT:** `import sqlite3`, `sqlite3.connect(`, or raw `CREATE TABLE` /
`INSERT INTO` / `SELECT ` strings outside `kaiju/state.py`.

**FIX:** Add a method to `kaiju.state` and call it. Schema changes go through
a migration in the same file.

---

## Pattern 7: Structured logger via `kaiju.logging`

**ENFORCE:** Import the configured logger from `kaiju.logging`. Never call
`logging.getLogger` directly.

**WHY:** Ad-hoc loggers bypass the configured structured fields and JSON
formatting; log analysis stops working.

**DETECT:** `logging.getLogger(` outside `kaiju/logging.py`. (`import logging`
for type hints is fine; only the `getLogger` call is the violation.)

**FIX:**

```python
# BAD
import logging
log = logging.getLogger(__name__)

# OK
from kaiju.logging import get_logger
log = get_logger(__name__)
```

`configure_logging()` is already called once at process startup in `runner.py`.

---

## How to add a new pattern

1. Format: ENFORCE / WHY / DETECT / FIX + minimal bad/good example.
2. WHY must reference a real failure mode if possible (postmortem-named).
3. If ruff/mypy already catches it, prefer the linter.
4. After adding, sweep `kaiju-engineer.md` / `kaiju-reviewer.md` — if they encode a redundant local rule, delete the local one.
