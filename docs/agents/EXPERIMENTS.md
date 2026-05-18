# EXPERIMENTS — how this scales to many agents

"Thousands of agents editing one trading runner" is chaos. The model that
actually scales here is a **hypothesis tournament behind frozen interfaces,
scored by one objective referee.**

## The model

The system has five pluggable seams (see `ARCHITECTURE.md`). A scalable unit
of agent work is: *propose one competing implementation behind one seam,
self-contained, and let the promotion gate decide if it wins.*

- N agents each work a different hypothesis (a calibration variant, a nowcast
  decay model, a different blend weight, an exit-margin rule). They never
  touch each other's files — different seams / different variant modules.
- `kaiju/eval/gate.py` is the referee: real CRPS vs a uniform-climatology
  baseline + PIT KS uniformity + net-of-fee PnL over the paired
  prediction/settlement window. It is fail-closed and is itself an invariant
  (A8) — agents may not edit it to make a variant look good.
- Only a variant that **beats the incumbent on the gate** *and* **breaks no
  invariant** is promoted to default. The incumbent stays default until then.

The number of *useful* parallel agents ≈ the number of independent,
gate-evaluable hypotheses you can pose. It is not unbounded — calendar time
(the paper-proof window) and the single trading account are hard ceilings
that no number of agents shortens.

## The seams and their interface contracts

A variant MUST keep the seam's signature and types unchanged.

| Seam | Interface (do not change the signature) |
|---|---|
| `model/distribution` | `pmf_from_nbm_percentiles(nbm_pct: dict[float,float]) -> TempPMF`; `blend_pmfs(parts: list[tuple[TempPMF, float]]) -> TempPMF` |
| `model/calibration` | `fit_calibration(fc_medians: list[float], realized: list[float], min_samples: int) -> CalibrationParams`; `apply_calibration(pmf: TempPMF, cal: CalibrationParams) -> TempPMF` |
| `model/nowcast` | `nowcast_pmf(base: TempPMF, observed_max_f: int, minutes_past_peak: int, remaining_forecast_max_f: int|None) -> TempPMF` |
| `strategy/edge` | `select_gap_trades(fair_cents, quotes, positions, net_edge_threshold, min_open_interest) -> list[TradeIntent]` |
| `strategy/exit_policy` | `decide_exit(position, fair_cents, quote, minutes_to_timestop, exit_margin_cents, fill_margin_cents) -> ExitDecision` |

## Rules for an experiment

1. **Add, don't replace in place.** New implementation in its own module
   (e.g. `model/nowcast_variants/decay_v2.py`), selectable — never edit the
   incumbent's body to "try something."
2. **Signature frozen.** Same inputs/outputs/types. If you think the interface
   must change, that is a design escalation, not an experiment.
3. **TDD.** The variant ships with its own unit tests; `make check` green.
4. **Scored, not asserted.** Superiority is decided by `eval/gate` on real
   paired data, not by your judgement. A variant that doesn't beat the
   incumbent is a *successful* experiment with a negative result — record it
   in the ledger so no one re-runs it.
5. **No invariant weakened.** Especially A8 (gate integrity) and B-series
   (correctness). Touching `eval/gate.py` to favor a variant is the single
   most dangerous possible action — it is a danger zone, human-only.

## Status of the selection mechanism (be honest)

Today `runner.py` calls the incumbents directly; there is no variant
registry yet. Until one exists, an experiment is evaluated by running the
gate on its branch vs `main` over the same data. **Backlog task
`0001-variant-registry`** adds a thin per-seam registry (default = current
incumbent, env/config-selectable) so experiments become first-class. That
infra task is the prerequisite for the tournament running at scale.
