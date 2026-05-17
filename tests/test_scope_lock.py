"""SCOPE LOCK — executable single-market guardrail.

This test is a *rail*, not a description. An autonomous loop iterating on this
codebase is restrained by red tests, not by prose. The project is deliberately
scoped to ONE market — NYC daily-high (`KXHIGHNY`, Central Park, settled via
IEM `NYTNYC`/`NYCLIMATE`, nowcast via ASOS `NYC`/`NY_ASOS`). Multi-city
scale-out is explicitly out of scope until the single-city paper-proof
qualifies (see docs/superpowers/specs/2026-05-17-...-design.md §11).

Scope is enforced in code at THREE independent points. This test freezes all
three so a loop cannot silently widen any of them:

  1. kaiju.config.Settings.cities      — committed default trading scope
  2. kaiju.markets.parser._SETTLEMENT_MAP — verified-settlement allowlist
  3. kaiju.runner._station_to_series   — station -> Kalshi series map

DELIBERATE-UNLOCK RITUAL (humans only — never an autonomous loop):
To add a city you must (a) verify its IEM station against a settled Kalshi
expiration_value per docs/superpowers/notes/settlement-map.md, (b) add it to
all three points above, and (c) consciously edit the assertions in this file
in the SAME commit. Scope expansion is therefore always a reviewed, intentional
act — never drift. If this test is failing, scope changed; that is the alarm
working, not a flaky test to silence.
"""

from __future__ import annotations

import pytest

from kaiju.config import Settings
from kaiju.markets.parser import _SETTLEMENT_MAP, resolve_settlement
from kaiju.runner import _station_to_series

# The single locked market and its verified settlement identifiers.
# Sourced from docs/superpowers/notes/settlement-map.md (cross-checked
# 2026-05-14: IEM max_tmpf == Kalshi expiration_value for KXHIGHNY-26MAY14).
LOCKED_SERIES = "KXHIGHNY"
LOCKED_CITY = "KNYC"
LOCKED_SETTLEMENT = {
    "station_human": "Central Park, New York",
    "iem_station": "NYTNYC",      # settlement daily-max (NYCLIMATE archive)
    "iem_network": "NYCLIMATE",
    "asos_station": "NYC",        # intraday nowcast (NY_ASOS obhistory.json)
    "asos_network": "NY_ASOS",
    "tz": "America/New_York",
}


def test_config_default_scope_is_the_single_locked_city():
    """The committed default `cities` is exactly the one locked city.

    Asserted on the source field default (env-independent) so the rail pins
    the code, not a runtime env override.
    """
    default = Settings.model_fields["cities"].default
    assert default == [LOCKED_CITY], (
        f"Scope lock: Settings.cities default is {default!r}, expected "
        f"[{LOCKED_CITY!r}]. Widening default scope requires the deliberate "
        f"unlock ritual in this file's docstring."
    )


def test_settlement_allowlist_contains_only_the_locked_series():
    """resolve_settlement only knows the one verified NYC series."""
    assert set(_SETTLEMENT_MAP.keys()) == {LOCKED_SERIES}, (
        f"Scope lock: settlement map keys are {set(_SETTLEMENT_MAP)}, expected "
        f"{{{LOCKED_SERIES!r}}}. A new series may only be added after the IEM "
        f"cross-check and the deliberate unlock ritual."
    )


def test_locked_series_resolves_to_verified_identifiers():
    """The one allowed market still points at the verified IEM/ASOS station.

    Pins the settlement<->nowcast station seam (the bug class the final
    whole-branch review caught): settlement MUST use NYTNYC/NYCLIMATE and
    nowcast MUST use NYC/NY_ASOS — they are different identifiers for the
    same physical site and must never be conflated or repointed.
    """
    assert resolve_settlement(LOCKED_SERIES) == LOCKED_SETTLEMENT


def test_non_locked_series_cannot_resolve_settlement():
    """A non-NYC series fails loud (no guessing) — the hard allowlist gate."""
    with pytest.raises(KeyError):
        resolve_settlement("KXHIGHCHI")


def test_station_to_series_maps_only_the_locked_city():
    """runner._station_to_series resolves only NYC aliases; others fail loud."""
    assert _station_to_series("NYC") == LOCKED_SERIES
    assert _station_to_series("KNYC") == LOCKED_SERIES
    with pytest.raises(KeyError):
        _station_to_series("KORD")  # Chicago — out of scope, must raise
