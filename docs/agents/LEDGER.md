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

```
2026-05-18 02:14:39Z | loopA | 0001 | loop/0001-variant-registry | kaiju/seams.py, kaiju/runner.py, tests/test_seams.py | gate:pass | merged:auto-pending | gate-score Δ:n/a (infra; default==incumbent, byte-for-byte no behavior change) | next:0002
2026-06-25 15:04:56Z | claude/relaxed-meitner | 0002 | claude/relaxed-meitner-fts7rl | kaiju/execution/paper_sim.py, kaiju/runner.py, tests/execution/test_paper_sim.py | gate:pass | merged:no (pushed to feature branch; no PR per session instr) | gate-score Δ:n/a (paper-book fidelity — orderbook_delta now applied incrementally; deltas were previously dropped, so shadow-paper fills now track the live book between snapshots; affects future fill sim, not a current gate metric) | next:0003 (review APPROVED; flagged follow-ups → 0004)
2026-06-25 15:45:20Z | claude/relaxed-meitner | 0005 | claude/relaxed-meitner-fts7rl | kaiju/state.py, kaiju/execution/position_manager.py, kaiju/execution/paper_sim.py, tests/test_state.py, tests/execution/test_paper_sim.py | gate:pass | merged:no (pushed to feature branch; no PR per session instr) | gate-score Δ:n/a (CORRECTNESS — paper exits now CLOSE positions instead of growing them; removes held-to-settlement inflation in shadow-paper; orders carry buy/sell action; prerequisite discovered while scoping 0003) | next:0003 (review APPROVED; sell fills at top-of-book bid noted — address exit-price conservatism in 0003)
2026-06-25 15:57:52Z | claude/relaxed-meitner | 0003 | claude/relaxed-meitner-fts7rl | kaiju/runner.py, tests/test_settlement.py | gate:pass | merged:no (pushed to feature branch; no PR per session instr) | gate-score Δ:+round-trip realized PnL now enters sim_pnl_usd (gate's go-live PnL no longer undercounts convergence round-trips); held-to-settlement + round-trip non-overlapping (0005 reduces position on exit); eval/gate.py untouched (A8); B5 idempotent | next:0004 (review APPROVED; re-scoped — premise drift, see task note; conservative-fill + real fill_rate are follow-ups)
2026-06-25 16:31:48Z | claude/relaxed-meitner | 0004 | claude/relaxed-meitner-fts7rl | kaiju/runner.py, tests/test_runner_ws_events.py | gate:pass | merged:no (pushed to feature branch; no PR per session instr) | gate-score Δ:n/a (test coverage + byte-for-byte extraction of the orderbook_delta WS parse into _apply_orderbook_delta; no behavior change) | next:0006 (review CHANGES_REQUESTED→FIXED: round-vs-truncate test passed trivially on '0.96'; switched to '0.29' and PROVED it catches the regression via round→int mutation; over-claim tightened; filed 0006 for non-numeric WS field hardening)
```
