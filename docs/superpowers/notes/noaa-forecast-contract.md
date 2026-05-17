# NOAA NBM + GEFS Herbie Contract

**Retrieval date:** 2026-05-16  
**Run verified:** 2026-05-15 00Z (model init 2026-05-15T00:00:00Z)  
**Station:** KNYC = New York Central Park, lat=40.7790, lon=-73.9693 (lon in 0-360 = 286.0307)  
**Herbie version:** 2026.3.0  
**Data source:** AWS S3 (NOMADS drops data after ~2 days; use `priority="aws"` in Herbie)

---

## 1. NBM Probabilistic Percentile TMAX

### Discovery finding: two separate NBM sub-products

There are two NBM products on S3:

| Sub-product | Herbie `model=` | S3 path segment | Contains |
|---|---|---|---|
| core | `"nbm"` | `.../core/blend.tHHz.core.fNNN.co.grib2` | Deterministic TMAX (12-hr windows, no percentiles) |
| qmd  | `"nbmqmd"` | `.../qmd/blend.tHHz.qmd.fNNN.co.grib2` | Calibrated percentile fields (TMP, APTMP, DPT, etc.) |

The `"co"` product (CONUS 13-km) is valid for KNYC.

### NBM qmd — probabilistic daily-max temperature

**Herbie constructor:**
```python
from herbie import Herbie
H = Herbie(
    "2026-05-15 00:00",   # model run datetime UTC
    model="nbmqmd",
    product="co",
    fxx=30,               # KEY: fxx=30 contains the 12-30 hour max fcst window
    priority="aws",       # NOMADS expires after ~2 days; use aws
)
```

**Search string for percentile TMAX:**
```
":TMP:2 m above ground:12-30 hour max fcst:{N}% level:"
```
where N ∈ {0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100}.

**Why fxx=30 and the 12-30h window:**

For a 00Z run, the 12-30 hour window = valid 12Z to 30Z (= 12Z to 06Z+1). In Eastern Daylight Time (UTC-4), 12Z = 8 AM EDT and 30Z = 2 AM EDT the next day. This fully covers the NWS climate-day high temperature window (afternoon peak through overnight).

The deterministic TMAX in `nbm` core at fxx=24 uses a narrower "12-24 hour max fcst" window (8 AM to 8 PM EDT) and has no percentiles.

**Percentile levels actually available:** 21 levels at 5-percentile intervals:
0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100

**Variable name in xarray:** `t2m` (may also appear as `mn2t` in some messages — always check `list(ds.data_vars)[0]`)

**Units:** Kelvin. Conversion to °F: `(K - 273.15) * 9/5 + 32`

**Full inventory row for the search target (from fxx=30 IDX):**
```
:TMP:2 m above ground:12-30 hour max fcst:50% level:
```

**Alternative: deterministic NBM TMAX (fallback / cross-check):**
```python
H = Herbie("2026-05-15 00:00", model="nbm", product="co", fxx=24, priority="aws")
search = ":TMAX:2 m above ground:12-24 hour max fcst:"
ds = H.xarray(search, remove_grib=True)
# ds.tmax in Kelvin
```
This gives a single deterministic value (mean blend), no percentiles.

---

## 2. GEFS Per-Member 2m Temperature (Daily Max)

### Herbie constructor:
```python
from herbie import Herbie

# Individual members: "c00" (control) + "p01".."p30" (30 perturbation members)
H = Herbie(
    "2026-05-15 00:00",
    model="gefs",
    product="atmos.25",    # 0.25-degree primary fields (~35 variables)
    member="p01",          # or "c00", "p02", ..., "p30"
    fxx=24,                # 18-24 hour TMAX window
    priority="aws",
)
```

**Search string:** `:TMAX:2 m above ground:` (matches per-member TMAX regardless of fxx)

**S3 URL pattern:**
```
https://noaa-gefs-pds.s3.amazonaws.com/gefs.YYYYMMDD/HH/atmos/pgrb2sp25/ge{member}.tHHz.pgrb2s.0p25.f0NN
```
Members: `geavg` (ensemble mean), `gec00` (control), `gep01`..`gep30`.

**TMAX windows per fxx:**
- fxx=18: "12-18 hour max fcst" (18Z = 2 PM EDT)
- fxx=24: "18-24 hour max fcst" (24Z = 8 PM EDT) — afternoon peak
- fxx=30: "24-30 hour max fcst" (30Z = 2 AM EDT+1)

**Recommended approach for daily-max:** fetch TMAX at fxx=18 AND fxx=24, take `max()` per member.

**Variable name in xarray:** `tmax` (from GRIB TMAX) — verify with `list(ds.data_vars)[0]`.

**Grid:** Regular lat/lon, 0.25°, 0-360° longitude. GEFS supports `ds[var].sel(latitude=lat, longitude=lon, method='nearest')` directly.

**Units:** Kelvin. Conversion: `(K - 273.15) * 9/5 + 32`

**Members exposed:** GEFS has 31 members total = 1 control (`c00`) + 30 perturbations (`p01`-`p30`). Each requires a separate Herbie call with `member=`.

---

## 3. Station Point Extraction

### NBM (curvilinear grid, y/x dims):

NBM is on a curvilinear Lambert Conformal grid. Longitude is in 0-360 range. Use scipy KDTree:

```python
import numpy as np
from scipy.spatial import cKDTree

KNYC_LAT = 40.7790
KNYC_LON_360 = 286.0307  # = 360 + (-73.9693)

# ds has dims (y, x), coords latitude(y,x) and longitude(y,x)
lats = ds.latitude.values.ravel()
lons = ds.longitude.values.ravel()
tree = cKDTree(np.stack([lats, lons], axis=1))
dist, idx = tree.query([KNYC_LAT, KNYC_LON_360])
iy, ix = np.unravel_index(idx, ds.latitude.shape)
val_K = float(ds[var].values[iy, ix])
val_F = (val_K - 273.15) * 9/5 + 32
```

Nearest grid point for KNYC: lat=40.7758, lon=286.0291, distance=0.0036°.

Note: `herbie.pick_points()` requires scikit-learn which is NOT in this project's deps. Do not use it.

### GEFS (regular lat/lon grid):

```python
KNYC_LAT = 40.7790
KNYC_LON_360 = 286.0307

val_K = float(ds[var].sel(latitude=KNYC_LAT, longitude=KNYC_LON_360, method='nearest').values)
val_F = (val_K - 273.15) * 9/5 + 32
```

---

## 4. Computing the Climate-Day Daily Maximum

### NBM approach:
The `nbmqmd` at fxx=30 provides `TMP:2 m above ground:12-30 hour max fcst` — this IS the native probabilistic daily-max temperature from NBM's calibration. No further aggregation needed. Each percentile level is a single spatial field.

### GEFS approach:
GEFS does not provide a single "24-hour max" field in one shot. Approach:
1. For each of the 31 members, fetch TMAX at fxx=18 (12-18h window) and fxx=24 (18-24h window).
2. Take `max(tmax_fxx18, tmax_fxx24)` per member — this captures the daily max.
3. Result: 31 floats in °F, one per member.

This is the approach used to produce the fixture `tests/fixtures/gefs_knyc.json`.

---

## 5. Fixture File Shapes

Both files are in `tests/fixtures/` and are the **exact** shapes consumed by Task 18's parser functions.

### `tests/fixtures/nbm_knyc.json`
```json
{
  "0": 63.8,
  "5": 66.1,
  "10": 66.8,
  ...
  "100": 74.6
}
```
- Keys: string percentile integers 0..100 in steps of 5 (21 levels total).
- Values: float °F.
- Guaranteed monotonic non-decreasing (verified).
- Parser: `nbm_percentiles_from_fixture(data)` → dict of `int → float`.
- Source: 2026-05-15 00Z, NBM qmd fxx=30, KNYC nearest grid point (lat=40.7758, lon=286.0291).

### `tests/fixtures/gefs_knyc.json`
```json
{
  "members": [68.7, 68.9, 67.2, ..., 68.6]
}
```
- One top-level key: `"members"`.
- Value: list of 31 floats in °F.
- Order: [c00, p01, p02, ..., p30].
- Parser: `gefs_members_from_fixture(data)` → `list[float]`.
- Source: 2026-05-15 00Z, GEFS atmos.25, max(TMAX at fxx=18, TMAX at fxx=24) per member.

---

## 6. Verified Inventory Excerpts

### NBM qmd fxx=30 — TMP max fcst rows (from S3 IDX):
```
236:...:TMP:2 m above ground:12-30 hour max fcst:prob <255.372:prob fcst 255/255:
...
243:...:TMP:2 m above ground:12-30 hour max fcst:0% level:
244:...:TMP:2 m above ground:12-30 hour max fcst:5% level:
...
263:...:TMP:2 m above ground:12-30 hour max fcst:100% level:
264:...:TMP:2 m above ground:12-30 hour max fcst:ens mean:
265:...:TMP:2 m above ground:12-30 hour max fcst:ens std dev:
```

### NBM core fxx=24 — TMAX row (deterministic):
```
70:...:TMAX:2 m above ground:12-24 hour max fcst:
71:...:TMAX:2 m above ground:12-24 hour max fcst:ens std dev
```

### GEFS p01 fxx=24 — TMP and TMAX rows:
```
:TMP:2 m above ground:24 hour fcst:ENS=+1:
:TMAX:2 m above ground:18-24 hour max fcst:ENS=+1:
```

---

## 7. UNVERIFIED / RISKS

1. **Data availability latency:** AWS S3 data for a given run appears available within ~1-2 hours of model completion. GEFS 00Z completes ~5-6 hours after init; NBM ~3 hours. Production code must handle the case where fxx=30 isn't yet on S3 when the bot runs (e.g., 06Z bot run trying to get 00Z+30h = 06Z NBM data). Consider falling back to fxx=24 or prior run.

2. **NOMADS vs AWS expiry:** NOMADS only retains ~2 days of data. Production code MUST use `priority="aws"` (which stores data for ~10 days based on S3 lifecycle policy). For backtesting, data older than ~10 days will not be on AWS either; offline fixtures cover that case.

3. **NBM fxx=30 not always present:** S3 listing showed fxx up to f159 (3-hourly gaps after f048). fxx=30 confirmed present for 2026-05-15. However, if a run is incomplete, fxx=30 may be missing before fxx=24. The implementation should verify existence or fall back to `nbm core fxx=24 + deterministic TMAX`.

4. **GEFS member count:** Current GEFS has 31 members (c00 + p01-p30). This has been stable but may change. Always verify `len(members)`.

5. **NBM percentile `0%` and `100%` reliability:** These are tail-of-distribution values and may be less calibrated than the 10th-90th percentile range. For fitting a distribution, consider clipping to 5-95 range.

6. **Apparent Temperature (APTMP) vs TMP:** The qmd product also contains `APTMP` (apparent/felt temperature) percentiles. We use `TMP` (dry-bulb 2m temperature), which is the NWS official daily-max predictand. Do not confuse with APTMP.

7. **fxx cycle for qmd "max" windows:** Only fxx=30 was confirmed to have the "12-30 hour max" window. fxx=18 has "0-18 hour min" (not max). Additional fxx values should be checked if multi-day forecasts are needed (fxx=54 likely has "36-54 hour max" for day 2, etc.).

8. **scikit-learn not installed:** `herbie.pick_points()` requires scikit-learn which is absent from this project. Use the cKDTree approach documented in Section 3 for NBM.

9. **Coordinate system:** NBM lon is 0-360. GEFS lon is also 0-360. Both confirmed.

---

## 8. Quick Reference: Herbie Call Patterns

```python
import datetime as dt
from herbie import Herbie
import numpy as np
from scipy.spatial import cKDTree

# KNYC constants
KNYC_LAT, KNYC_LON_360 = 40.7790, 286.0307

# --- NBM probabilistic TMAX percentiles ---
run = dt.datetime(2026, 5, 15, 0, 0)  # 00Z run
H_nbm = Herbie(run.strftime("%Y-%m-%d %H:%M"), model="nbmqmd", product="co",
               fxx=30, priority="aws")

results_nbm = {}
for pct in range(0, 101, 5):
    ds = H_nbm.xarray(f":TMP:2 m above ground:12-30 hour max fcst:{pct}% level:",
                      remove_grib=True)
    var = list(ds.data_vars)[0]
    lats = ds.latitude.values.ravel()
    lons = ds.longitude.values.ravel()
    tree = cKDTree(np.stack([lats, lons], axis=1))
    _, idx = tree.query([KNYC_LAT, KNYC_LON_360])
    iy, ix = np.unravel_index(idx, ds.latitude.shape)
    results_nbm[pct] = (float(ds[var].values[iy, ix]) - 273.15) * 9/5 + 32

# --- GEFS per-member daily-max ---
members = ['c00'] + [f'p{i:02d}' for i in range(1, 31)]
results_gefs = []
for member in members:
    tmax_vals = []
    for fxx in [18, 24]:
        H = Herbie(run.strftime("%Y-%m-%d %H:%M"), model="gefs", product="atmos.25",
                   member=member, fxx=fxx, priority="aws")
        ds = H.xarray(":TMAX:2 m above ground:", remove_grib=True)
        var = list(ds.data_vars)[0]
        val_K = float(ds[var].sel(latitude=KNYC_LAT, longitude=KNYC_LON_360,
                                   method='nearest').values)
        tmax_vals.append(val_K)
    results_gefs.append((max(tmax_vals) - 273.15) * 9/5 + 32)
```
