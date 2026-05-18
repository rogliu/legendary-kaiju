# docs/agents/ — the work-intake system

How loops get bounded work and stay out of each other's way. The behavioral
contract is `LOOP.md`; this explains the directory mechanics.

## Directories

| Dir | Meaning |
|---|---|
| `backlog/` | Available tasks. Self-contained, in-scope, non-danger-zone, with acceptance criteria. |
| `in-progress/<loop-id>/` | Claimed tasks. The `git mv` into here **is the lock** — atomic, so two loops cannot grab the same task. |
| `done/` | Completed tasks (kept for the ledger trail / "did we try this already"). |

`<loop-id>` is a short stable id for the running loop (e.g. `loopA`,
`loop-2026-05-17a`). Pick one and reuse it for the loop's lifetime.

## Lifecycle

```
backlog/NNNN-slug.md
  → git mv → in-progress/<loop-id>/NNNN-slug.md   (claim = lock)
  → work the task on branch loop/NNNN-slug (see CONTRIBUTING.md)
  → git mv → done/NNNN-slug.md                    (close)
  → append one line to LEDGER.md
```

If two loops race the same `git mv`, exactly one wins (the other's move
fails because the source path is gone) — the loser picks a different task.

## Rules

- **Only take from `backlog/`.** Never invent a task to stay busy. Empty
  backlog (or nothing eligible under `LOOP.md`) → stop cleanly.
- **One task at a time per loop.** Finish or revert before claiming another.
- **Negative results count.** A tried-and-rejected experiment goes to `done/`
  with its result in the ledger, so it is not re-run.
- **New tasks** must use `TASK_TEMPLATE.md` and pass the danger-zone check in
  it. A loop may *propose* a task file into `backlog/` only if it is in-scope
  and non-danger-zone; anything else is a human escalation.

## Numbering

Zero-padded sequential (`0001`, `0002`, …). Never reuse a number; a task that
moves to `done/` keeps its number forever.
