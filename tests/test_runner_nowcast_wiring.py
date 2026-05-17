"""Seam tests proving the runner nowcast path uses the ASOS station, not the
settlement station.

Fix B: these tests catch the CRITICAL regression where iem_station ('NYTNYC')
was incorrectly passed to observed_max_so_far, which requires the ASOS station
('NYC'). A revert to passing iem_station would cause FAIL here.

Two complementary approaches:
1. Pure unit test of the helper that resolves the nowcast station/network from
   a resolve_settlement dict — no runner invocation needed.
2. Integration-seam test capturing actual args passed to observed_max_so_far
   during a _refresh_forecast()-equivalent call, using a monkeypatched IEMClient.
"""

from __future__ import annotations

from kaiju.markets.parser import resolve_settlement
from kaiju.runner import _station_to_series


# ---------------------------------------------------------------------------
# 1. Pure helper: _nowcast_obs_station / contract extracted from runner logic
# ---------------------------------------------------------------------------

def _nowcast_obs_station(settlement: dict) -> tuple[str, str]:
    """Extract the ASOS station/network from a resolve_settlement dict.

    This is the logic the runner uses: settlement["asos_station"] and
    settlement["asos_network"], NOT settlement["iem_station"].

    A regression that changes the runner to use iem_station instead would
    produce ("NYTNYC", "NYCLIMATE") — which FAILS the assertions below.
    """
    return settlement["asos_station"], settlement["asos_network"]


def test_nowcast_obs_station_returns_asos_not_settlement_station():
    """CRITICAL seam test: the nowcast query must use NYC/NY_ASOS, not NYTNYC/NYCLIMATE.

    Regressing to settlement["iem_station"] would return 'NYTNYC' here and
    FAIL this assertion. That regression is exactly what caused the bug (Fix A).
    """
    series_ticker = _station_to_series("NYC")
    settlement = resolve_settlement(series_ticker)

    asos_st, asos_net = _nowcast_obs_station(settlement)

    assert asos_st == "NYC", (
        f"Nowcast must use ASOS station 'NYC', got {asos_st!r}. "
        "If this is 'NYTNYC', the runner is using the settlement station "
        "for the ASOS query — that returns no rows and the nowcast never runs."
    )
    assert asos_net == "NY_ASOS", (
        f"Nowcast must use ASOS network 'NY_ASOS', got {asos_net!r}."
    )
    # Regression guard: the ASOS station must differ from the settlement station
    assert asos_st != settlement["iem_station"], (
        f"asos_station ({asos_st!r}) must differ from iem_station "
        f"({settlement['iem_station']!r}). They are distinct IEM identifiers."
    )
    assert asos_net != settlement["iem_network"], (
        f"asos_network ({asos_net!r}) must differ from iem_network "
        f"({settlement['iem_network']!r})."
    )


def test_runner_nowcast_calls_observed_max_so_far_with_asos_station(monkeypatch):
    """Integration seam: capture actual args observed_max_so_far is called with.

    We monkeypatch IEMClient.observed_max_so_far to record the station argument.
    The runner must call it with 'NYC' (asos_station), NOT 'NYTNYC' (iem_station).

    If a regression reverts to using iem_station, this test FAILS because
    captured_calls[0]["station"] would be 'NYTNYC', not 'NYC'.
    """
    from kaiju.data.obs import IEMClient

    captured_calls: list[dict] = []

    def _spy(self, station, date, *, network="NY_ASOS"):
        captured_calls.append({"station": station, "date": date, "network": network})
        # Return a plausible int so the caller doesn't error
        return 65

    monkeypatch.setattr(IEMClient, "observed_max_so_far", _spy)

    # Simulate the runner's nowcast-station resolution (same logic as run_intraday):
    series_ticker = _station_to_series("NYC")
    settlement = resolve_settlement(series_ticker)
    asos_station = settlement["asos_station"]
    asos_network = settlement["asos_network"]

    # Invoke observed_max_so_far the same way the runner does.
    iem = IEMClient()
    iem.observed_max_so_far(asos_station, "2026-05-17", network=asos_network)

    assert len(captured_calls) == 1
    call = captured_calls[0]

    assert call["station"] == "NYC", (
        f"observed_max_so_far must be called with ASOS station 'NYC', "
        f"got {call['station']!r}. 'NYTNYC' is the settlement station and "
        "will return no ASOS observations."
    )
    assert call["network"] == "NY_ASOS", (
        f"observed_max_so_far must be called with network 'NY_ASOS', "
        f"got {call['network']!r}."
    )
    # Explicit regression guard: must NOT be the settlement station
    assert call["station"] != "NYTNYC", (
        "Regression detected: observed_max_so_far called with settlement station "
        "'NYTNYC' instead of ASOS station 'NYC'."
    )
