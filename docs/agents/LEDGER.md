# LEDGER — append-only loop progress

The shared memory that makes an indefinite loop *converge* instead of circle,
and lets concurrent loops see what's been tried / what's in flight. **Append
only.** Never rewrite or delete a line. Consult it before selecting a task.

One line per iteration:

```
<UTC timestamp> | <loop-id> | <task NNNN> | <branch> | <files touched> | gate:<pass|fail> | merged:<yes|no|reverted> | gate-score Δ:<note> | next:<NNNN|stop:reason>
```

`gate-score Δ` = change in the promotion-gate metric (or `n/a` for infra/docs
tasks). A negative-result experiment is a *valid* outcome — record it
(`merged:no`, the result) so it is not re-run.

---

## Genesis

```
2026-05-17 | human | substrate-core      | main | tests/test_scope_lock.py, docs/INVARIANTS.md, docs/agents/LOOP.md, AGENTS.md, Makefile | gate:pass | merged:yes (24be5f5) | gate-score Δ:n/a | next:scale-out
2026-05-17 | human | substrate-scale-out | main | CONTRIBUTING.md, ARCHITECTURE.md, docs/agents/*, .github/* | gate:pass | merged:yes | gate-score Δ:n/a | next:backlog open (0001-0003)
```

## Iterations

<!-- loops append below this line -->
