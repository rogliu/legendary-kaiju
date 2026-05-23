# Agentic Feature Kit Setup — Design

**Date:** 2026-05-22
**Status:** Approved, ready for implementation plan
**Author:** rogliu (with Claude)

## Feature Overview

Set up a quartet of domain-specific subagents for kaiju (orchestrator, engineer, reviewer, two researchers) plus a Python language pack and a tool-level danger-zone hook. The agents are invoked from the main session via the Task tool and operate with disjoint context budgets per the agentic-feature-kit's universal principles.

The kit itself (`agentic-feature-kit/`) is templates — not committed. Only the filled-in outputs land in the repo. The kit's `principles/universal-principles.md` is referenced inline in this spec where decisions cite it.

## Requirements Summary

### Functional

1. Four subagents materialized in `.claude/agents/`: orchestrator, engineer, reviewer, ground-truth researcher, quant researcher. (One of the "agents" is two researchers — see Architecture below.)
2. One Python language pack at `docs/agents/python-language-pack.md`, loaded by engineer + reviewer.
3. One PreToolUse hook (`scripts/block-danger-zones.sh` + `.claude/settings.json`) that blocks `Edit`/`Write`/`NotebookEdit` on rail files.
4. Postmortem gotcha sections in engineer + orchestrator seeded with 3 named incidents from the recent git log.
5. `agentic-feature-kit/` removed from the working tree after extraction.

### Non-functional

- **Safety-first ordering:** hook + read-only agents land in PR 1; writer agents (engineer, orchestrator) land in PR 2 only after PR 1 has merged.
- **No prompt-only safety:** danger-zone enforcement is hook-level (kit principle 11). Prompts explain the why so agents route around the perimeter efficiently.
- **Tool-level scoping:** reviewers and researchers have no `Edit`/`Write`. Nobody has `gh` access. PR creation stays in the main session (kit principle 11).
- **Sibling parity:** engineer and orchestrator share identical postmortem gotchas and identical references to the Python pack (kit principle 12).
- **Disjoint context:** reviewer does not load `ARCHITECTURE.md` or `LOOP.md` or specs. Researchers are split external (`docs/superpowers/notes/`) vs internal (`kaiju/model|strategy|eval`) to prevent the circular-citation failure mode (kit principle 10).

### Assumptions

- Claude Code subagents (Task tool) can declare a `Skill` tool and invoke superpowers skills. (Verify during PR 1 — if not possible, fall back to inlining the relevant discipline.)
- `.claude/settings.json` is the right home for the shared hook (vs `settings.local.json`, which is user-local). Confirmed: hook should fire for any agent run on this repo by anyone.
- The hook fires in all sessions including main — by design, since `INVARIANTS.md` edits should be deliberate human acts.

## Architecture

### Agent roster, tool scopes, model tiers

| Agent | Model | Tools | Loads (doc-load gate) |
|---|---|---|---|
| `kaiju-orchestrator` | opus | Read, Grep, Glob, Write, Bash, Task, AskUserQuestion, Skill | `AGENTS.md`, `ARCHITECTURE.md`, `docs/INVARIANTS.md`, `docs/agents/LOOP.md`, `README.md`, `docs/superpowers/specs/2026-05-17-kalshi-weather-mispricing-capture-design.md` |
| `kaiju-engineer` | opus | Read, Grep, Glob, Edit, Write, Bash, Skill | `AGENTS.md`, `ARCHITECTURE.md`, `docs/INVARIANTS.md`, `docs/agents/python-language-pack.md`, `CONTRIBUTING.md` |
| `kaiju-reviewer` | opus | Read, Grep, Glob, Bash | `docs/INVARIANTS.md`, `docs/agents/python-language-pack.md`, `AGENTS.md` (danger-zone list only) |
| `kaiju-ground-truth-researcher` | opus | Read, Grep, Glob, Bash | `AGENTS.md` (citation discipline), `docs/superpowers/notes/{kalshi-api-contract,kalshi-ws-contract,noaa-forecast-contract,settlement-map}.md`, `kaiju/markets/parser.py` |
| `kaiju-quant-researcher` | opus | Read, Grep, Glob, Bash | `ARCHITECTURE.md` (SEAMs section + module map), module docstrings of `kaiju/model/`, `kaiju/strategy/`, `kaiju/eval/` on demand |

Notes on tool scoping (kit principle 11 — remove the tool, don't ask):

- Orchestrator has `Write` but not `Edit`. Creates new plan files in `./plans/`; cannot modify source.
- Reviewer and researchers have no `Edit`/`Write`. No `Skill` either — process is fully baked in.
- Nobody has direct `gh` access. PR creation runs from the main session.
- Engineer and orchestrator have `Skill` to invoke specific superpowers skills (see "Skills integration" below).

### Skills integration (hybrid per agreed design)

| Agent | Skills invoked | Why |
|---|---|---|
| Engineer | `superpowers:test-driven-development` at start of implementation; `superpowers:verification-before-completion` as final gate | TDD + verification are battle-tested cross-cutting discipline; re-encoding inside the agent risks drift |
| Reviewer | None | Kit's B1–B5 forced-enumeration is its strongest contribution; don't dilute |
| Researchers | None | Citation discipline is narrow enough to bake in directly |
| Orchestrator | `superpowers:brainstorming` (Step 1: requirements), `superpowers:writing-plans` (Step 5: plan output), `superpowers:requesting-code-review` (wave gates) | Skills handle the universal planning shape; orchestrator carries the kaiju-specific context that makes the planning concrete |

The pattern: agents carry domain context + role-specific process; skills carry cross-cutting discipline. Where they overlap, prefer the skill.

### Researcher split (external vs internal)

Per kit principle 10's canonical failure mode — an agent answering "how does X behave" by citing internal code that *encodes our assumption* about X, instead of the verified-external-reality docs — researchers are split:

- **`kaiju-ground-truth-researcher`** — only allowed to cite `docs/superpowers/notes/` and API-boundary code (`markets/parser.py`, `markets/kalshi_client.py`, `data/forecast.py`, `data/obs.py`). Output is "what NOAA/Kalshi actually do." If the answer isn't in `notes/`, the answer is "couldn't verify."
- **`kaiju-quant-researcher`** — only allowed to cite internal math/seam code (`model/`, `strategy/`, `eval/`). Output is "what our PMF/calibration/fair-value pipeline actually does." Cannot make external-reality claims.

## Danger-Zone Hook

### `scripts/block-danger-zones.sh`

```bash
#!/usr/bin/env bash
# Block Edit/Write/NotebookEdit on rail files. Reason: AGENTS.md danger zones must be
# human-edited only; runtime rail edits can corrupt the safety substrate.
# Fires in ALL Claude Code sessions on this repo (including the main session).
set -euo pipefail

input="$(cat)"
path="$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.path // ""')"
[ -z "$path" ] && exit 0   # not a path-bearing tool call, allow

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
rel="${path#$repo_root/}"

block() {
  printf 'BLOCKED: %s is a rail file (AGENTS.md danger zone).\nReason: %s\nResolution: Stop & Escalate to a human.\n' "$1" "$2" >&2
  exit 2   # exit 2 = block the tool call (Claude Code convention)
}

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

exit 0
```

### `.claude/settings.json` wiring

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

### Scope decisions

- Hook fires in **all sessions including main** (by design — `INVARIANTS.md` edits are deliberate human acts).
- Hook does **not** block reads — agents must read danger-zone files to understand the constraints.
- `Bash` is **not** matched. `gh pr merge`, `git push --force`, `rm -rf` are governed by branch protection and human review, not this hook. (Possible follow-up: a Bash-matcher hook for destructive commands; out of scope here.)
- Committed to `settings.json` (not `settings.local.json`) so the rail applies to every clone, every agent, every operator.

### Escape valve for legitimate rail edits

A human edits the file via their editor directly, or runs the tool from outside Claude Code, or temporarily removes the hook entry in `settings.json`. There is no "let me through this once" affordance inside Claude Code — that's the point.

## Python Language Pack

Lives at `docs/agents/python-language-pack.md`. Format mirrors the kit's Java pack: ENFORCE / WHY / DETECT / FIX + minimal example.

Seeded with 7 patterns. All verified not redundant with current ruff config (which has only `line-length = 100`, `target-version = "py312"`). If ruff is tightened later, redundant patterns get removed per kit principle 4 ("patterns in this file should be the ones the linter can't catch").

### Pattern 1: Frozen dataclasses for value types

**ENFORCE:** Types that cross module boundaries are `@dataclass(frozen=True)`.
**WHY:** Kaiju runs an intraday loop where the same object can be observed by multiple components in sequence; mutation in one shifts behavior elsewhere unpredictably.
**DETECT:** `@dataclass` without `frozen=True` in `kaiju/types.py` or as a return type from `data/`, `model/`, `markets/`.
**FIX:** Add `frozen=True`. If mutation is genuinely required, refactor to return a new instance with `dataclasses.replace`.

### Pattern 2: Integer cents, never float, for prices and fees

**ENFORCE:** Kalshi prices/fees are `int` cents (0–99 or fee bps). Only PMF probabilities are `float`.
**WHY:** Float equality against fee thresholds drifts (`0.30 + 0.05 != 0.35` in IEEE 754); a fees regression would be silent.
**DETECT:** `float` in a function signature in `kaiju/strategy/fees.py`, `kaiju/strategy/sizing.py`, or any `==`/`!=`/`<=`/`>=` comparison involving a price/fee.
**FIX:** Use `int` cents. For arithmetic that produces fractional cents, decide on rounding semantics explicitly in the design.

### Pattern 3: No silent exception swallowing in `runner.py`, `markets/`, `execution/`

**ENFORCE:** Every `except` either re-raises, logs at ERROR with `exc_info=True`, or has a *named* recovery action documented in a comment.
**WHY:** In an autonomous loop, silently eaten exceptions hide market disconnections, broker rejections, settlement errors. The loop keeps "succeeding" with stale state.
**DETECT:** `except Exception` or `except BaseException` followed by anything other than `raise`, `log.exception(...)`, `log.error(..., exc_info=True)`, or a documented recovery (`# recovery: <reason>`).
**FIX:** Either re-raise, or log with `exc_info=True`, or annotate the recovery path. Catch-and-continue without all three is forbidden in these modules.

### Pattern 4: Pytest fixtures + `tmp_path`, no hardcoded `/tmp/...`

**ENFORCE:** Tests get filesystem paths from `tmp_path` / `tmp_path_factory`.
**WHY:** Hardcoded `/tmp/...` breaks CI parallelism and leaks state between runs — a flake the loop can't diagnose.
**DETECT:** Literal `"/tmp/"` or `tempfile.mkdtemp(` in `tests/`.
**FIX:** Take `tmp_path: pathlib.Path` as a fixture parameter; use `tmp_path / "..."` for file paths.

### Pattern 5: SEAM functions are pure

**ENFORCE:** The five SEAMs — `model/distribution.pmf_from_nbm_percentiles`, `model/distribution.blend_pmfs`, `model/calibration.fit_calibration|apply_calibration`, `model/nowcast.nowcast_pmf`, `strategy/edge.select_gap_trades`, `strategy/exit_policy.decide_exit` — take all inputs as parameters. No `time.time()`, `datetime.now()`, network I/O, DB reads, or unparametrized module-level globals.
**WHY:** `eval/gate` scores competing SEAM implementations on replay. Non-determinism breaks the ranking and your primary safety mechanism for experimentation.
**DETECT:** `time.`, `datetime.now`, `requests.`, `httpx.`, `sqlite3.`, or unparametrized module-level state inside a SEAM body.
**FIX:** Inject the dependency as a parameter. Tests provide deterministic stubs; production injects the real clock/client.

### Pattern 6: DB access only through `kaiju.state` DAL

**ENFORCE:** No `sqlite3.connect`, no raw SQL outside `kaiju/state.py`.
**WHY:** Migration and schema discipline live in one place; ad-hoc queries in `runner.py` or `execution/` would drift from the schema model.
**DETECT:** `import sqlite3`, `sqlite3.connect(`, or raw `CREATE TABLE`/`INSERT INTO`/`SELECT ` strings outside `kaiju/state.py`.
**FIX:** Add a method to `kaiju.state` and call it. Schema changes go through a migration in the same file.

### Pattern 7: Structured logger via `kaiju.logging`, never ad-hoc `logging.getLogger`

**ENFORCE:** Import the configured logger from `kaiju.logging`.
**WHY:** Ad-hoc loggers bypass the configured structured fields and JSON formatting; log analysis stops working.
**DETECT:** `logging.getLogger(` outside `kaiju/logging.py`. (Note: `import logging` for type hints is fine; only the `getLogger` call is the violation.)
**FIX:** `from kaiju.logging import get_logger; log = get_logger(__name__)`. Call `configure_logging()` once at process startup (already done in `runner.py`).

### How to add a new pattern

1. Format: ENFORCE / WHY / DETECT / FIX + minimal bad/good example.
2. WHY must reference a real failure mode if possible (postmortem-named).
3. If ruff/mypy already catches it, prefer the linter — patterns in this file should be the ones the linter can't catch.
4. After adding, sweep `kaiju-engineer.md` / `kaiju-reviewer.md` — if they encode a redundant local rule, delete the local one.

## Postmortem Gotchas (seed entries)

Identical in `kaiju-engineer.md` and `kaiju-orchestrator.md` (kit principle 12 — propagate to siblings; treat divergence as a smell).

### GOTCHA `3abf9e1` (May 2026): reconcile_with_broker against guessed schema

- **Symptom:** `reconcile_with_broker` built against an inferred Kalshi `MarketPosition` schema; the real schema differed and reconciliation failed silently until a fix landed.
- **Root cause:** External API shape was inferred from internal type expectations rather than cited from `docs/superpowers/notes/` or a live API response.
- **Fix:** Rewrote against the real `MarketPosition` schema.
- **Prevention:** External API shapes must be cited from `docs/superpowers/notes/` (the verified ground-truth docs) or a captured live response. Never inferred. When in doubt, spawn `kaiju-ground-truth-researcher`.

### GOTCHA `e0cfb4c` (May 2026): CI secrets guard misfired on legitimate input

- **Symptom:** A defensive CI guard intended to block accidental secret commits flagged a legitimate file pattern, blocking otherwise-good work.
- **Root cause:** The guard was added without a test that proves a legitimate input passes through.
- **Fix:** Tuned the guard; added a positive test alongside the negative test.
- **Prevention:** When adding a guard or filter, write the test that proves a legitimate input *passes* before declaring done. A guard is two-sided: it must block bad input AND admit good input.

### GOTCHA `0f5a1d4` (May 2026): paper fills not persisted across restarts

- **Symptom:** README-tracked limitation #1 — paper fills lived only in memory; restarts wiped them; iteration loops couldn't observe persistence regressions.
- **Root cause:** In-memory state was added without a "what happens on restart" answer at design time.
- **Fix:** Persisted fills + flipped order status in `kaiju.state`.
- **Prevention:** Any new in-memory state in `kaiju/` must answer "what happens on restart" at design time. If the answer is "we lose it," that's a designed decision documented in the spec, not an oversight.

## Output Contracts (per role)

Kit's templates verbatim per role — summarized here, fully specified in each agent file.

**Orchestrator output:** plan markdown with sections — Feature Overview, Requirements (functional / non-functional / assumptions), Cross-Domain Consultations (with researcher evidence), Architecture, Implementation Tasks (phased), Testing Strategy, Risks, Open Questions. Plus a wave decomposition with per-task agent assignment (engineer for everything since we dropped engineer-lite).

**Engineer output:** markdown report with sections — Files Changed (path + summary), Deliberately Not Changed (path + why out of scope), Tests Added/Modified (test name + what it covers), Blockers (if any).

**Reviewer output:** Files Reviewed (numbered list), Behavioral Findings (per-hunk B1–B5 artifacts), Pattern Findings (severity + file:line + issue + fix), Verdict (APPROVED | CHANGES_REQUESTED). CRITICAL finding blocks APPROVED regardless of pattern checklist cleanliness.

**Researcher output (both):** Research Brief by topic; per-question Q&A with one-sentence answer, evidence (`file:line` + actual code block), confidence (high|medium|low|unable to verify). Strict word budget honored from caller.

## Implementation Plan (two PRs)

### PR 1 — Foundation (read-only)

Files:
- `scripts/block-danger-zones.sh` (new, executable)
- `.claude/settings.json` (new, committed)
- `docs/agents/python-language-pack.md` (new, ~7 patterns above)
- `.claude/agents/kaiju-reviewer.md` (new, filled from reviewer template)
- `.claude/agents/kaiju-ground-truth-researcher.md` (new)
- `.claude/agents/kaiju-quant-researcher.md` (new)
- `agentic-feature-kit/` (delete)
- `.gitignore` (add `.claude/settings.local.json` if not already)

Acceptance criteria for PR 1:
1. `make check` green
2. Attempting `Edit kaiju/risk/limits.py` from any Claude Code session in this repo produces `BLOCKED: ... is a rail file ...` and exit code 2; `Edit kaiju/types.py` works normally
3. Spawning `kaiju-reviewer` against the current branch produces the kit's review format (Files Reviewed → Behavioral Findings → Pattern Findings → Verdict)
4. Spawning `kaiju-ground-truth-researcher` with a Kalshi settlement question produces evidence cited only from `docs/superpowers/notes/` or `markets/parser.py`; if not findable in notes, declines with "couldn't verify"
5. Spawning `kaiju-quant-researcher` with a SEAM-contract question produces evidence cited only from `kaiju/model|strategy|eval`
6. `agentic-feature-kit/` no longer present in the working tree

### PR 2 — Writers

Files:
- `.claude/agents/kaiju-engineer.md` (new)
- `.claude/agents/kaiju-orchestrator.md` (new)

Acceptance criteria for PR 2:
1. `make check` green
2. Spawning `kaiju-engineer` to implement a small mechanical task (e.g., add a typed field to `kaiju/types.py` and thread it through) produces the kit's engineer output format, with TDD invocation visible in the trace and `verification-before-completion` invoked before the "done" report
3. Spawning `kaiju-orchestrator` for a small feature produces a plan that invokes `superpowers:brainstorming` for requirements and `superpowers:writing-plans` for plan structure, with kaiju-specific danger-zone awareness in the wave decomposition
4. Engineer attempting `Edit kaiju/risk/limits.py` is blocked by the hook with the expected message
5. Engineer's hard-rules section, postmortem gotchas, and Python-pack reference are byte-identical to orchestrator's (kit principle 12); diff confirms parity

## Testing Strategy

Each agent is testable in isolation by spawning it via the Task tool from the main session and inspecting the output:

- Hook is testable independently: pipe a fake tool-call JSON into `scripts/block-danger-zones.sh` and assert exit code + stderr message.
- Reviewer is testable by pointing it at a committed branch with known violations and asserting the verdict.
- Researchers are testable by asking them a question with a known answer in their citation domain and asserting the cited line matches.
- Engineer + orchestrator are testable end-to-end by running a small feature through the loop.

Acceptance tests for the hook (will become a small test in `tests/`):

```python
# tests/test_danger_zone_hook.py
def test_hook_blocks_risk(tmp_path):
    # invoke the hook script with a fake stdin payload, assert exit 2
def test_hook_blocks_invariants_md(...):
    ...
def test_hook_allows_kaiju_types(...):
    # not a rail file — exit 0
```

(Adding this hook test is part of PR 1.)

## Risks and Mitigations

1. **Risk:** Subagents can't invoke skills via the `Skill` tool. **Mitigation:** PR 1 verifies skill invocation works inside a Task-spawned subagent before PR 2 designs depend on it. Fallback: inline the relevant TDD/verification discipline directly in `kaiju-engineer.md`.
2. **Risk:** The hook script's repo-root detection or path-canonicalization fails on edge cases (symlinks, absolute paths outside the repo). **Mitigation:** Acceptance criterion #2 in PR 1 exercises the hook directly; the test in `tests/test_danger_zone_hook.py` covers the path-handling cases.
3. **Risk:** Postmortem gotchas drift between engineer.md and orchestrator.md over time. **Mitigation:** Add a CI check (small pytest) that diffs the gotcha section between the two files and fails on divergence. Out of scope for this spec, follow-up.
4. **Risk:** Python pack patterns are wrong or annoying in practice. **Mitigation:** First reviewer run on a real PR will surface mismatches; iterate the pack based on real findings, not speculation. User explicitly said "iterate on this."
5. **Risk:** The ground-truth researcher's `notes/` list (currently 4 files) grows and the gate becomes stale. **Mitigation:** Reference the directory rather than enumerating individual files if the count exceeds ~8; the agent reads on demand.

## Open Questions

1. **Subagent `Skill` access:** confirm during PR 1 (see Risk 1).
2. **Bash-matcher hook for destructive commands** (`git push --force`, `gh pr merge` to main, `rm -rf`): deliberately out of scope here; follow-up if value emerges.
3. **Gotcha-drift CI check:** out of scope here; follow-up.

Resolved during spec writing:
- `CONTRIBUTING.md` content: confirmed relevant (TDD definition-of-done, scope-lock workflow, ledger discipline). Stays in engineer doc-load gate.
- `kaiju.logging` shape: `from kaiju.logging import get_logger`; `configure_logging()` called once in `runner.py`. Pattern 7 updated accordingly.

## References to Universal Principles

For traceability, decisions in this spec cite kit principles from `agentic-feature-kit/principles/universal-principles.md` (which is deleted at the end of PR 1). The principles in question:

- **#1 Constraints first, examples second** — each Python pack pattern has an ENFORCE rule, not just an example.
- **#2 Every rule has a why** — same.
- **#3 Forced written artifacts beat checklists** — reviewer's B1–B5 hunk artifact.
- **#4 Postmortem-named gotchas beat generic advice** — gotcha section seeded from real git log, not generic best practices.
- **#5 Don't waste the doc load** — engineer doesn't load business context; reviewer doesn't load architecture; researchers don't load each other's domain.
- **#6 Asymmetric context budgets per role** — see roster table.
- **#7 Steelman to defeat self-defense** — engineer + orchestrator carry this in their workflow.
- **#8 Falsification prior** — reviewer's default assumption is "there is a bug here."
- **#9 Tier the model to the task** — N/A since engineer-lite is dropped; all on Opus.
- **#10 Cite, don't fabricate** — researcher split (external vs internal) prevents the canonical failure mode.
- **#11 Don't ask for safety; enforce it** — danger-zone hook + tool scoping (no Edit on reviewer/researchers, no gh anywhere).
- **#12 Propagate to siblings; treat divergence as a smell** — engineer/orchestrator share identical hard rules + gotchas + pack reference.

## Definition of Done

PR 1 merged AND PR 2 merged AND the next real feature in kaiju is shipped end-to-end through the agent quartet (orchestrator plans → engineer implements → reviewer approves → main session opens PR). At that point the kit setup is in production use, and iteration on the pack/gotchas/agents proceeds organically from real findings.
