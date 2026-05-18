# Task NNNN — <short title>

> Copy this file to `backlog/NNNN-slug.md` and fill every section. A task with
> a blank section is not ready to be claimed.

## Motivation

Why this matters in one short paragraph. Link the code/doc evidence (file:line
or a docstring quote) so the next agent doesn't have to rediscover it.

## Scope

- **Owned module(s):** e.g. `kaiju/markets/ws_client.py`
- **Files expected to change:** exact paths.
- **Conflict scope:** the set of files this touches (so the backlog can be
  curated to keep concurrently-claimable tasks file-disjoint).

## Acceptance criteria

- The failing test to write first (name it, state what it asserts).
- Observable behavior when done.
- `make check` fully green; no invariant/test weakened; scope lock intact.

## Out of scope

What this task explicitly does NOT do (prevents sprawl).

## Danger-zone check

Confirm this touches **none** of: `kaiju/risk/`, `kaiju/eval/gate.py`,
`kaiju/config.py` live path, `kaiju/markets/parser.py` `_SETTLEMENT_MAP`,
`docs/superpowers/notes/`, or the rail files (see `docs/INVARIANTS.md`
bottom). If it does → this is NOT a loop task; it is a human escalation.

> ☑ Confirmed no danger-zone changes / ☐ DANGER — human only

## Definition of done

Per `CONTRIBUTING.md` "Definition of done" — all six conditions.
