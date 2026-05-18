"""Thin per-seam variant registry (backlog task 0001).

`docs/agents/EXPERIMENTS.md` defines a hypothesis tournament behind five frozen
seams. This module is the *selection mechanism*: each seam resolves to a typed
bundle of callables, and the default bundle **is** the current incumbent — the
same function objects, so behaviour is byte-for-byte unchanged when nothing is
overridden.

A variant is selectable per seam via an explicit argument or the
``KAIJU_SEAM_<SEAM>`` environment variable (explicit arg wins). An unknown seam
or an unknown variant raises ``ValueError`` — never a silent fallback, because a
silently-wrong model is exactly the failure this registry exists to prevent.

Adding an actual competing variant is intentionally out of scope here; this is
only the infrastructure that makes such experiments first-class (see
EXPERIMENTS.md → "Status of the selection mechanism").
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal, NamedTuple, Protocol, TypeVar, overload

from kaiju.model.calibration import CalibrationParams
from kaiju.model.calibration import apply_calibration as _apply_calibration
from kaiju.model.calibration import fit_calibration as _fit_calibration
from kaiju.model.distribution import blend_pmfs as _blend_pmfs
from kaiju.model.distribution import pmf_from_nbm_percentiles as _pmf_from_nbm_percentiles
from kaiju.model.nowcast import nowcast_pmf as _nowcast_pmf
from kaiju.strategy.edge import select_gap_trades as _select_gap_trades
from kaiju.strategy.exit_policy import decide_exit as _decide_exit
from kaiju.types import ExitDecision, MarketQuote, Position, TempPMF, TradeIntent

DEFAULT_VARIANT = "incumbent"

#: The five frozen seams (must equal the EXPERIMENTS.md table, in order).
SEAM_NAMES: tuple[str, ...] = (
    "model/distribution",
    "model/calibration",
    "model/nowcast",
    "strategy/edge",
    "strategy/exit_policy",
)


# --- Exact seam signatures (EXPERIMENTS.md). Call-Protocols keep both the
# parameter names and types, so existing keyword call sites still type-check. ---


class PmfFromNbmPercentiles(Protocol):
    def __call__(self, pct_to_temp: dict[float, float]) -> TempPMF: ...


class BlendPmfs(Protocol):
    def __call__(self, weighted: list[tuple[TempPMF, float]]) -> TempPMF: ...


class FitCalibration(Protocol):
    def __call__(
        self, fc_medians: list[float], realized: list[float], min_samples: int
    ) -> CalibrationParams: ...


class ApplyCalibration(Protocol):
    def __call__(self, pmf: TempPMF, cal: CalibrationParams) -> TempPMF: ...


class NowcastPmf(Protocol):
    def __call__(
        self,
        base: TempPMF,
        observed_max_f: int,
        minutes_past_peak: int,
        remaining_forecast_max_f: int | None,
    ) -> TempPMF: ...


class SelectGapTrades(Protocol):
    def __call__(
        self,
        fair_cents: dict[str, int],
        quotes: dict[str, MarketQuote],
        positions: dict[str, Position],
        net_edge_threshold: float,
        min_open_interest: int,
    ) -> list[TradeIntent]: ...


class DecideExit(Protocol):
    def __call__(
        self,
        position: Position,
        fair_cents: int,
        quote: MarketQuote,
        minutes_to_timestop: int,
        exit_margin_cents: int,
        fill_margin_cents: int,
    ) -> ExitDecision: ...


# --- Per-seam bundles: one immutable record of a seam's incumbent callables. ---


class DistributionSeam(NamedTuple):
    pmf_from_nbm_percentiles: PmfFromNbmPercentiles
    blend_pmfs: BlendPmfs


class CalibrationSeam(NamedTuple):
    fit_calibration: FitCalibration
    apply_calibration: ApplyCalibration


class NowcastSeam(NamedTuple):
    nowcast_pmf: NowcastPmf


class EdgeSeam(NamedTuple):
    select_gap_trades: SelectGapTrades


class ExitPolicySeam(NamedTuple):
    decide_exit: DecideExit


SeamBundle = (
    DistributionSeam | CalibrationSeam | NowcastSeam | EdgeSeam | ExitPolicySeam
)

# --- Registry: seam -> {variant -> bundle}. Default variant == incumbent. ---

_DISTRIBUTION: dict[str, DistributionSeam] = {
    DEFAULT_VARIANT: DistributionSeam(_pmf_from_nbm_percentiles, _blend_pmfs),
}
_CALIBRATION: dict[str, CalibrationSeam] = {
    DEFAULT_VARIANT: CalibrationSeam(_fit_calibration, _apply_calibration),
}
_NOWCAST: dict[str, NowcastSeam] = {
    DEFAULT_VARIANT: NowcastSeam(_nowcast_pmf),
}
_EDGE: dict[str, EdgeSeam] = {
    DEFAULT_VARIANT: EdgeSeam(_select_gap_trades),
}
_EXIT_POLICY: dict[str, ExitPolicySeam] = {
    DEFAULT_VARIANT: ExitPolicySeam(_decide_exit),
}


def seam_env_var(seam: str) -> str:
    """Environment variable that selects ``seam``'s variant.

    ``"model/distribution"`` -> ``"KAIJU_SEAM_MODEL_DISTRIBUTION"``.
    """
    if seam not in SEAM_NAMES:
        raise ValueError(f"unknown seam {seam!r}; known: {list(SEAM_NAMES)}")
    return "KAIJU_SEAM_" + seam.upper().replace("/", "_").replace("-", "_")


_B = TypeVar("_B", bound=tuple[object, ...])


def _pick(seam: str, table: Mapping[str, _B], variant: str | None) -> _B:
    chosen = (
        variant
        if variant is not None
        else os.environ.get(seam_env_var(seam), DEFAULT_VARIANT)
    )
    try:
        return table[chosen]
    except KeyError:
        raise ValueError(
            f"unknown variant {chosen!r} for seam {seam!r}; "
            f"known: {sorted(table)}"
        ) from None


@overload
def resolve_seam(
    seam: Literal["model/distribution"], variant: str | None = ...
) -> DistributionSeam: ...
@overload
def resolve_seam(
    seam: Literal["model/calibration"], variant: str | None = ...
) -> CalibrationSeam: ...
@overload
def resolve_seam(
    seam: Literal["model/nowcast"], variant: str | None = ...
) -> NowcastSeam: ...
@overload
def resolve_seam(
    seam: Literal["strategy/edge"], variant: str | None = ...
) -> EdgeSeam: ...
@overload
def resolve_seam(
    seam: Literal["strategy/exit_policy"], variant: str | None = ...
) -> ExitPolicySeam: ...
@overload
def resolve_seam(seam: str, variant: str | None = ...) -> SeamBundle: ...


def resolve_seam(seam: str, variant: str | None = None) -> SeamBundle:
    """Resolve ``seam`` to its variant bundle (default == incumbent).

    Variant precedence: explicit ``variant`` arg > ``KAIJU_SEAM_<SEAM>`` env >
    ``"incumbent"``. Unknown seam or unknown variant raises ``ValueError`` —
    never a silent fallback.
    """
    if seam == "model/distribution":
        return _pick(seam, _DISTRIBUTION, variant)
    if seam == "model/calibration":
        return _pick(seam, _CALIBRATION, variant)
    if seam == "model/nowcast":
        return _pick(seam, _NOWCAST, variant)
    if seam == "strategy/edge":
        return _pick(seam, _EDGE, variant)
    if seam == "strategy/exit_policy":
        return _pick(seam, _EXIT_POLICY, variant)
    raise ValueError(f"unknown seam {seam!r}; known: {list(SEAM_NAMES)}")
