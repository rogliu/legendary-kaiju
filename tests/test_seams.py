"""Task 0001 — thin per-seam variant registry.

The hypothesis tournament (docs/agents/EXPERIMENTS.md) needs the five frozen
seams to be selectable behind a registry whose default is, byte-for-byte, the
current incumbent. These tests pin that contract: default == incumbent,
selectable by name/env, unknown -> fail loud (never a silent fallback).
"""
from __future__ import annotations

import pytest

# The five frozen seams and their interface callables (EXPERIMENTS.md).
EXPECTED_SEAMS: dict[str, tuple[str, ...]] = {
    "model/distribution": ("pmf_from_nbm_percentiles", "blend_pmfs"),
    "model/calibration": ("fit_calibration", "apply_calibration"),
    "model/nowcast": ("nowcast_pmf",),
    "strategy/edge": ("select_gap_trades",),
    "strategy/exit_policy": ("decide_exit",),
}


def _incumbents() -> dict[str, dict[str, object]]:
    from kaiju.model.calibration import apply_calibration, fit_calibration
    from kaiju.model.distribution import blend_pmfs, pmf_from_nbm_percentiles
    from kaiju.model.nowcast import nowcast_pmf
    from kaiju.strategy.edge import select_gap_trades
    from kaiju.strategy.exit_policy import decide_exit

    return {
        "model/distribution": {
            "pmf_from_nbm_percentiles": pmf_from_nbm_percentiles,
            "blend_pmfs": blend_pmfs,
        },
        "model/calibration": {
            "fit_calibration": fit_calibration,
            "apply_calibration": apply_calibration,
        },
        "model/nowcast": {"nowcast_pmf": nowcast_pmf},
        "strategy/edge": {"select_gap_trades": select_gap_trades},
        "strategy/exit_policy": {"decide_exit": decide_exit},
    }


def test_seam_names_are_exactly_the_five_frozen_seams() -> None:
    from kaiju.seams import SEAM_NAMES

    assert set(SEAM_NAMES) == set(EXPECTED_SEAMS)


def test_default_is_incumbent() -> None:
    """No override -> each seam resolves to the incumbent callable itself.

    Identity (`is`) is the strongest possible "byte-for-byte unchanged":
    the registry hands back the exact incumbent function object.
    """
    from kaiju.seams import resolve_seam

    inc = _incumbents()
    for seam, fn_names in EXPECTED_SEAMS.items():
        bundle = resolve_seam(seam)
        for fn in fn_names:
            assert getattr(bundle, fn) is inc[seam][fn], (seam, fn)


def test_explicit_incumbent_variant_selectable_by_name() -> None:
    from kaiju.seams import resolve_seam

    inc = _incumbents()
    assert (
        resolve_seam("model/nowcast", "incumbent").nowcast_pmf
        is inc["model/nowcast"]["nowcast_pmf"]
    )


def test_unknown_seam_fails_loud() -> None:
    from kaiju.seams import resolve_seam

    with pytest.raises((KeyError, ValueError)):
        resolve_seam("model/bogus")


def test_unknown_variant_fails_loud_not_silent_fallback() -> None:
    from kaiju.seams import resolve_seam

    with pytest.raises((KeyError, ValueError)):
        resolve_seam("model/nowcast", "does-not-exist")


def test_env_selects_variant_and_unknown_env_value_fails_loud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kaiju.seams import resolve_seam, seam_env_var

    var = seam_env_var("model/nowcast")
    inc = _incumbents()

    monkeypatch.setenv(var, "incumbent")
    assert resolve_seam("model/nowcast").nowcast_pmf is inc["model/nowcast"]["nowcast_pmf"]

    monkeypatch.setenv(var, "totally-unknown")
    with pytest.raises((KeyError, ValueError)):
        resolve_seam("model/nowcast")


def test_explicit_variant_argument_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kaiju.seams import resolve_seam, seam_env_var

    monkeypatch.setenv(seam_env_var("model/nowcast"), "totally-unknown")
    inc = _incumbents()
    # An explicit, valid variant must win over a bogus env value.
    assert (
        resolve_seam("model/nowcast", "incumbent").nowcast_pmf
        is inc["model/nowcast"]["nowcast_pmf"]
    )


def test_registered_callables_are_callable_with_seam_signatures() -> None:
    """Type-correctness is enforced by mypy in `make check`; at runtime we at
    least assert every registered seam member is callable."""
    from kaiju.seams import resolve_seam

    for seam, fn_names in EXPECTED_SEAMS.items():
        bundle = resolve_seam(seam)
        for fn in fn_names:
            assert callable(getattr(bundle, fn))


def test_runner_sources_all_seams_from_registry() -> None:
    """runner.py must resolve every seam through the registry instead of direct
    imports (task 0001). Pre-wiring the deferred-import callables are not module
    attributes and `resolve_seam` is absent, so this fails until runner is wired;
    identity then proves 'no behavior change when nothing is overridden'.
    """
    import kaiju.runner as runner
    import kaiju.seams as seams
    from kaiju.seams import resolve_seam

    assert runner.resolve_seam is seams.resolve_seam

    expected = {
        "pmf_from_nbm_percentiles": resolve_seam(
            "model/distribution"
        ).pmf_from_nbm_percentiles,
        "blend_pmfs": resolve_seam("model/distribution").blend_pmfs,
        "fit_calibration": resolve_seam("model/calibration").fit_calibration,
        "apply_calibration": resolve_seam("model/calibration").apply_calibration,
        "nowcast_pmf": resolve_seam("model/nowcast").nowcast_pmf,
        "select_gap_trades": resolve_seam("strategy/edge").select_gap_trades,
        "decide_exit": resolve_seam("strategy/exit_policy").decide_exit,
    }
    for name, fn in expected.items():
        assert getattr(runner, name) is fn, name
