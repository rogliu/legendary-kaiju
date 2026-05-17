"""IEM observation client.

Provides two methods:
  - official_daily_max: final NWS CLI daily max from NYCLIMATE archive
  - observed_max_so_far: intraday running max from ASOS sub-hourly observations

Both methods return int (rounded °F) and raise LookupError if no valid data is found.
"""

import httpx

_DAILY_BASE_URL = "https://mesonet.agron.iastate.edu/api/1/daily.json"
_ASOS_BASE_URL = "https://mesonet.agron.iastate.edu/api/1/obhistory.json"

_TIMEOUT = 20.0


class IEMClient:
    """Client for IEM (Iowa Environmental Mesonet) weather observation data."""

    def official_daily_max(self, station: str, network: str, date: str) -> int:
        """Return the official NWS CLI daily maximum temperature in °F for the given date.

        Queries the IEM daily climate archive (NYCLIMATE network for NYC).

        Args:
            station: IEM station identifier, e.g. "NYTNYC".
            network: IEM network identifier, e.g. "NYCLIMATE".
            date: Calendar date in "YYYY-MM-DD" format (local station time).

        Returns:
            Official daily maximum temperature as an integer °F.

        Raises:
            LookupError: If no row exists for the date, or max_tmpf is null, or
                         tmpf_est=True (value is preliminary, not the final CLI report).
        """
        with httpx.Client(timeout=_TIMEOUT) as client:
            response = client.get(
                _DAILY_BASE_URL,
                params={"station": station, "network": network, "date": date},
            )
            response.raise_for_status()

        data = response.json().get("data", [])
        for row in data:
            if row.get("date") == date:
                max_tmpf = row.get("max_tmpf")
                if max_tmpf is None:
                    raise LookupError(
                        f"max_tmpf is null for station={station} date={date}"
                    )
                if row.get("tmpf_est") is True:
                    raise LookupError(
                        f"max_tmpf is preliminary (tmpf_est=True) for station={station} date={date}; "
                        "final CLI report not yet available"
                    )
                return int(round(max_tmpf))

        raise LookupError(f"No daily data row found for station={station} date={date}")

    def observed_max_so_far(self, station: str, date: str) -> int:
        """Return the running maximum of intraday ASOS tmpf observations for the given date.

        Queries the IEM ASOS observation history endpoint (NY_ASOS network for NYC).
        Skips null / non-numeric tmpf values.

        Args:
            station: ASOS station identifier, e.g. "NYC" for Central Park.
            date: Calendar date in "YYYY-MM-DD" format (local station time).

        Returns:
            Running maximum observed temperature as an integer °F.

        Raises:
            LookupError: If no valid (non-null, numeric) tmpf observations exist.
        """
        with httpx.Client(timeout=_TIMEOUT) as client:
            response = client.get(
                _ASOS_BASE_URL,
                params={"station": station, "network": "NY_ASOS", "date": date},
            )
            response.raise_for_status()

        obs = response.json().get("data", [])
        valid = [
            o["tmpf"]
            for o in obs
            if isinstance(o.get("tmpf"), (int, float))
        ]

        if not valid:
            raise LookupError(
                f"No valid tmpf observations for station={station} date={date}"
            )

        return int(round(max(valid)))
