"""Herbie forecast fetcher: NBM probabilistic (nbmqmd) and GEFS ensemble.

Pure parsers (stdlib json only — no herbie/eccodes at import time):
  nbm_percentiles_from_fixture(path) -> dict[float, float]
  gefs_members_from_fixture(path)    -> list[float]

Live fetchers (herbie/cfgrib imported INSIDE functions to avoid breaking offline tests/mypy):
  fetch_nbm_percentiles(lat, lon, run, fxx=30) -> dict[float, float]
  fetch_gefs_members(lat, lon, run)             -> list[float]

Cross-task contract (used by runner Task 17):
  nbm_percentiles_from_fixture(path: str) -> dict[float, float]
  gefs_members_from_fixture(path: str)    -> list[float]
  fetch_nbm_percentiles(lat: float, lon: float, run: datetime, fxx: int = 30) -> dict[float, float]
  fetch_gefs_members(lat: float, lon: float, run: datetime) -> list[float]

Note: lon MUST be in [0,360] (0-360 grid; pass lon+360 for western longitudes).
"""

from __future__ import annotations

import json
from datetime import datetime

# Percentile levels available in NBM qmd 12-30h max fcst window
NBM_PERCENTILES: list[int] = list(range(0, 101, 5))

# Station constants (KNYC = New York Central Park)
_KNYC_LAT = 40.7790
_KNYC_LON_360 = 286.0307  # = 360 + (-73.9693)


def _k_to_f(k: float) -> float:
    """Convert Kelvin to Fahrenheit."""
    return (k - 273.15) * 9 / 5 + 32


# ---------------------------------------------------------------------------
# Pure parsers (offline-safe, stdlib only)
# ---------------------------------------------------------------------------


def nbm_percentiles_from_fixture(path: str) -> dict[float, float]:
    """Load NBM percentile fixture JSON and return {float(percentile): float(°F)}.

    Fixture shape: {"0": 63.8, "5": 66.1, ..., "100": 74.6}
    """
    with open(path) as f:
        obj = json.load(f)
    return {float(k): float(v) for k, v in obj.items()}


def gefs_members_from_fixture(path: str) -> list[float]:
    """Load GEFS members fixture JSON and return list of member °F values.

    Fixture shape: {"members": [68.7, 68.9, ...]}
    """
    with open(path) as f:
        obj = json.load(f)
    return [float(x) for x in obj["members"]]


# ---------------------------------------------------------------------------
# Live fetchers (heavy imports deferred inside functions)
# ---------------------------------------------------------------------------


def fetch_nbm_percentiles(
    lat: float,
    lon: float,
    run: datetime,
    fxx: int = 30,
) -> dict[float, float]:
    """Fetch NBM qmd probabilistic daily-max temperature percentiles at (lat, lon).

    Uses Herbie model="nbmqmd", product="co", fxx=fxx, priority="aws".
    Search: ":TMP:2 m above ground:12-30 hour max fcst:{N}% level:"
    Grid extraction: scipy cKDTree nearest on curvilinear NBM grid.
    Units: Kelvin → °F.

    lon MUST be in [0,360] (0-360 grid; pass lon+360 for western longitudes).

    Returns:
        dict mapping float percentile (0..100, step 5) to float °F.
        Missing percentile levels are skipped (not fabricated).
        Raises RuntimeError if fewer than 15 levels are returned (likely a
        network/auth failure, not genuine sparsity).
    """
    if not (0.0 <= lon <= 360.0):
        raise ValueError(
            f"lon must be in [0,360] (0-360 grid convention); got {lon}. "
            f"For W longitudes pass lon+360 (e.g. KNYC -73.9693 -> 286.0307)."
        )

    import numpy as np
    from herbie import Herbie
    from scipy.spatial import cKDTree

    run_str = run.strftime("%Y-%m-%d %H:%M")
    H = Herbie(run_str, model="nbmqmd", product="co", fxx=fxx, priority="aws")

    results: dict[float, float] = {}
    # KDTree and nearest-point index are built once from the first successful level
    # and reused across all remaining levels (NBM grid is identical for all percentiles).
    tree: cKDTree | None = None
    iy_cached: int | None = None
    ix_cached: int | None = None
    grid_shape: tuple[int, ...] | None = None

    for pct in NBM_PERCENTILES:
        search = f":TMP:2 m above ground:12-30 hour max fcst:{pct}% level:"
        try:
            ds = H.xarray(search, remove_grib=True)
        except Exception:
            # Level unavailable — skip rather than fabricate
            continue

        var = list(ds.data_vars)[0]

        if tree is None:
            # Build tree once from the first successfully-fetched level
            lats = ds.latitude.values.ravel()
            lons = ds.longitude.values.ravel()
            tree = cKDTree(np.stack([lats, lons], axis=1))
            grid_shape = ds.latitude.shape
            _, idx = tree.query([lat, lon])
            iy_cached, ix_cached = np.unravel_index(idx, grid_shape)

        val_k = float(ds[var].values[iy_cached, ix_cached])
        results[float(pct)] = _k_to_f(val_k)

    if len(results) < 15:
        raise RuntimeError(
            f"fetch_nbm_percentiles: only {len(results)}/{len(NBM_PERCENTILES)} "
            f"percentile levels returned for run={run} fxx={fxx} — likely an S3/"
            f"availability/auth failure, not genuine sparsity; refusing to emit a "
            f"biased distribution."
        )

    return results


def fetch_gefs_members(
    lat: float,
    lon: float,
    run: datetime,
) -> list[float]:
    """Fetch GEFS per-member daily-max temperature at (lat, lon).

    Uses Herbie model="gefs", product="atmos.25", member=..., fxx in {18,24}.
    Search: ":TMAX:2 m above ground:"
    Daily max per member = max(TMAX@fxx18, TMAX@fxx24).
    Grid extraction: xarray .sel(method="nearest") on regular lat/lon grid.
    Units: Kelvin → °F.

    lon MUST be in [0,360] (0-360 grid; pass lon+360 for western longitudes).

    Returns:
        List of 31 float °F values, one per member [c00, p01, ..., p30].
    """
    if not (0.0 <= lon <= 360.0):
        raise ValueError(
            f"lon must be in [0,360] (0-360 grid convention); got {lon}. "
            f"For W longitudes pass lon+360 (e.g. KNYC -73.9693 -> 286.0307)."
        )

    from herbie import Herbie

    run_str = run.strftime("%Y-%m-%d %H:%M")
    members = ["c00"] + [f"p{i:02d}" for i in range(1, 31)]
    results: list[float] = []

    for member in members:
        tmax_vals: list[float] = []
        for fxx in [18, 24]:
            H = Herbie(
                run_str,
                model="gefs",
                product="atmos.25",
                member=member,
                fxx=fxx,
                priority="aws",
            )
            ds = H.xarray(":TMAX:2 m above ground:", remove_grib=True)
            var = list(ds.data_vars)[0]
            val_k = float(
                ds[var].sel(latitude=lat, longitude=lon, method="nearest").values
            )
            tmax_vals.append(val_k)
        results.append(_k_to_f(max(tmax_vals)))

    return results


# ---------------------------------------------------------------------------
# Manual smoke test (not run by pytest)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Smoke-test forecast fetchers")
    parser.add_argument(
        "--smoke",
        metavar="ICAO",
        default="KNYC",
        help="Station to test (currently only KNYC supported)",
    )
    args = parser.parse_args()

    # Use KNYC regardless of ICAO argument (only supported station for now)
    lat, lon = _KNYC_LAT, _KNYC_LON_360

    # Construct a recent 00Z run (yesterday at 00Z to ensure data is on S3)
    import datetime as dt

    yesterday = dt.datetime.utcnow().replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - dt.timedelta(days=1)
    run = yesterday

    print(f"Fetching NBM percentiles for {args.smoke} (lat={lat}, lon={lon})")
    print(f"  Run: {run.strftime('%Y-%m-%d %H:%M')} UTC")

    pct_map = fetch_nbm_percentiles(lat, lon, run)
    if pct_map:
        print("  Percentile -> °F:")
        for k in sorted(pct_map):
            print(f"    {int(k):3d}%: {pct_map[k]:.1f}°F")
    else:
        print("  No percentile data returned (S3 may be unreachable or data not yet available)")
