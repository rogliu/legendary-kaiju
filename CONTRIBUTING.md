# CONTRIBUTING

The mechanical protocol. The *rules* are `docs/INVARIANTS.md`; the *loop
behavior* is `docs/agents/LOOP.md`; the *system* is `ARCHITECTURE.md`. This
page is just "how to make one change correctly."

## Definition of done

A change is done when **all** hold:

1. It addresses exactly one bounded task. No sprawl, no opportunistic refactor.
2. There is a test that **fails without the change and passes with it** (TDD).
3. `make check` is fully green (pytest + ruff + mypy) — on the change *and*
   on the result of merging it onto `main`.
4. It touched no danger zone (`docs/INVARIANTS.md` bottom) and weakened no
   test, assertion, or invariant.
5. It stayed in scope (NYC `KXHIGHNY`; `tests/test_scope_lock.py` green).
6. The ledger line is appended (`docs/agents/LEDGER.md`).

If any fails, it is not done — fix it or revert it. Never silence the gate.

## Workflow

```bash
# 1. Claim a task (the git move IS the lock — prevents two loops colliding)
git mv docs/agents/backlog/NNNN-slug.md docs/agents/in-progress/<loop-id>/

# 2. Branch off main
git switch -c loop/NNNN-slug

# 3. TDD: failing test → see it fail → minimal impl → green → refactor
#    Run the single test first, then the full gate:
uv run pytest tests/path/test_x.py::test_y -v
make check

# 4. Rebase onto main, verify green on the result, merge
git switch main && git pull --ff-only        # if remote tracking
git switch loop/NNNN-slug && git rebase main
make check                                    # must be green post-rebase
git switch main && git merge --ff-only loop/NNNN-slug

# 5. Record + close out
#   append a line to docs/agents/LEDGER.md
git mv docs/agents/in-progress/<loop-id>/NNNN-slug.md docs/agents/done/
git commit
```

## Conventions

- **Branches:** `loop/<NNNN-slug>` (autonomous) or `feat/<slug>` / `fix/<slug>`
  (human).
- **Commits:** conventional prefix (`feat:`, `fix:`, `test:`, `docs:`,
  `refactor:`). One logical change per commit.
- **Tests:** `tests/` mirrors `kaiju/`. Plain `pytest`, `def test_*`.
  Offline and deterministic — no network (mock `httpx` with `respx`).
- **Secrets:** the Kalshi RSA key lives in `.env` (gitignored). **Never**
  commit it; never paste a key into code, a test, or a fixture. CI fails the
  build if a private key or `.env` is tracked.
- **Verified contracts** (`docs/superpowers/notes/`) are externally-checked
  ground truth. Do not edit without re-verifying against the live source —
  treat as an escalation.

## Review

Non-trivial changes get two-stage review (spec compliance, then code
quality) before merge — this discipline caught ~10 critical money/safety
bugs during the build. Danger-zone changes additionally require the human
owner via `CODEOWNERS`. An autonomous loop never reviews its own danger-zone
change — it stops and escalates instead.
