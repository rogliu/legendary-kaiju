"""Event/bucket parser for Kalshi weather temperature markets.

Recorded contract references:
  docs/superpowers/notes/kalshi-api-contract.md  — field names for Market object
  docs/superpowers/notes/settlement-map.md       — IEM station / network / tz mapping

## Integer-band rule (HAZARD 1 — *.5 strikes)

Kalshi half-degree bucket strikes produce the inclusive integer band:

    lower_f = ceil(floor_strike)    [open low tail: None]
    upper_f = floor(cap_strike)     [open high tail: None]

Examples:
    floor_strike=68.5, cap_strike=69.5  ->  lower_f=69, upper_f=69
    floor_strike=69.5, cap_strike=70.5  ->  lower_f=70, upper_f=70

Adjacent buckets (sharing a *.5 boundary) therefore cover consecutive
disjoint integers and NEVER share an integer degree. This prevents
double-counting in kaiju/strategy/edge.py::bucket_probabilities().

## OI/volume source rule (HAZARD 2)

MarketQuote.open_interest and .volume are populated from each market
object's open_interest_fp / volume_fp fields (recorded: FixedPointCount
strings, e.g. "300.00").  The orderbook endpoint (used by
KalshiClient.get_quote) always returns OI/volume = 0 and MUST NOT be
used as the source.  Tasks 15 and 17 must rely on the EventSnapshot
produced here, not on individual get_quote() calls, for liquidity data.

## Recorded field names (kalshi-api-contract.md §3.4)

    Strike fields:   floor_strike (float|None), cap_strike (float|None)
    Quote fields:    yes_bid_dollars, yes_ask_dollars, no_bid_dollars, no_ask_dollars
    Liquidity:       volume_fp, open_interest_fp   (FixedPointCount strings)
    Rules:           rules_primary                 (settlement description, not parsed here)
"""

from __future__ import annotations

import math
from typing import Optional

from kaiju.types import Bucket, EventSnapshot, MarketQuote


# ---------------------------------------------------------------------------
# Settlement map
# ---------------------------------------------------------------------------

# Settlement map sourced from docs/superpowers/notes/settlement-map.md.
# Only KXHIGHNY is fully verified (IEM cross-check performed 2026-05-14).
# KXHIGHCHI / KXHIGHLAX: rules_primary verified but IEM station IDs are
# UNVERIFIED — do NOT add them here until the cross-check is complete.
_SETTLEMENT_MAP: dict[str, dict[str, str]] = {
    "KXHIGHNY": {
        "station_human": "Central Park, New York",
        # Settlement daily-max identifiers (IEM NYCLIMATE archive, final NWS CLI value):
        "iem_station": "NYTNYC",
        "iem_network": "NYCLIMATE",
        # Intraday ASOS identifiers (IEM obhistory.json, NY_ASOS sub-hourly obs):
        # HAZARD: these are DIFFERENT IEM identifiers for the same physical site.
        # Settlement must use NYTNYC/NYCLIMATE; nowcast MUST use NYC/NY_ASOS.
        # See docs/superpowers/notes/settlement-map.md §IEM intraday ASOS — ASOS station
        # section, which explicitly flags this two-identifier hazard for Central Park.
        "asos_station": "NYC",
        "asos_network": "NY_ASOS",
        "tz": "America/New_York",
    },
}


def resolve_settlement(series_ticker: str) -> dict[str, str]:
    """Return settlement metadata for a Kalshi series ticker.

    Keys returned: station_human, iem_station, iem_network, asos_station, asos_network, tz.

    Two distinct IEM identifier pairs are provided for the same physical site:
      - Settlement daily-max uses iem_station/iem_network (e.g. NYTNYC/NYCLIMATE).
        Call IEMClient.official_daily_max(iem_station, iem_network, date).
      - Intraday nowcast ASOS uses asos_station/asos_network (e.g. NYC/NY_ASOS).
        Call IEMClient.observed_max_so_far(asos_station, date) with network=asos_network.
    HAZARD (settlement-map.md §6): the NWS CLI issuedby code 'NYC' and the ASOS station
    'NYC' are the same string but DIFFERENT from the NYCLIMATE station 'NYTNYC'. Do not
    pass the settlement iem_station to the ASOS nowcast query — it will return no rows.

    Raises KeyError with a clear message for unmapped series.
    Does NOT guess — only hard-verified entries are in the map.
    """
    if series_ticker not in _SETTLEMENT_MAP:
        raise KeyError(
            f"Series ticker {series_ticker!r} is not in the settlement map. "
            "Add it only after verifying the IEM station ID against a settled "
            "Kalshi expiration_value (see docs/superpowers/notes/settlement-map.md)."
        )
    return dict(_SETTLEMENT_MAP[series_ticker])


# ---------------------------------------------------------------------------
# Integer-band conversion helpers
# ---------------------------------------------------------------------------

def _lower_int(floor_strike: float) -> int:
    """Convert a Kalshi floor_strike to the inclusive integer lower bound.

    Integer-band rule: lower = ceil(floor_strike).
    For *.5 values: ceil(68.5)=69, ceil(69.5)=70, etc.
    For exact integer strikes: ceil(70.0)=70.
    """
    return math.ceil(floor_strike)


def _upper_int(cap_strike: float) -> int:
    """Convert a Kalshi cap_strike to the inclusive integer upper bound.

    Integer-band rule: upper = floor(cap_strike).
    For *.5 values: floor(69.5)=69, floor(70.5)=70, etc.
    For exact integer strikes: floor(70.0)=70.
    """
    return math.floor(cap_strike)


# ---------------------------------------------------------------------------
# Dollar string → cents int
# ---------------------------------------------------------------------------

def _dollars_to_cents(s: str, field: str) -> int:
    """Parse a FixedPointDollars string to integer cents.

    Raises ValueError with the field name if the string is non-numeric.
    """
    try:
        return round(float(s) * 100)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"Non-numeric value {s!r} in field {field!r}"
        ) from exc


def _parse_fp_count(s: str, field: str) -> int:
    """Parse a FixedPointCount string (e.g. '300.00') to an integer.

    Raises ValueError with the field name if the string is non-numeric.
    """
    try:
        return int(float(s))
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"Non-numeric value {s!r} in field {field!r}"
        ) from exc


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_event_snapshot(
    event_ticker: str,
    station_id: str,
    climate_date: str,
    raw_markets: list[dict],
) -> EventSnapshot:
    """Parse a list of raw market dicts into an EventSnapshot.

    Recorded field names used (kalshi-api-contract.md §3.4):
      - ticker            : str (required)
      - floor_strike      : float | None
      - cap_strike        : float | None
      - yes_bid_dollars   : FixedPointDollars string
      - yes_ask_dollars   : FixedPointDollars string
      - no_bid_dollars    : FixedPointDollars string
      - no_ask_dollars    : FixedPointDollars string
      - volume_fp         : FixedPointCount string  (HAZARD 2 source)
      - open_interest_fp  : FixedPointCount string  (HAZARD 2 source)

    Dollar->cents uses round(float*100); for the standard 0.01-step (linear_cent) tier
    there are no exact half-cents. Sub-cent (tapered_deci_cent) extreme prices
    (e.g. 0.001-0.009) collapse to 0/100 cents; a resulting 0/100 ask is excluded
    downstream by select_trades' 1<=price<=99 guard.

    Absent `volume_fp`/`open_interest_fp` keys default to 0 (conservative:
    select_trades skips low-OI markets) — distinct from a present null which raises.

    Raises:
      KeyError  — if 'ticker' is missing from a market dict
      ValueError — if both floor_strike and cap_strike are None (degenerate)
      ValueError — if lower_f > upper_f after *.5->int conversion (inverted band)
      ValueError — if any numeric field is non-parseable
    """
    buckets: list[Bucket] = []
    quotes: dict[str, MarketQuote] = {}

    for mkt in raw_markets:
        # --- ticker (required) ---
        if "ticker" not in mkt:
            raise KeyError(
                f"Market dict missing required 'ticker' field: {mkt!r}"
            )
        ticker: str = mkt["ticker"]

        # --- strike → integer bounds (HAZARD 1) ---
        raw_floor = mkt.get("floor_strike")
        raw_cap = mkt.get("cap_strike")

        if raw_floor is None and raw_cap is None:
            raise ValueError(
                f"Market {ticker!r}: both floor_strike and cap_strike are None. "
                "Cannot determine bucket bounds — this is a degenerate entry."
            )

        lower_f: Optional[int]
        upper_f: Optional[int]

        if raw_floor is None:
            # Open low tail: no lower bound
            lower_f = None
        else:
            lower_f = _lower_int(float(raw_floor))

        if raw_cap is None:
            # Open high tail: no upper bound
            upper_f = None
        else:
            upper_f = _upper_int(float(raw_cap))

        if lower_f is not None and upper_f is not None and lower_f > upper_f:
            raise ValueError(
                f"Market {ticker!r}: inverted integer band after *.5->int conversion "
                f"(lower_f={lower_f} > upper_f={upper_f}; floor_strike={raw_floor!r}, "
                f"cap_strike={raw_cap!r}). Only well-formed brackets with "
                f"floor_strike < cap_strike are supported."
            )

        bucket = Bucket(
            market_ticker=ticker,
            lower_f=float(lower_f) if lower_f is not None else None,
            upper_f=float(upper_f) if upper_f is not None else None,
        )
        buckets.append(bucket)

        # --- dollar strings → cents ints ---
        def _opt_cents(key: str) -> Optional[int]:
            val = mkt.get(key)
            if val is None:
                return None
            return _dollars_to_cents(str(val), key)

        yes_bid = _opt_cents("yes_bid_dollars")
        yes_ask = _opt_cents("yes_ask_dollars")
        no_bid = _opt_cents("no_bid_dollars")
        no_ask = _opt_cents("no_ask_dollars")

        # --- liquidity from market object (HAZARD 2) ---
        # open_interest_fp / volume_fp must be read here, NOT from orderbook.
        # The orderbook endpoint always returns 0 for these fields.
        volume = _parse_fp_count(str(mkt.get("volume_fp", "0")), "volume_fp")
        open_interest = _parse_fp_count(
            str(mkt.get("open_interest_fp", "0")), "open_interest_fp"
        )

        quote = MarketQuote(
            market_ticker=ticker,
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            no_bid=no_bid,
            no_ask=no_ask,
            volume=volume,
            open_interest=open_interest,
        )
        quotes[ticker] = quote

    return EventSnapshot(
        event_ticker=event_ticker,
        station_id=station_id,
        climate_date=climate_date,
        buckets=buckets,
        quotes=quotes,
    )
