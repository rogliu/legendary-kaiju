"""Tests for kaiju/markets/parser.py.

Verified field names from docs/superpowers/notes/kalshi-api-contract.md §3.4:
  Strike fields:  floor_strike (float|None), cap_strike (float|None)
  Quote fields:   yes_bid_dollars, yes_ask_dollars, no_bid_dollars, no_ask_dollars
  Liquidity:      volume_fp (FixedPointCount string), open_interest_fp (FixedPointCount string)

Integer-band rule (HAZARD 1):
  A bucket with floor_strike=f, cap_strike=c covers inclusive integer band [ceil(f), floor(c)].
  E.g. floor=68.5, cap=69.5 -> [69, 69]; floor=69.5, cap=70.5 -> [70, 70].
  Adjacent *.5 buckets never share an integer degree.

OI/volume source rule (HAZARD 2):
  MarketQuote.open_interest and .volume must be populated from the market object's
  open_interest_fp / volume_fp, NOT from the orderbook (which always returns 0).
"""

import pytest
from kaiju.markets.parser import parse_event_snapshot, resolve_settlement


def test_half_strikes_become_inclusive_integer_bounds_no_double_count():
    raw = [
        {
            "ticker": "B69",
            "floor_strike": 68.5,
            "cap_strike": 69.5,
            "yes_bid_dollars": "0.04",
            "yes_ask_dollars": "0.07",
            "no_bid_dollars": "0.93",
            "no_ask_dollars": "0.96",
            "volume_fp": "10",
            "open_interest_fp": "300",
        },
        {
            "ticker": "B70",
            "floor_strike": 69.5,
            "cap_strike": 70.5,
            "yes_bid_dollars": "0.40",
            "yes_ask_dollars": "0.45",
            "no_bid_dollars": "0.55",
            "no_ask_dollars": "0.60",
            "volume_fp": "50",
            "open_interest_fp": "900",
        },
        {
            "ticker": "LO",
            "floor_strike": None,
            "cap_strike": 49.5,
            "yes_bid_dollars": "0.01",
            "yes_ask_dollars": "0.03",
            "no_bid_dollars": "0.97",
            "no_ask_dollars": "0.99",
            "volume_fp": "5",
            "open_interest_fp": "150",
        },
        {
            "ticker": "HI",
            "floor_strike": 80.5,
            "cap_strike": None,
            "yes_bid_dollars": "0.01",
            "yes_ask_dollars": "0.03",
            "no_bid_dollars": "0.97",
            "no_ask_dollars": "0.99",
            "volume_fp": "5",
            "open_interest_fp": "120",
        },
    ]
    snap = parse_event_snapshot("E", "NYTNYC", "2026-05-17", raw)
    b = {x.market_ticker: x for x in snap.buckets}

    # Integer-band rule: floor_strike=68.5, cap_strike=69.5 -> [ceil(68.5), floor(69.5)] = [69, 69]
    assert (b["B69"].lower_f, b["B69"].upper_f) == (69, 69)
    # Adjacent bucket: floor_strike=69.5, cap_strike=70.5 -> [ceil(69.5), floor(70.5)] = [70, 70]
    # No shared integer with B69 (69 != 70) — HAZARD 1 enforced
    assert (b["B70"].lower_f, b["B70"].upper_f) == (70, 70)

    # Open low tail: floor_strike=None, cap_strike=49.5 -> lower_f=None, upper_f=floor(49.5)=49
    assert b["LO"].lower_f is None and b["LO"].upper_f == 49
    # Open high tail: floor_strike=80.5, cap_strike=None -> lower_f=ceil(80.5)=81, upper_f=None
    assert b["HI"].lower_f == 81 and b["HI"].upper_f is None

    # HAZARD 2: OI/volume come from market object, not from orderbook (which would be 0)
    q = snap.quotes["B70"]
    assert q.open_interest == 900 and q.volume == 50

    # Dollar strings -> cents int: "0.45" -> 45, "0.55" -> 55
    assert q.yes_ask == 45 and q.no_bid == 55

    # EventSnapshot fields are wired through correctly
    assert snap.event_ticker == "E"
    assert snap.station_id == "NYTNYC"
    assert snap.climate_date == "2026-05-17"


def test_adjacent_buckets_share_no_integer():
    """Explicit no-double-count proof: B69 upper bound < B70 lower bound."""
    raw = [
        {
            "ticker": "B69",
            "floor_strike": 68.5,
            "cap_strike": 69.5,
            "yes_bid_dollars": "0.04",
            "yes_ask_dollars": "0.07",
            "no_bid_dollars": "0.93",
            "no_ask_dollars": "0.96",
            "volume_fp": "10",
            "open_interest_fp": "300",
        },
        {
            "ticker": "B70",
            "floor_strike": 69.5,
            "cap_strike": 70.5,
            "yes_bid_dollars": "0.40",
            "yes_ask_dollars": "0.45",
            "no_bid_dollars": "0.55",
            "no_ask_dollars": "0.60",
            "volume_fp": "50",
            "open_interest_fp": "900",
        },
    ]
    snap = parse_event_snapshot("E2", "NYTNYC", "2026-05-17", raw)
    b = {x.market_ticker: x for x in snap.buckets}
    # B69 covers only 69; B70 covers only 70. They do NOT share the integer 69.
    assert b["B69"].upper_f is not None
    assert b["B70"].lower_f is not None
    # The critical assertion: no overlap
    assert b["B69"].upper_f < b["B70"].lower_f


def test_oi_and_volume_are_nonzero_from_market_object():
    """HAZARD 2: open_interest and volume must be non-zero when market obj has values."""
    raw = [
        {
            "ticker": "T1",
            "floor_strike": 70.5,
            "cap_strike": 71.5,
            "yes_bid_dollars": "0.50",
            "yes_ask_dollars": "0.52",
            "no_bid_dollars": "0.48",
            "no_ask_dollars": "0.50",
            "volume_fp": "200.00",
            "open_interest_fp": "500.00",
        }
    ]
    snap = parse_event_snapshot("EV", "NYTNYC", "2026-05-17", raw)
    q = snap.quotes["T1"]
    assert q.open_interest == 500
    assert q.volume == 200


def test_resolve_settlement_knyc():
    s = resolve_settlement("KXHIGHNY")
    assert s["iem_station"] == "NYTNYC" and s["iem_network"] == "NYCLIMATE"
    assert s["tz"] == "America/New_York"
    assert s["station_human"] == "Central Park, New York"


def test_resolve_settlement_unknown_raises():
    with pytest.raises((KeyError, ValueError)):
        resolve_settlement("KXUNKNOWN")


def test_parse_raises_on_missing_ticker():
    raw = [
        {
            "floor_strike": 70.5,
            "cap_strike": 71.5,
            "yes_bid_dollars": "0.50",
            "yes_ask_dollars": "0.52",
            "no_bid_dollars": "0.48",
            "no_ask_dollars": "0.50",
            "volume_fp": "10",
            "open_interest_fp": "100",
        }
    ]
    with pytest.raises((KeyError, ValueError)):
        parse_event_snapshot("E", "NYTNYC", "2026-05-17", raw)


def test_parse_raises_on_both_strikes_null():
    raw = [
        {
            "ticker": "BAD",
            "floor_strike": None,
            "cap_strike": None,
            "yes_bid_dollars": "0.50",
            "yes_ask_dollars": "0.52",
            "no_bid_dollars": "0.48",
            "no_ask_dollars": "0.50",
            "volume_fp": "10",
            "open_interest_fp": "100",
        }
    ]
    with pytest.raises(ValueError):
        parse_event_snapshot("E", "NYTNYC", "2026-05-17", raw)


def test_inverted_band_raises():
    raw = [{"ticker": "BAD", "floor_strike": 69.5, "cap_strike": 69.5,
            "yes_bid_dollars": "0.40", "yes_ask_dollars": "0.45", "no_bid_dollars": "0.55", "no_ask_dollars": "0.60",
            "volume_fp": "10", "open_interest_fp": "300"}]
    with pytest.raises(ValueError, match="inverted"):
        parse_event_snapshot("E", "NYTNYC", "2026-05-17", raw)


def test_contiguous_ladder_tiles_with_no_gap_no_overlap():
    # standard contiguous *.5 ladder: 67.5/68.5, 68.5/69.5, 69.5/70.5 -> (68,68),(69,69),(70,70)
    def m(t, f, c):
        return {"ticker": t, "floor_strike": f, "cap_strike": c,
                "yes_bid_dollars": "0.10", "yes_ask_dollars": "0.12", "no_bid_dollars": "0.88", "no_ask_dollars": "0.90",
                "volume_fp": "10", "open_interest_fp": "300"}
    raw = [m("A", 67.5, 68.5), m("B", 68.5, 69.5), m("C", 69.5, 70.5)]
    snap = parse_event_snapshot("E", "NYTNYC", "2026-05-17", raw)
    bands = sorted((b.lower_f, b.upper_f) for b in snap.buckets)
    assert bands == [(68, 68), (69, 69), (70, 70)]
    # no gap and no overlap between consecutive bands
    for (lo1, hi1), (lo2, lo2u) in zip(bands, bands[1:]):
        assert lo2 == hi1 + 1            # no gap, no shared integer


def test_single_bad_market_aborts_whole_snapshot():
    good = {"ticker": "G", "floor_strike": 68.5, "cap_strike": 69.5,
            "yes_bid_dollars": "0.40", "yes_ask_dollars": "0.45", "no_bid_dollars": "0.55", "no_ask_dollars": "0.60",
            "volume_fp": "10", "open_interest_fp": "300"}
    bad = {"floor_strike": 70.5, "cap_strike": 71.5,  # missing 'ticker'
           "yes_bid_dollars": "0.40", "yes_ask_dollars": "0.45", "no_bid_dollars": "0.55", "no_ask_dollars": "0.60",
           "volume_fp": "10", "open_interest_fp": "300"}
    with pytest.raises((KeyError, ValueError)):
        parse_event_snapshot("E", "NYTNYC", "2026-05-17", [good, bad])
