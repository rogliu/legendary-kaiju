# Task 0001 — thin per-seam variant registry

## Motivation

`docs/agents/EXPERIMENTS.md` defines a hypothesis tournament behind the five
seams, but `kaiju/runner.py` calls each incumbent directly (e.g.
`pmf_from_nbm_percentiles`, `blend_pmfs` with hardcoded 0.6/0.4,
`nowcast_pmf`, `select_gap_trades`, `decide_exit`). Without a selection
mechanism, experiments can't be run side-by-side at scale. This is the
prerequisite infra for the tournament.

## Scope

- **Owned module(s):** new `kaiju/seams.py` (or `kaiju/registry.py`).
- **Files expected to change:** new registry module; `kaiju/runner.py`
  (resolve seam implementations through the registry instead of direct
  imports); new `tests/test_seams.py`.
- **Conflict scope:** the new module + the seam-call sites in `runner.py`.

## Acceptance criteria

- Write `tests/test_seams.py::test_default_is_incumbent` first: resolving
  each of the 5 seams with no override returns the current incumbent
  callable, and its behavior is byte-for-byte unchanged.
- A seam implementation is selectable by name (config/env), default =
  incumbent. Unknown name → fail loud (`KeyError`/`ValueError`), never a
  silent fallback.
- Registry is type-correct (the registered callables keep the exact seam
  signatures in `EXPERIMENTS.md`).
- `make check` green; no behavior change when nothing is overridden.

## Out of scope

Adding any actual new variant. Changing seam signatures. Touching the gate.

## Danger-zone check

Touches `runner.py` (not a danger zone) + a new module + a new test. Does
NOT touch `risk/`, `eval/gate.py`, `config.py` live path,
`parser._SETTLEMENT_MAP`, `notes/`, or rail files.

> ☑ Confirmed no danger-zone changes

## Definition of done

Per `CONTRIBUTING.md` — all six conditions.
