# AGENTS.md — read this first

**What this is:** `kaiju`, an autonomous Kalshi weather-temperature trading bot
(mispricing-capture, NYC daily-high). It is real-money-*capable* but currently
a **shadow-paper proof harness**: it has never traded real money, and is not
proven profitable. Real money is gated behind a human checklist (`README.md`).

**Who you probably are:** an agent in an iteration loop. This codebase is built
to be iterated on by many unsupervised agents. That is only safe because the
rails below are *executable*. Follow them exactly.

## Prime directives (non-negotiable)

1. **Read `docs/INVARIANTS.md` before changing anything.** Every invariant is a
   test. If you think you must weaken/delete/work-around one — **STOP**, that is
   a human escalation, never your call.
2. **`make check` must be fully green before any merge to `main`.** Never make
   it pass by deleting a test, loosening an assertion, or editing a rail file.
   Gate red → fix or revert. Never disable.
3. **One bounded, in-scope, test-driven change at a time.** DRY, YAGNI, TDD.
   No "while I'm here" sprawl.
4. **Scope is locked to one market (NYC `KXHIGHNY`).** Adding a city/market is
   out of scope by definition; it trips `tests/test_scope_lock.py`.
5. **Never touch the real-money / live path autonomously.** No `mode=live`, no
   arm token, no danger-zone files (listed at the bottom of `INVARIANTS.md`).
   Those are human-only.
6. **If looping, follow `docs/agents/LOOP.md`** — the one-iteration contract and
   the Stop & Escalate conditions (an indefinite loop must fail bounded).

## The one command

```
make check          # pytest + ruff + mypy — green is the precondition to merge
```

## Map

| If you need… | Read |
|---|---|
| The rules you cannot break (test-linked) | `docs/INVARIANTS.md` |
| How one loop iteration must run | `docs/agents/LOOP.md` |
| What the system is / why (current design) | `docs/superpowers/specs/2026-05-17-kalshi-weather-mispricing-capture-design.md` |
| Verified external reality (Kalshi/NOAA/settlement) — **ground truth, do not edit without re-verifying** | `docs/superpowers/notes/` |
| Operator runbook + GO-LIVE checklist + limitations | `README.md` |

When in doubt, don't trade and don't merge. A correct, focused, in-scope change
is the goal; a green gate is only its precondition.
