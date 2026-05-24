# Agentic Kit PR 1 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the read-only foundation of the agentic-feature-kit setup: a PreToolUse hook that blocks edits to rail files, a Python language pack, and three read-only subagents (reviewer + two researchers). All on branch `agentic-kit/spec`, which is already cut from `main` and contains the design spec.

**Architecture:** Hook is a small bash script invoked via `.claude/settings.json` PreToolUse matcher, exits non-zero with a clear message on rail-path matches. The language pack is a markdown reference file loaded by future engineer/reviewer agents. The three subagents live in `.claude/agents/` and are invoked from the main session via the Task tool — they have no `Edit`/`Write` tools so they can't damage the repo if mis-tuned.

**Tech Stack:** Bash, `jq`, pytest, Claude Code subagent files (`.claude/agents/*.md`), Claude Code settings hooks (`.claude/settings.json`).

**Spec reference:** `docs/superpowers/specs/2026-05-22-agentic-feature-kit-setup-design.md`

---

## Task 1: Failing test for the danger-zone hook (test-first)

**Files:**
- Create: `tests/test_danger_zone_hook.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_danger_zone_hook.py
"""Tests for scripts/block-danger-zones.sh.

The script reads a Claude Code PreToolUse hook payload on stdin
(a JSON object with `tool_input.file_path`). It exits 0 if the path
is safe, exits 2 with a message on stderr if the path is a rail file.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "block-danger-zones.sh"


def _invoke(file_path: str) -> subprocess.CompletedProcess[str]:
    payload = json.dumps(
        {
            "tool_name": "Edit",
            "tool_input": {"file_path": file_path},
        }
    )
    return subprocess.run(
        ["bash", str(SCRIPT)],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )


def test_hook_blocks_risk_dir() -> None:
    result = _invoke("kaiju/risk/limits.py")
    assert result.returncode == 2, result.stderr
    assert "rail file" in result.stderr.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_danger_zone_hook.py::test_hook_blocks_risk_dir -v`

Expected: FAIL with the script not existing (FileNotFoundError or non-zero from bash that the test doesn't expect).

- [ ] **Step 3: Commit the failing test**

```bash
git add tests/test_danger_zone_hook.py
git commit -m "test: failing test for danger-zone hook (script not yet implemented)"
```

---

## Task 2: Minimal hook script — block one rail directory

**Files:**
- Create: `scripts/block-danger-zones.sh`

- [ ] **Step 1: Create the minimal script**

```bash
#!/usr/bin/env bash
# Block Edit/Write/NotebookEdit on rail files. Reason: AGENTS.md danger zones
# must be human-edited only; runtime rail edits can corrupt the safety substrate.
# Fires in ALL Claude Code sessions on this repo (including the main session).
set -euo pipefail

input="$(cat)"
path="$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.path // ""')"
[ -z "$path" ] && exit 0   # not a path-bearing tool call, allow

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
rel="${path#$repo_root/}"

block() {
  printf 'BLOCKED: %s is a rail file (AGENTS.md danger zone).\nReason: %s\nResolution: Stop & Escalate to a human.\n' "$1" "$2" >&2
  exit 2
}

case "$rel" in
  kaiju/risk/*) block "$rel" "real-money risk gate; must stay fail-closed" ;;
esac

exit 0
```

- [ ] **Step 2: Make the script executable**

Run: `chmod +x scripts/block-danger-zones.sh`

- [ ] **Step 3: Run the test from Task 1**

Run: `uv run pytest tests/test_danger_zone_hook.py::test_hook_blocks_risk_dir -v`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add scripts/block-danger-zones.sh
git commit -m "feat(hook): minimal danger-zone hook — blocks kaiju/risk/"
```

---

## Task 3: Extend hook + tests to cover all rail files

**Files:**
- Modify: `tests/test_danger_zone_hook.py`
- Modify: `scripts/block-danger-zones.sh`

- [ ] **Step 1: Add failing tests for the other rail files**

Append to `tests/test_danger_zone_hook.py`:

```python
import pytest


@pytest.mark.parametrize(
    "rail_path",
    [
        "kaiju/eval/gate.py",
        "kaiju/config.py",
        "kaiju/markets/parser.py",
        "docs/INVARIANTS.md",
        "docs/agents/LOOP.md",
        "AGENTS.md",
        "tests/test_scope_lock.py",
    ],
)
def test_hook_blocks_rail_file(rail_path: str) -> None:
    result = _invoke(rail_path)
    assert result.returncode == 2, result.stderr
    assert "rail file" in result.stderr.lower()


def test_hook_allows_non_rail_file() -> None:
    result = _invoke("kaiju/types.py")
    assert result.returncode == 0, result.stderr


def test_hook_allows_empty_path() -> None:
    """A tool call without a file path (e.g., Bash) is allowed."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_hook_blocks_absolute_path_to_rail() -> None:
    """Edit calls use absolute paths; hook must canonicalize and still block."""
    repo_root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    result = _invoke(f"{repo_root}/kaiju/risk/limits.py")
    assert result.returncode == 2, result.stderr
```

- [ ] **Step 2: Run the new tests, confirm they fail**

Run: `uv run pytest tests/test_danger_zone_hook.py -v`

Expected: the new parametrized tests FAIL (only `kaiju/risk/*` is in the script so far); `test_hook_allows_non_rail_file` and `test_hook_allows_empty_path` already PASS; `test_hook_blocks_absolute_path_to_rail` PASSES because the existing canonicalization already strips the repo root.

- [ ] **Step 3: Expand the hook script**

Replace the `case` block in `scripts/block-danger-zones.sh` with:

```bash
case "$rel" in
  kaiju/risk/*)              block "$rel" "real-money risk gate; must stay fail-closed" ;;
  kaiju/eval/gate.py)        block "$rel" "live-trading promotion gate" ;;
  kaiju/config.py)           block "$rel" "live-path guard + secrets handling" ;;
  kaiju/markets/parser.py)   block "$rel" "settlement map + band boundary rules" ;;
  docs/INVARIANTS.md)        block "$rel" "executable rail spec — only humans weaken invariants" ;;
  docs/agents/LOOP.md)       block "$rel" "loop contract — only humans alter the iteration model" ;;
  AGENTS.md)                 block "$rel" "prime directives — only humans alter rails" ;;
  tests/test_scope_lock.py)  block "$rel" "scope-lock test enforces single-market rule" ;;
esac
```

- [ ] **Step 4: Run all hook tests, confirm green**

Run: `uv run pytest tests/test_danger_zone_hook.py -v`

Expected: all 11 cases PASS (7 parametrized rail-file cases + 1 risk + non-rail + empty-path + absolute-path).

- [ ] **Step 5: Commit**

```bash
git add scripts/block-danger-zones.sh tests/test_danger_zone_hook.py
git commit -m "feat(hook): cover all rail files from AGENTS.md danger zones"
```

---

## Task 4: Wire hook into `.claude/settings.json`

**Files:**
- Create: `.claude/settings.json`

- [ ] **Step 1: Confirm `.claude/settings.local.json` exists and is gitignored**

Run: `cat .gitignore | grep -E "(claude|settings)" || echo "no claude entry"`

Expected: an entry like `.claude/settings.local.json` is gitignored. If missing, add it:

```bash
printf '\n.claude/settings.local.json\n' >> .gitignore
git add .gitignore
```

- [ ] **Step 2: Create the committed settings file**

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write|NotebookEdit",
        "hooks": [
          { "type": "command", "command": "bash scripts/block-danger-zones.sh" }
        ]
      }
    ]
  }
}
```

Save to `.claude/settings.json`.

- [ ] **Step 3: Validate the hook fires in a real Claude Code session**

Manual check (the engineer running this plan does this):
1. Restart Claude Code so the new `settings.json` is picked up
2. Ask Claude to `Edit kaiju/risk/limits.py` (any trivial edit)
3. Confirm the tool call is blocked with the message starting `BLOCKED: kaiju/risk/limits.py is a rail file ...`
4. Ask Claude to `Edit kaiju/types.py` instead (any trivial reversible edit, then revert)
5. Confirm the edit goes through normally

If the hook doesn't fire, debug `.claude/settings.json` syntax (Claude Code logs the hook load error on startup).

- [ ] **Step 4: Commit**

```bash
git add .claude/settings.json .gitignore
git commit -m "feat(hook): wire danger-zone hook via PreToolUse in .claude/settings.json"
```

---

## Task 5: Python language pack

**Files:**
- Create: `docs/agents/python-language-pack.md`

- [ ] **Step 1: Create the pack with the 7 seeded patterns**

Save the full content of the spec's "Python Language Pack" section (patterns 1–7 plus the header and footer) to `docs/agents/python-language-pack.md`. The exact text:

```markdown
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

\`\`\`python
# BAD
@dataclass
class TempPMF:
    probs: tuple[float, ...]

# OK
@dataclass(frozen=True)
class TempPMF:
    probs: tuple[float, ...]
\`\`\`

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

\`\`\`python
# BAD
def fee(notional: float) -> float:
    return notional * 0.07

# OK
def fee(notional_cents: int) -> int:
    # round-half-even or floor — decide explicitly per call site
    return (notional_cents * 7 + 50) // 100
\`\`\`

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

\`\`\`python
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
\`\`\`

---

## Pattern 4: Pytest fixtures + `tmp_path`, no hardcoded `/tmp/...`

**ENFORCE:** Tests get filesystem paths from `tmp_path` / `tmp_path_factory`.

**WHY:** Hardcoded `/tmp/...` breaks CI parallelism and leaks state between
runs — a flake the loop can't diagnose.

**DETECT:** Literal `"/tmp/"` or `tempfile.mkdtemp(` in `tests/`.

**FIX:**

\`\`\`python
# BAD
def test_state():
    db = "/tmp/test.sqlite"
    ...

# OK
def test_state(tmp_path):
    db = tmp_path / "test.sqlite"
    ...
\`\`\`

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

\`\`\`python
# BAD
def decide_exit(position):
    if datetime.now() > position.entry_time + timedelta(hours=4):
        return ExitDecision.TIME_STOP

# OK
def decide_exit(position, now: datetime):
    if now > position.entry_time + timedelta(hours=4):
        return ExitDecision.TIME_STOP
\`\`\`

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

\`\`\`python
# BAD
import logging
log = logging.getLogger(__name__)

# OK
from kaiju.logging import get_logger
log = get_logger(__name__)
\`\`\`

`configure_logging()` is already called once at process startup in `runner.py`.

---

## How to add a new pattern

1. Format: ENFORCE / WHY / DETECT / FIX + minimal bad/good example.
2. WHY must reference a real failure mode if possible (postmortem-named).
3. If ruff/mypy already catches it, prefer the linter.
4. After adding, sweep `kaiju-engineer.md` / `kaiju-reviewer.md` — if they encode a redundant local rule, delete the local one.
```

Note: when actually writing the file, the engineer must escape the inner triple-backticks in code blocks — the markdown above uses `\`\`\`` placeholders that should be real triple-backticks in the saved file.

- [ ] **Step 2: Verify `make check` still green (the pack is markdown, but a typo somewhere else might be lurking)**

Run: `make check`

Expected: green.

- [ ] **Step 3: Commit**

```bash
git add docs/agents/python-language-pack.md
git commit -m "docs: python language pack — 7 patterns ruff/mypy don't catch"
```

---

## Task 6: kaiju-reviewer agent file

**Files:**
- Create: `.claude/agents/kaiju-reviewer.md`

- [ ] **Step 1: Create the reviewer agent file**

Use the kit's `agents/reviewer.template.md` as the structural skeleton, fill in the kaiju specifics. Required content:

- **Frontmatter:** `name: kaiju-reviewer`, `description: Reviews kaiju code changes against the python language pack and rail invariants. Catches behavioral bugs via forced B1–B5 enumeration. No Edit/Write — read-only.`, `model: opus`, `tools: [Read, Grep, Glob, Bash]`, `color: red`.
- **BLOCKING doc-load gate** with required reads:
  1. `docs/INVARIANTS.md`
  2. `docs/agents/python-language-pack.md`
  3. `AGENTS.md` (danger-zone list only — reviewer should not load business context)
- **Proof-of-reading line:** `context loaded: docs/INVARIANTS.md, docs/agents/python-language-pack.md, AGENTS.md`
- **Mandatory review process** — Step 1 (list files via `git diff main...HEAD --name-only -- '*.py' '*.md' '*.sh' '*.json'`), Step 2 (read + per-file review), Step 3 (per-hunk B1–B5 with the kit's full B1–B5 prose), Step 4 (pattern checklist from the Python pack).
- **Severity levels:** CRITICAL / MAJOR / MINOR per the kit template.
- **Output format:** Files Reviewed (numbered) → Behavioral Findings → Pattern Findings → Verdict (APPROVED | CHANGES_REQUESTED). One CRITICAL finding blocks APPROVED.
- **Falsification prior** section (kit's verbatim).
- **What reviewers do NOT do** section (no Edit/Write enforced by tools, no re-design, no skipping behavioral review).

Length target: ~250–350 lines including B1–B5 prose.

- [ ] **Step 2: Validate by spawning the reviewer against the current branch**

From the main Claude Code session, run:

```
Spawn the kaiju-reviewer subagent and review branch agentic-kit/spec against main.
```

Expected output structure: `context loaded: ...` line, then "Files Reviewed" numbered list (should be 2: the spec doc and the python pack are the diff so far; tests + scripts + settings.json may also be present depending on commit order), then "Behavioral Findings" (mostly N/A — these are docs), then "Pattern Findings" (markdown can't violate Python patterns, so likely none), then "Verdict: APPROVED".

If the output structure is missing or the agent refuses to load docs, debug the agent file syntax.

- [ ] **Step 3: Commit**

```bash
git add .claude/agents/kaiju-reviewer.md
git commit -m "feat(agents): kaiju-reviewer — read-only diff auditor with B1–B5 behavioral review"
```

---

## Task 7: kaiju-ground-truth-researcher agent file

**Files:**
- Create: `.claude/agents/kaiju-ground-truth-researcher.md`

- [ ] **Step 1: Create the agent file**

Use the kit's `agents/researcher.template.md` as the skeleton. Required content:

- **Frontmatter:** `name: kaiju-ground-truth-researcher`, `description: Read-only research into verified external reality (NOAA forecasts, Kalshi API/settlement). Cites docs/superpowers/notes/ and boundary code only. Never proposes designs.`, `model: opus`, `tools: [Read, Grep, Glob, Bash]`, `color: yellow`.
- **BLOCKING doc-load gate:**
  1. `AGENTS.md` (citation discipline)
  2. `docs/superpowers/notes/kalshi-api-contract.md`
  3. `docs/superpowers/notes/kalshi-ws-contract.md`
  4. `docs/superpowers/notes/noaa-forecast-contract.md`
  5. `docs/superpowers/notes/settlement-map.md`
  6. `kaiju/markets/parser.py`
- **Allowed citation sources** explicitly listed: `docs/superpowers/notes/`, `kaiju/markets/parser.py`, `kaiju/markets/kalshi_client.py`, `kaiju/data/forecast.py`, `kaiju/data/obs.py`. Anything else → "outside my citation domain, escalate to `kaiju-quant-researcher`."
- **Forbidden:** proposing designs, writing code, editing files (already enforced by tools), citing internal math/model code (that's the quant researcher's domain), summarizing without citations.
- **Output format:** Research Brief by topic; per-question Q&A with one-sentence answer + evidence block (`file:line` + actual code lines) + confidence (high|medium|low|unable to verify).
- **Decline mode:** if the answer isn't findable in the allowed sources, output "I could not find evidence of X in the citation domain. Confidence: unable to verify." Do NOT fall back on internal code.

Length target: ~150–200 lines.

- [ ] **Step 2: Validate by spawning with a known-answer question**

From the main session, run:

```
Spawn kaiju-ground-truth-researcher with this question:
"What is the cents-band boundary rule for Kalshi temperature markets when the
official daily high is exactly N.5 degrees? Cite the rule from docs/superpowers/notes/
and the implementation from kaiju/markets/parser.py."
```

Expected: `context loaded: ...` line, then a Q&A with two citations — one from `docs/superpowers/notes/settlement-map.md` (or similar) and one from `kaiju/markets/parser.py` showing the `*.5→int` rule. Confidence: high.

If the agent cites `kaiju/strategy/` or `kaiju/model/` instead, the citation-domain enforcement is broken — fix the agent file's allowed-sources section.

- [ ] **Step 3: Commit**

```bash
git add .claude/agents/kaiju-ground-truth-researcher.md
git commit -m "feat(agents): kaiju-ground-truth-researcher — cites notes/ + boundary code only"
```

---

## Task 8: kaiju-quant-researcher agent file

**Files:**
- Create: `.claude/agents/kaiju-quant-researcher.md`

- [ ] **Step 1: Create the agent file**

Use the kit's `agents/researcher.template.md` as the skeleton. Required content:

- **Frontmatter:** `name: kaiju-quant-researcher`, `description: Read-only research into internal math (PMF, calibration, fair value, edge selection, exits). Cites kaiju/model/, kaiju/strategy/, kaiju/eval/ only. Never proposes designs.`, `model: opus`, `tools: [Read, Grep, Glob, Bash]`, `color: yellow`.
- **BLOCKING doc-load gate:**
  1. `ARCHITECTURE.md` (SEAMs section + module map)
  2. `AGENTS.md` (citation discipline section)
- **Allowed citation sources:** `kaiju/model/`, `kaiju/strategy/`, `kaiju/eval/`, `kaiju/types.py` (for PMF/MarketQuote/Position type definitions). Anything else → "outside my citation domain, escalate to `kaiju-ground-truth-researcher`."
- **Forbidden:** designs, code edits, external-reality claims (NOAA/Kalshi behavior is the ground-truth researcher's domain), summaries without citations.
- **Output format:** same as ground-truth researcher.
- **Decline mode:** same shape.

Length target: ~150–200 lines.

- [ ] **Step 2: Validate by spawning with a known-answer question**

From the main session, run:

```
Spawn kaiju-quant-researcher with this question:
"What is the contract of fit_calibration in kaiju/model/calibration.py? What
inputs does it take and what does it return? Cite the function signature and
any docstring."
```

Expected: `context loaded: ARCHITECTURE.md, AGENTS.md`, then a Q&A citing `kaiju/model/calibration.py:<lineno>` with the actual function signature pasted, plus the docstring if present. Confidence: high.

If the agent answers from `docs/superpowers/notes/` instead, the citation-domain enforcement is broken.

- [ ] **Step 3: Commit**

```bash
git add .claude/agents/kaiju-quant-researcher.md
git commit -m "feat(agents): kaiju-quant-researcher — cites internal math/SEAMs only"
```

---

## Task 9: Remove `agentic-feature-kit/`

**Files:**
- Delete: `agentic-feature-kit/` (entire directory)

- [ ] **Step 1: Verify nothing in the tree references the kit by path**

Run: `grep -r "agentic-feature-kit" --include="*.md" --include="*.py" --include="*.json" --include="*.sh" . | grep -v "^Binary"`

Expected: zero matches (the spec only references kit *contents* like principle numbers, not paths). If matches are found, fix or document them before proceeding.

- [ ] **Step 2: Remove the directory**

Run: `rm -rf agentic-feature-kit/`

- [ ] **Step 3: Verify `make check` still green**

Run: `make check`

Expected: green.

- [ ] **Step 4: Commit**

```bash
git add -A agentic-feature-kit/
git commit -m "chore: remove agentic-feature-kit templates (extracted into spec + agents)"
```

Note: `git add -A <path>` correctly stages the deletion of an untracked directory's tracked subtree if any of it had been committed; if the kit was never committed (the working tree showed `?? agentic-feature-kit/` originally), the `rm -rf` alone is enough and no commit is needed. Check `git status` after `rm -rf` — if it shows nothing, skip the commit and move on.

---

## Task 10: Final green check and open PR

- [ ] **Step 1: Run the full gate**

Run: `make check`

Expected: green (pytest + ruff + mypy).

- [ ] **Step 2: Confirm the branch is in good shape**

Run: `git log main..HEAD --oneline`

Expected: roughly 8–10 commits — the spec commit from before this plan started, plus the new commits from Tasks 1–9.

- [ ] **Step 3: Push and open PR**

```bash
git push -u origin agentic-kit/spec
gh pr create --title "Agentic kit foundation: hook + python pack + read-only agents" --body "$(cat <<'BODY'
## Summary

Foundation PR for the agentic-feature-kit setup. Lands the read-only and hook-guarded pieces so the writer agents (engineer + orchestrator) can build on a hardened base in PR 2.

What's in this PR:

- **Spec:** `docs/superpowers/specs/2026-05-22-agentic-feature-kit-setup-design.md`
- **Hook:** `scripts/block-danger-zones.sh` + `.claude/settings.json` PreToolUse wiring. Blocks `Edit`/`Write`/`NotebookEdit` on rail files from `AGENTS.md` danger zones. Tests in `tests/test_danger_zone_hook.py`.
- **Python language pack:** `docs/agents/python-language-pack.md`, 7 patterns ruff/mypy don't catch.
- **Read-only subagents:**
  - `kaiju-reviewer` — diff auditor with B1–B5 behavioral review, no Edit/Write.
  - `kaiju-ground-truth-researcher` — cites `docs/superpowers/notes/` + boundary code only.
  - `kaiju-quant-researcher` — cites internal math (`model/`, `strategy/`, `eval/`) only.
- **Cleanup:** `agentic-feature-kit/` template dir removed.

Design rationale lives in the spec; key choices: kit principle 11 (enforce don't ask) → hook-level danger zones; kit principle 10 (cite don't fabricate) → external/internal researcher split; kit principle 12 (sibling parity) → pack as single source of truth for engineer + reviewer.

## Test plan

- [ ] `make check` green
- [ ] In a Claude Code session, ask Claude to `Edit kaiju/risk/limits.py` → hook blocks with the expected message
- [ ] In a Claude Code session, ask Claude to `Edit kaiju/types.py` → edit proceeds normally
- [ ] Spawn `kaiju-reviewer` on this branch → produces APPROVED with the expected output structure
- [ ] Spawn `kaiju-ground-truth-researcher` on a Kalshi-settlement question → cites only notes/ + parser.py
- [ ] Spawn `kaiju-quant-researcher` on a SEAM-contract question → cites only model/strategy/eval

🤖 Generated with [Claude Code](https://claude.com/claude-code)
BODY
)" --base main
```

- [ ] **Step 4: Auto-merge once CI is green**

```bash
gh pr merge --auto --squash
```

(Branch protection enforces CI green before the merge actually happens; auto-merge waits for the gate.)

---

## Self-Review

**Spec coverage:**

| Spec section | Task(s) implementing it |
|---|---|
| Architecture / Agent roster (read-only entries) | Tasks 6, 7, 8 |
| Danger-Zone Hook (script + settings) | Tasks 1, 2, 3, 4 |
| Python Language Pack | Task 5 |
| Implementation Plan / PR 1 file list | Tasks 1–9 |
| Acceptance criterion #1 (`make check` green) | Task 10 step 1 |
| Acceptance criterion #2 (hook blocks rail, allows normal) | Task 4 step 3 |
| Acceptance criterion #3 (reviewer produces kit format) | Task 6 step 2 |
| Acceptance criterion #4 (ground-truth researcher cite domain) | Task 7 step 2 |
| Acceptance criterion #5 (quant researcher cite domain) | Task 8 step 2 |
| Acceptance criterion #6 (`agentic-feature-kit/` removed) | Task 9 |
| Risk 1 (subagent Skill access) | Out of scope for PR 1 — researchers and reviewer don't use Skill; will surface in PR 2. |
| Risk 2 (hook canonicalization edge cases) | Task 3 step 1 includes `test_hook_blocks_absolute_path_to_rail`. |

Gaps: none for PR 1. PR 2 covers engineer + orchestrator + postmortem gotchas + Risk 1 verification.

**Placeholder scan:** every code step has actual code; every command is exact; no "TBD" / "implement appropriately" / "similar to Task N."

**Type consistency:** agent names are consistent (`kaiju-reviewer`, `kaiju-ground-truth-researcher`, `kaiju-quant-researcher`); file paths consistent across tasks (`scripts/block-danger-zones.sh`, `tests/test_danger_zone_hook.py`, `docs/agents/python-language-pack.md`, `.claude/settings.json`, `.claude/agents/*.md`); the `_invoke` helper used in Task 1 is referenced (not redefined) in Task 3.

One known soft spot: Task 5's markdown content uses placeholders for triple-backticks (the inner code fences inside the pack). The engineer must write real triple-backticks in the saved file. This is called out explicitly in Task 5 Step 1's note.
