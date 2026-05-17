# THE LOOP CONTRACT

This defines exactly what an autonomous loop (`/loop`) is allowed to do on this
codebase. `/loop` is the *engine*; this document plus `docs/INVARIANTS.md` and
the test gate are the *rails*. An indefinite unsupervised loop is only safe
because its scope, its failure behavior, and its merge bar are all bounded and
executable. Read `docs/INVARIANTS.md` first; it is assumed here.

## What one iteration IS

An iteration is **one bounded, reviewed, reverted-or-merged change**. Exactly:

1. **Select one task.** Take a single task from `docs/agents/backlog/` (claim
   it by `git mv` into `docs/agents/in-progress/<loop-id>/` — the move is the
   lock). If the backlog is empty or no task is eligible under these rails:
   **stop cleanly** (do not invent scope-expanding work).
2. **Branch.** `git switch -c loop/<short-task-slug>` off current `main`.
3. **TDD.** Write the failing test, see it fail, implement the minimum to pass,
   refactor. One responsibility. No "while I'm here" changes.
4. **Gate.** Run `make check` (pytest + ruff + mypy). It must be fully green.
5. **Self-check against `docs/INVARIANTS.md`.** Did this touch a danger zone?
   Weaken any test/assertion? Widen scope? If yes → Stop & Escalate (below).
6. **Merge only if green.** Fast-forward/rebase onto `main`, `make check` green
   on the merge result, then merge. `main` must always stay runnable.
7. **Record.** Append one line to `docs/agents/LEDGER.md`: timestamp, loop-id,
   task, branch, files, gate result, merged?, gate-score delta, next.
8. **End the iteration.** Move the task file to `docs/agents/done/`. Pick the
   next task, or stop.

> The backlog / in-progress / done / LEDGER.md machinery ships in the scale-out
> tier. Until it exists, a single loop runs steps 2–7 against an explicit task
> the human handed it, and records progress in the commit log.

## Hard rules (non-negotiable)

- **One task per iteration.** No batching, no sprawl, no opportunistic refactor.
- **Never make the gate pass by weakening it.** No deleting/loosening tests, no
  editing `docs/INVARIANTS.md`, `tests/test_scope_lock.py`, or any danger-zone
  file to get green. Gate red → fix the change or revert it. Never disable.
- **Scope is locked to NYC `KXHIGHNY`.** Adding a city/market is out of scope
  for any loop, forever, by definition. It trips `tests/test_scope_lock.py`.
- **No real money, ever, autonomously.** The loop never sets `mode=live`,
  never sets/handles the arm token, never touches the live path. That boundary
  is human-only (INVARIANTS A2/A3).
- **TDD, DRY, YAGNI.** A change without a test that would fail without it is
  not done.

## Stop & Escalate — bounded failure for an "indefinite" loop

An indefinite loop MUST have non-infinite failure modes. Stop and write the
reason to the ledger / surface to the human when ANY of these holds:

- **Gate regressed and you cannot fix it within this one bounded task** →
  revert the branch, do **not** merge, log, continue to the next task (or stop
  after `K=3` consecutive unfixable failures).
- **The task requires touching a danger zone** (INVARIANTS bottom: `risk/`,
  `eval/gate.py`, `config.py` live path, `parser._SETTLEMENT_MAP`,
  `docs/superpowers/notes/`, the rails files) → **stop, escalate, do not
  proceed.** Human only.
- **The task requires real-money / live arming** → hard stop. Never autonomous.
- **No eligible bounded task is available** → stop cleanly. Do not manufacture
  scope-expanding or speculative work to keep busy.
- **The plan/spec is wrong or contradictory** → stop and escalate; do not
  "fix" intent unilaterally.

## Anti-thrash

If `N=5` consecutive iterations produce no net progress — no backlog burndown
**and** no improvement in the promotion-gate score (`eval/gate`) — **stop and
report.** Looping without convergence is a failure state, not work. The ledger
is the shared memory that makes "did this already / is this in flight"
answerable; consult it before selecting a task so loops converge instead of
circle.

## Running many loops concurrently

The model that makes "tons of agents" safe rather than terrifying:

- **Task claiming = a git move.** `git mv backlog/T → in-progress/<loop-id>/T`
  is an atomic lock; two loops cannot grab the same task.
- **Module ownership.** The backlog is curated so concurrently-claimable tasks
  do not share files; each task declares its conflict scope.
- **`main` + required-green CI is the only serialization point.** Loops rebase
  on `main`; CI re-runs `make check`; `main` is never broken. CI — not a human
  — is the trust boundary for an unsupervised merge.
- **The promotion gate is the scoreboard.** When loops explore competing
  strategy/model variants behind the stable seams (`model/distribution`,
  `model/calibration`, `model/nowcast`, `strategy/edge`, `strategy/exit_policy`),
  `eval/gate` is the objective referee — only an improvement merges. This is
  how the system scales: a hypothesis tournament behind frozen interfaces, not
  many agents editing one runner.

## The one command

```
make check        # pytest + ruff + mypy — must be fully green before any merge
```

Green is the precondition for merge. It is never the goal; a correct, focused,
in-scope change that happens to be green is the goal.
