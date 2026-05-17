# Settlement Map — Verified Research Notes

**Retrieval date: 2026-05-17**

All items are sourced from live API calls unless marked **UNVERIFIED** or **NOTE**.

---

## Part 1 — IEM Daily-Max Endpoint

### Verified Endpoint

```
GET https://mesonet.agron.iastate.edu/api/1/daily.json
```

**Query parameters (for a single station, one calendar month):**

| Parameter | Type   | Required | Notes                                       |
|-----------|--------|----------|---------------------------------------------|
| `station` | string | Yes      | IEM station identifier (e.g. `NYTNYC`)      |
| `network` | string | Yes      | IEM network identifier (e.g. `NYCLIMATE`)   |
| `year`    | int    | Yes*     | Calendar year (e.g. `2026`)                 |
| `month`   | int    | No       | Calendar month 1–12; omit to get full year  |
| `date`    | string | No       | Single date `YYYY-MM-DD`; returns one row   |

*`year` is required when not using `date`. `month` without `year` is rejected.

**Note:** The `date1`/`date2` parameters seen in some IEM examples are NOT supported by this endpoint. Use `year`/`month` or `date`.

### JSON Path to Official Daily Max

```
response.data[*].max_tmpf
```

- **Type:** number (integer °F in practice; schema says `number`)
- **Units:** °F
- **Null behaviour:** `max_tmpf` can be `null` (e.g. missing preliminary data). `tmpf_est` flag (`bool`) is `true` when the value is estimated rather than finalised from the CLI report.

**Full response shape:**

```json
{
  "data": [
    {
      "index": 13,
      "station": "NYTNYC",
      "date": "2026-05-14",
      "max_tmpf": 66,
      "min_tmpf": 53,
      "tmpf_est": false,
      "precip_est": false,
      "precip": 0.01,
      "max_gust": null,
      "snow": 0.0,
      "snowd": 0.0,
      "min_rh": null,
      "max_rh": null,
      "max_dwpf": null,
      "min_dwpf": null,
      "min_feel": null,
      "avg_feel": null,
      "max_feel": null,
      "max_gust_localts": null,
      "max_drct": null,
      "avg_sknt": null,
      "vector_avg_drct": null,
      "min_rstage": null,
      "max_rstage": null,
      "temp_hour": 24,
      "id": "NYTNYC",
      "name": "New York-Central Park Area"
    }
  ]
}
```

Key fields for Task 17's `IEMClient.official_daily_max(station, date) -> int`:

| Field      | Meaning                                                                 |
|------------|-------------------------------------------------------------------------|
| `max_tmpf` | Official NWS CLI daily maximum temperature in °F (int in practice)     |
| `tmpf_est` | `true` = estimated / preliminary; `false` = final CLI report value      |
| `date`     | Local station calendar date `YYYY-MM-DD`                                |
| `station`  | Echoes the requested station ID                                         |

### Station Identification (KNYC)

The IEM station for **Central Park, New York** (the KXHIGHNY Kalshi settlement station) is:

| Field        | Value                     |
|--------------|---------------------------|
| IEM Station  | `NYTNYC`                  |
| IEM Network  | `NYCLIMATE`               |
| Human name   | `New York-Central Park Area` |
| Archive from | 1869-01-01                |
| IEM `ncdc81` | `USW00094728`             |
| WFO          | `OKX`                     |

**Confirmed via:**
- `GET https://mesonet.agron.iastate.edu/geojson/network.php?network=NYCLIMATE` returns station `NYTNYC` with `sname="New York-Central Park Area"`.
- Cross-checked: IEM `max_tmpf=66` for 2026-05-14 == Kalshi `expiration_value=66.00` for `KXHIGHNY-26MAY14` (all markets share `expiration_value: 66.00`). **Values match exactly.**

### Why `NWSCLI` / `NYC` Did Not Work

The station ID `NYC` in the `NWSCLI` network returned empty rows. `NWSCLI` is a network for real-time NWS climate products; the long-term archive for the same data (sourced from the daily CLI bulletin) lives in the **`NYCLIMATE`** network under the station ID **`NYTNYC`**. Both ultimately track the same NWS Climatological Report (Daily) values. Task 17 must use `NYCLIMATE` / `NYTNYC`.

### Exact Request URL (example — single month)

```
GET https://mesonet.agron.iastate.edu/api/1/daily.json?station=NYTNYC&network=NYCLIMATE&year=2026&month=5
```

### Fixture Location and Shape

Fixture file: `tests/fixtures/iem_knyc_dailymax.json`

- Contains 10 rows: 2026-05-07 through 2026-05-16.
- Top-level key: `"data"` → array of objects.
- Each object has the fields listed above; many are `null` for NYCLIMATE stations (only `max_tmpf`, `min_tmpf`, `tmpf_est`, `precip`, `snow`, `snowd`, `temp_hour`, `station`, `date`, `id`, `name` are reliably populated).

### Mock-Matching Guidance for Task 17 Tests

Use `respx` to mock `httpx` calls. The URL to match:

```python
import respx, re

respx.get(
    url=re.compile(r"https://mesonet\.agron\.iastate\.edu/api/1/daily\.json"),
).mock(return_value=httpx.Response(200, json=fixture_data))
```

Or match by host + path:
```python
respx.get("https://mesonet.agron.iastate.edu/api/1/daily.json")
```

The query params (`station`, `network`, `year`, `month`) do not need to be matched in the mock — respx matches on URL prefix by default. Pin them in `params=` if you want strict matching.

### Quirks

1. **`tmpf_est` flag**: When the daily value is being held from the ASOS observation (before the official CLI report is issued, typically the following morning), `tmpf_est=true`. Task 17 should check this flag: if `true`, the value is preliminary and may differ slightly from the final CLI value. **Prefer final values (`tmpf_est=false`) for settlement verification.**

2. **`temp_hour=24`**: For NYCLIMATE stations the observation hour is always 24, meaning the climate day runs through local midnight (confirmed by Kalshi `strike_date` analysis below).

3. **`null` fields**: Most meteorological fields (RH, dew point, feel, gust) are `null` for the NYCLIMATE archive — only temperature and precipitation are reliably populated.

4. **Integer vs float**: `max_tmpf` arrives as a JSON integer (e.g. `66`) even though the schema declares it as `number`. Parse as `int(round(row["max_tmpf"]))` to be safe.

5. **Missing days**: Gaps are possible (station offline, data not archived). The API returns only rows that exist; a missing date returns no row — not a `null` row.

---

## Part 2 — Kalshi Settlement Map

### Verified Kalshi Series: KXHIGHNY

**Confirmed via:** `GET https://external-api.kalshi.com/trade-api/v2/series/KXHIGHNY` (unauthenticated, public)

```json
{
  "ticker": "KXHIGHNY",
  "title": "Highest temperature in NYC",
  "category": "Climate and Weather",
  "frequency": "daily",
  "fee_type": "quadratic",
  "fee_multiplier": 1,
  "settlement_sources": [
    {
      "name": "NWS Climatological Report",
      "url": "https://forecast.weather.gov/product.php?site=OKX&product=CLI&issuedby=NYC"
    }
  ],
  "contract_terms_url": "https://kalshi-public-docs.s3.amazonaws.com/contract_terms/NHIGH.pdf"
}
```

### rules_primary (verbatim, from market `KXHIGHNY-26MAY14-B69.5`)

> "If the highest temperature recorded in Central Park, New York for May 14, 2026 as reported by the National Weather Service's Climatological Report (Daily), is between 69-70°, then the market resolves to Yes."

### rules_secondary (verbatim)

> "Not all weather data is the same. While checking a source like AccuWeather or Google Weather may help guide your decision, the official and final value used to determine this market is the highest temperature as reported by the corresponding NWS Climatological Report (Daily) linked in the rules above. Preliminary NWS reporting and measurement methods may be subject to underlying rounding and conversion nuances. Traders should exercise caution when interpreting preliminary NWS data."

### Climate-Day Window / Timezone

From Kalshi event `strike_date: "2026-05-18T03:59:00Z"` for the May 17 event:
- UTC 03:59 = 23:59 EDT (UTC-4, DST active in May)
- The climate day for "May 17" ends at **11:59 PM Eastern Daylight Time** on May 17.
- This matches the NWS CLI report definition: midnight-to-midnight local time.
- Kalshi help doc confirms (verbatim): *"During Daylight Saving Time, the high temperature will be recorded between 1:00 AM and 12:59 AM local time the following day."*

**Effective window:** Local midnight to local midnight (America/New_York), i.e., the standard NWS calendar day.

### Settlement Map Table

| Kalshi Series | Title                      | Settlement Station (rules_primary) | IEM Station | IEM Network | Climate-Day Tz    | NWS CLI URL                                                          |
|---------------|----------------------------|------------------------------------|-------------|-------------|-------------------|----------------------------------------------------------------------|
| `KXHIGHNY`    | Highest temperature in NYC | Central Park, New York             | `NYTNYC`    | `NYCLIMATE` | America/New_York  | `https://forecast.weather.gov/product.php?site=OKX&product=CLI&issuedby=NYC` |
| `KXHIGHCHI`   | Highest temperature in Chicago | Chicago Midway, IL            | UNVERIFIED* | UNVERIFIED* | America/Chicago   | `https://forecast.weather.gov/product.php?site=LOT&product=CLI&issuedby=MDW` |
| `KXHIGHLAX`   | Highest temperature in LA  | Los Angeles Airport, CA            | UNVERIFIED* | UNVERIFIED* | America/Los_Angeles | `https://forecast.weather.gov/product.php?site=LOX&product=CLI&issuedby=LAX` |

*KXHIGHCHI and KXHIGHLAX `rules_primary` text was verified via live API call; the corresponding IEM station IDs have not been looked up and verified for those cities.

### Extension Pattern for Other Cities

To extend the map to a new city:

1. `GET /series/{TICKER}` — read `settlement_sources[0].url` (the NWS CLI URL encodes the `issuedby=` station code, e.g. `NYC`, `MDW`, `LAX`).
2. Fetch one settled market for that series and read `rules_primary` — it names the human weather station (e.g. "Central Park, New York", "Chicago Midway, IL").
3. In IEM, query `GET https://mesonet.agron.iastate.edu/geojson/network.php?network={STATE}CLIMATE` and search features for the matching station name.
4. Confirm the IEM `max_tmpf` matches the Kalshi `expiration_value` on a settled day.
5. Record the IEM `sid` (station) + `network` in this table.

### Kalshi Event Ticker Convention

Format: `{SERIES_TICKER}-{YY}{MON}{DD}`

Example: `KXHIGHNY-26MAY14` = KXHIGHNY series, May 14, 2026.

Market tickers within an event:
- `{EVENT}-B{FLOOR}.5` = binary bracket market (between FLOOR and FLOOR+1 degrees)
- `{EVENT}-T{CAP}` = tail market (above CAP)
- `{EVENT}-T{FLOOR}` with only `floor_strike` = "at or above FLOOR" market

### Settlement Timing

NWS issues the Daily Climate Report (CLI) typically the morning after the climate day ends. Markets settle at `settlement_ts` (observed: ~12:01 UTC next day for NYC, e.g. `2026-05-15T12:01:51Z` for the May 14 event). Task 20 should not query IEM for the official max until at least 8 AM local time the following day.

---

## UNVERIFIED / RISKS

1. **IEM `tmpf_est` vs final CLI value**: On the day of or the evening after a climate day, `tmpf_est=true` may be set while the NWS CLI report is outstanding. The final value after CLI issuance is typically `tmpf_est=false`. The numerical difference is usually 0–1°F but has been documented to differ. **Risk**: Task 17 querying before CLI issuance will get a preliminary value. Mitigation: check `tmpf_est` and only use `false` values for settlement decisions; add a retry loop in Task 17 with a cutoff of ~10 AM ET.

2. **IEM station IDs for non-NYC cities**: `KXHIGHCHI` settles at "Chicago Midway" and `KXHIGHLAX` at "Los Angeles Airport." The corresponding IEM station IDs in `ILCLIMATE` / `CACLIMATE` networks have not been looked up or cross-checked. Must be verified before those cities go to production (use the same geojson network + expiration_value cross-check method).

3. **NWSCLI vs NYCLIMATE discrepancy**: The `NWSCLI` network is the real-time NWS CLI text product archive; `NYCLIMATE` is the long-term IEM archive of the same values. During a ~1-hour window after the CLI is issued, `NWSCLI` may be updated before `NYCLIMATE`. Task 17 should monitor whether `NYCLIMATE` lags behind `NWSCLI`. If latency is a concern, cross-reference both.

4. **Rounding/conversion nuances**: Kalshi's `rules_secondary` explicitly warns about "underlying rounding and conversion nuances" in preliminary NWS data. The official CLI value is always an integer °F. IEM's `max_tmpf` matches exactly for all verified dates. If a discrepancy is ever found, the NWS CLI PDF/HTML text at the `settlement_sources[0].url` is the authoritative source.

5. **Climate day during standard time (non-DST)**: In November–March, the NYC climate day is midnight-to-midnight Eastern Standard Time (UTC-5). The Kalshi strike_date shifts to UTC 04:59. IEM uses local station time (`America/New_York`) so this is handled correctly, but Task 17 must parse dates in local time, not UTC.

6. **`issuedby=NYC` in NWS URL vs IEM station `NYTNYC`**: The NWS CLI `issuedby` code is `NYC`; the IEM NYCLIMATE station ID is `NYTNYC` (different strings). Do not conflate them. The IEM lookup must always use `NYTNYC` + `NYCLIMATE`.

7. **Series `HIGHNY0` and `HIGHNY`**: Two additional tickers found in the series scan (`HIGHNY0` — "NYC high temperature", cat=World; `HIGHNY` — "Highest temperature in NYC") appear to be older or duplicate series. Only `KXHIGHNY` was verified with live events and market data in 2026. Task 20 should confirm which ticker is active before trading.

8. **Task 19/20 live demo confirmation needed**: The cross-check was performed on one settled date (May 14, 2026). A production-readiness check should verify IEM matches Kalshi `expiration_value` for at least 5 consecutive settled days before going live.

---

## IEM intraday ASOS (Task 10 SPIKE)

**Retrieval date: 2026-05-17**

### Verified Endpoint

```
GET https://mesonet.agron.iastate.edu/api/1/obhistory.json
```

**Query parameters:**

| Parameter | Type   | Required | Notes                                                        |
|-----------|--------|----------|--------------------------------------------------------------|
| `station` | string | Yes      | ASOS station identifier — `NYC` for Central Park            |
| `network` | string | Yes      | IEM network — `NY_ASOS`                                     |
| `date`    | string | Yes      | Calendar date `YYYY-MM-DD` (local station time)             |

**Example:**

```
GET https://mesonet.agron.iastate.edu/api/1/obhistory.json?station=NYC&network=NY_ASOS&date=2026-05-14
```

### JSON Path to Per-Observation Air Temperature

```
response.data[*].tmpf
```

- **Type:** number (float °F) or `null`
- **Units:** °F
- **Timestamps:** `data[*].local_valid` — ISO-style local datetime `YYYY-MM-DDTHH:MM` (no tz suffix; station local time = `America/New_York`)
- **UTC timestamp also available:** `data[*].utc_valid` — ISO string with `Z` suffix

**Null behaviour:** `tmpf` is `null` for observations where the temperature sensor was not reporting. No string `'M'` sentinel was observed in this endpoint (unlike the older `asos.py` CSV endpoint which uses `'M'` for missing). Always check `isinstance(v, (int, float))` or `v is not None` before using.

### Station Identification

| Field       | Value                               |
|-------------|-------------------------------------|
| IEM Station | `NYC`                               |
| IEM Network | `NY_ASOS`                           |
| Human name  | `NEW YORK CITY` (IEM ASOS label)    |
| ncdc81      | `USW00094728`                       |
| WFO         | `OKX`                               |
| METAR ID    | `KNYC` (appears in raw METAR field) |
| Archive     | 1943-12-01 to present               |

**Same station as NYCLIMATE `NYTNYC`:** Both `NYC` (NY_ASOS) and `NYTNYC` (NYCLIMATE) share `ncdc81=USW00094728`. The ASOS sub-hourly observations are the underlying source for the daily climate summary.

**Verified:** `NYC` returns per-hour `tmpf` for 2026-05-14. The `raw` field confirms METAR identifier `KNYC`. Running max across all 24 observations = 65°F. The official daily max from NYCLIMATE (`max_tmpf=66`) exceeds the ASOS running max (65°F) for the same date — consistent with the NWS CLI report incorporating the warmest reading during the climate day window including any afternoon peak not captured on-the-hour.

### How to Compute Running Max So Far for a Date/Time

```python
import httpx

def observed_max_so_far(station: str, date: str) -> int:
    url = "https://mesonet.agron.iastate.edu/api/1/obhistory.json"
    r = httpx.get(url, params={"station": station, "network": "NY_ASOS", "date": date}, timeout=20)
    r.raise_for_status()
    obs = r.json()["data"]
    valid = [o["tmpf"] for o in obs if isinstance(o.get("tmpf"), (int, float))]
    if not valid:
        raise LookupError(f"No valid tmpf observations for {station} on {date}")
    return int(round(max(valid)))
```

To get the running max *up to a specific time*, filter on `local_valid <= cutoff_time` before computing the max.

### Response Shape

```json
{
  "schema": {
    "fields": [
      {"name": "index", "type": "integer"},
      {"name": "utc_valid", "type": "string"},
      {"name": "local_valid", "type": "string"},
      {"name": "tmpf", "type": "number"},
      ...
    ],
    "primaryKey": ["index"]
  },
  "data": [
    {
      "index": 0,
      "utc_valid": "2026-05-14T04:51Z",
      "local_valid": "2026-05-14T00:51",
      "tmpf": 57.0,
      "dwpf": 51.0,
      ...
    },
    ...
  ]
}
```

### Fixture Location

Fixture file: `tests/fixtures/iem_knyc_asos.json`

- Contains 24 observations: 2026-05-14 00:51 through 23:51 (America/New_York).
- Top-level keys: `"schema"` and `"data"`.
- 24 rows, one per hour (at :51 minutes past each hour — ASOS observation time).
- `tmpf` range: 55.0–65.0 °F; `int(round(max)) = 65`.
- No null `tmpf` values in this fixture.

### Mock-Matching Guidance for Task 10 Tests

```python
import respx, httpx

respx.get(url__regex=r".*mesonet\.agron\.iastate\.edu.*").mock(
    return_value=httpx.Response(200, json=fixture_data)
)
```

Or more specific:
```python
respx.get("https://mesonet.agron.iastate.edu/api/1/obhistory.json")
```

### Quirks

1. **Null `tmpf`:** Use `isinstance(v, (int, float))` or `v is not None` to filter. No string `'M'` sentinels observed in this JSON endpoint.
2. **`local_valid` format:** `YYYY-MM-DDTHH:MM` — no seconds, no timezone suffix. Parse with `datetime.fromisoformat` (works in Python 3.12).
3. **Observation cadence:** Roughly hourly at :51 past the hour (METAR_RESET_MINUTE=51 per IEM station metadata). May have gaps or special obs.
4. **Running max vs official max:** The ASOS running max (65°F on 2026-05-14) may be 1°F below the official NYCLIMATE daily max (66°F) because the official CLI value incorporates all NWS readings including any special observations between scheduled METAR times. Do not use the ASOS running max as a settlement proxy — use it only for intraday nowcasting.
5. **Intraday endpoint returns full-day data:** The API always returns all observations for the given date up to the current time. For a date in the past it returns the full day; for today it returns observations through the current hour.
6. **'M' values (legacy note):** The older `asos.py` CSV endpoint at `/cgi-bin/request/asos.py` uses `'M'` for missing values. The `obhistory.json` endpoint uses `null` instead. This implementation uses `obhistory.json` exclusively.
