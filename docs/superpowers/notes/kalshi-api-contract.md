# Kalshi API Contract — Verified Research Notes

**Retrieved: 2026-05-16**

All items are sourced from official Kalshi documentation unless marked **UNVERIFIED** or **THIRD-PARTY SOURCE**.

---

## 1. Base URLs

**Source:** https://docs.kalshi.com/getting_started/api_environments.md

### REST API

| Environment | Base URL |
|-------------|----------|
| Production  | `https://external-api.kalshi.com/trade-api/v2` |
| Demo        | `https://external-api.demo.kalshi.co/trade-api/v2` |

**Additional production URL observed in OpenAPI spec (elections subdomain — purpose unclear):**
`https://api.elections.kalshi.com/trade-api/v2` — UNVERIFIED: whether this is still active or election-market-specific.

### WebSocket API

| Environment | WebSocket URL |
|-------------|---------------|
| Production  | `wss://external-api-ws.kalshi.com/trade-api/ws/v2` |
| Demo        | `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` |

> From docs: "credentials are not shared between environments, so demo API keys only work against demo endpoints and production API keys only work against production endpoints."

### Important API Version Note

The current REST path prefix is `/trade-api/v2`. A V2 event-order endpoint set was added April 22, 2026 (see Orders section). The legacy `/portfolio/orders` endpoint is deprecated as of May 21, 2026.

---

## 2. Authentication Scheme

**Source:** https://docs.kalshi.com/getting_started/quick_start_authenticated_requests (primary)
**Source:** https://docs.kalshi.com/getting_started/api_keys.md (corroborating)

### Required Headers (exact names)

Every authenticated request must include all three:

| Header Name                | Value Description                              |
|----------------------------|------------------------------------------------|
| `KALSHI-ACCESS-KEY`        | Your API Key ID (UUID format, e.g. `a952bcbe-ec3b-4b5b-b8f9-11dae589608c`) |
| `KALSHI-ACCESS-TIMESTAMP`  | Current Unix time **in milliseconds** (integer as string, e.g. `1703123456789`) |
| `KALSHI-ACCESS-SIGNATURE`  | RSA-PSS signature, **base64-encoded**          |

### Message to Sign — Exact Concatenation

From docs (verbatim): *"Sign a concatenation of the timestamp, the HTTP method and the path."*

```
message = timestamp_ms_string + HTTP_METHOD_UPPERCASE + path_without_query_params
```

**Example from docs:**
```
"1703123456789GET/trade-api/v2/portfolio/balance"
```

**Critical detail from docs:** *"When signing requests, use the path **without query parameters**."*

For a URL like `https://external-api.demo.kalshi.co/trade-api/v2/portfolio/orders?limit=5`, sign only `/trade-api/v2/portfolio/orders`.

Implementation: `path = url.split('?')[0]` (strip query string before signing).

### Signature Algorithm — Exact Specification

From docs (verbatim Python example):

```python
signature = private_key.sign(
    message,
    padding.PSS(
        mgf=padding.MGF1(hashes.SHA256()),
        salt_length=padding.PSS.DIGEST_LENGTH
    ),
    hashes.SHA256()
)
```

- **Algorithm:** RSA-PSS
- **Hash:** SHA-256
- **MGF:** MGF1 with SHA-256
- **Salt length:** `PSS.DIGEST_LENGTH` (i.e., salt length equals the digest length = 32 bytes for SHA-256)
- **Output encoding:** Base64 (standard, not URL-safe — docs do not specify; assume standard base64)
- **Key format:** PEM-encoded RSA private key (generated at https://kalshi.com/account/profile)

From docs on JavaScript: `"RSA-SHA256"` with `"RSA_PKCS1_PSS_PADDING"` and `"RSA_PSS_SALTLEN_DIGEST"` — confirming PSS with digest-length salt across languages.

### Key Management

From docs: *"the private key will not be stored by our service, and you will not be able to retrieve it again once this page is closed."*

Private key is downloaded once and must be kept secure. The Key ID is the `KALSHI-ACCESS-KEY` header value.

---

## 3. Endpoints Needed by the Bot

All paths are relative to the base URL (e.g., `https://external-api.kalshi.com/trade-api/v2`).

### 3.1 List Series

**Source:** https://docs.kalshi.com/api-reference/market/get-series-list

```
GET /series
```

**Query parameters:**

| Parameter                  | Type    | Description |
|----------------------------|---------|-------------|
| `category`                 | string  | Filter by series category |
| `tags`                     | string  | Filter by subject tags |
| `include_product_metadata` | boolean | Include internal metadata (default: false) |
| `include_volume`           | boolean | Include total traded volume per series (default: false) |
| `min_updated_ts`           | integer | Filter series updated after this Unix timestamp (seconds) |

**Key response fields (Series object):**

| Field                 | Type                          | Description |
|-----------------------|-------------------------------|-------------|
| `ticker`              | string                        | Series identifier |
| `title`               | string                        | Series title |
| `frequency`           | string                        | Human-readable frequency (e.g., "daily") |
| `category`            | string                        | Series category |
| `tags`                | array of strings              | Subject tags |
| `fee_type`            | enum                          | `quadratic`, `quadratic_with_maker_fees`, or `flat` |
| `fee_multiplier`      | number (double)               | Multiplier applied to fee calculations |
| `settlement_sources`  | array of SettlementSource     | Official settlement sources |
| `contract_url`        | string                        | Link to original filing |
| `contract_terms_url`  | string                        | Link to current contract terms |
| `additional_prohibitions` | array of strings          | Trading prohibitions |
| `volume_fp`           | FixedPointCount (string)      | Total contracts across all events (if requested) |
| `last_updated_ts`     | date-time string              | Last metadata update |

**SettlementSource object:** `{ "name": string, "url": string }` (both optional)

**Weather/temperature series tickers (THIRD-PARTY SOURCES — confirm via live API):**
Known weather high-temperature series: `KXHIGHNY` (NYC), `KXHIGHCHI` (Chicago), `KXHIGHMIA` (Miami), `KXHIGHLAX` (Los Angeles), `KXHIGHDEN` (Denver). Source: GitHub projects and web research; not from official Kalshi docs. Must be verified via live API call.

### 3.2 List Events

**Source:** https://docs.kalshi.com/api-reference/market/get-series-list (series endpoint; events endpoint 404'd)

```
GET /events
```

> Note: The `/events` page returned 404 during this research pass. The series list endpoint above is the confirmed starting point for discovery. Event listing via `series_ticker` query param is referenced in the Get Markets endpoint and confirmed by third-party sources but the official `/events` endpoint page was not directly accessed.

**Expected query parameters (UNVERIFIED — based on Get Markets docs reference):**

| Parameter        | Description |
|------------------|-------------|
| `series_ticker`  | Filter events by series |
| `status`         | Filter by event status |
| `limit`          | Results per page (default 100) |
| `cursor`         | Pagination cursor |

### 3.3 List Markets for an Event

**Source:** https://docs.kalshi.com/api-reference/market/get-markets.md

```
GET /markets
```

**Query parameters:**

| Parameter         | Type    | Notes |
|-------------------|---------|-------|
| `event_ticker`    | string  | Filter to a single event |
| `series_ticker`   | string  | Filter by series |
| `tickers`         | string  | Comma-separated list of market tickers |
| `status`          | enum    | `unopened`, `open`, `paused`, `closed`, `settled` |
| `limit`           | integer | 0–1000, default 100 |
| `cursor`          | string  | Pagination token |
| `min_close_ts`, `max_close_ts` | integer | Timestamp filters |
| `mve_filter`      | enum    | `only` or `exclude` multivariate events |

**Key response fields (Market summary — abbreviated for list view):**
`ticker`, `event_ticker`, `market_type`, `yes_sub_title`, `no_sub_title`, `status`, `yes_bid_dollars`, `yes_ask_dollars`, `last_price_dollars`, `volume_24h_fp`, `result`

### 3.4 Get Market (single market, full fields)

**Source:** https://docs.kalshi.com/api-reference/market/get-market.md

```
GET /markets/{ticker}
```

**Path parameter:** `ticker` (string, required)

**Key response fields for weather/temperature trading:**

| Field                   | Type                    | Description |
|-------------------------|-------------------------|-------------|
| `ticker`                | string                  | Market identifier |
| `event_ticker`          | string                  | Associated event identifier |
| `market_type`           | enum                    | `binary` or `scalar` |
| `yes_sub_title`         | string                  | "Shortened title for the yes side of this market" |
| `no_sub_title`          | string                  | "Shortened title for the no side of this market" |
| `subtitle`              | string (deprecated)     | Deprecated; prefer `yes_sub_title` / `no_sub_title` |
| `status`                | enum                    | `initialized`, `inactive`, `active`, `closed`, `determined`, `disputed`, `amended`, `finalized` |
| `yes_bid_dollars`       | FixedPointDollars       | "Price for the highest YES buy offer on this market in dollars" |
| `yes_ask_dollars`       | FixedPointDollars       | "Price for the lowest YES sell offer on this market in dollars" |
| `no_bid_dollars`        | FixedPointDollars       | "Price for the highest NO buy offer on this market in dollars" |
| `no_ask_dollars`        | FixedPointDollars       | "Price for the lowest NO sell offer on this market in dollars" |
| `yes_bid_size_fp`       | FixedPointCount         | "Total contract size of orders to buy YES at best bid" |
| `yes_ask_size_fp`       | FixedPointCount         | "Total contract size of orders to sell YES at best ask" |
| `last_price_dollars`    | FixedPointDollars       | "Price for the last traded YES contract on this market in dollars" |
| `volume_fp`             | FixedPointCount         | Total market volume in contracts |
| `volume_24h_fp`         | FixedPointCount         | "String representation of the 24h market volume in contracts" |
| `open_interest_fp`      | FixedPointCount         | "Number of contracts bought disconsidering netting" |
| `floor_strike`          | number/double (nullable)| "Minimum expiration value that leads to a YES settlement" |
| `cap_strike`            | number/double (nullable)| "Maximum expiration value that leads to a YES settlement" |
| `strike_type`           | enum                    | `greater`, `greater_or_equal`, `less`, `less_or_equal`, `between`, `functional`, `custom`, `structured` |
| `rules_primary`         | string                  | "Plain language description of the most important market terms" |
| `rules_secondary`       | string                  | "Plain language description of secondary market terms" |
| `result`                | enum                    | `yes`, `no`, `scalar`, or empty string |
| `settlement_timer_seconds` | integer              | "Amount of time after determination that the market settles" |
| `settlement_ts`         | date-time (nullable)    | "Timestamp when market settled" |
| `expiration_value`      | string                  | "Value considered for settlement" |
| `notional_value_dollars`| FixedPointDollars       | "Total value of a single contract at settlement in dollars" |
| `price_level_structure` | string                  | Active tick-size tier: `linear_cent`, `tapered_deci_cent`, or `deci_cent` |
| `price_ranges`          | array of PriceRange     | Valid price intervals and tick sizes for this market |

> **IMPORTANT:** The field `settlement_sources` is NOT present on the Market object response. Settlement sources are on the **Series** object. To find the NWS station for a temperature market, query `GET /series/{ticker}` and inspect `settlement_sources`.

> **Deprecated fields removed (as of 2026):** `yes_bid` (integer cents), `yes_ask` (integer cents), `no_bid` (integer cents), `no_ask` (integer cents), `last_price` (integer cents) — all removed January 15, 2026. Use `*_dollars` equivalents.

### 3.5 Get Market Orderbook

**Source:** https://docs.kalshi.com/api-reference/market/get-market-orderbook.md

```
GET /markets/{ticker}/orderbook
```

**Query parameter:** `depth` (integer 0–100, default 0; 0 or negative = all levels)

**Response structure:**

```json
{
  "orderbook_fp": {
    "yes_dollars": [ ["0.5500", "100.00"], ["0.5400", "50.00"] ],
    "no_dollars":  [ ["0.4500", "100.00"], ["0.4600", "50.00"] ]
  }
}
```

Each level is a 2-element array: `[price_dollars_string, count_fp_string]`.

Fields: `orderbook_fp.yes_dollars` (array), `orderbook_fp.no_dollars` (array).

### 3.6 Get Portfolio Balance

**Source:** https://docs.kalshi.com/api-reference/portfolio/get-balance.md

```
GET /portfolio/balance
```

Authentication required. Optional query param: `subaccount` (integer, default 0).

**Response fields:**

| Field                | Type              | Description |
|----------------------|-------------------|-------------|
| `balance`            | integer (int64)   | Available balance **in cents** |
| `balance_dollars`    | FixedPointDollars | Available balance as fixed-point string (e.g. `"0.5600"`) |
| `portfolio_value`    | integer (int64)   | Current value of all held positions **in cents** |
| `updated_ts`         | integer (int64)   | Unix timestamp of last balance update |
| `balance_breakdown`  | array (optional)  | Per-exchange-index balances |

### 3.7 Get Positions

**Source:** https://docs.kalshi.com/api-reference/portfolio/get-positions.md

```
GET /portfolio/positions
```

**Query parameters:** `cursor`, `limit` (1–1000, default 100), `count_filter`, `ticker`, `event_ticker`, `subaccount`

**Response:**
- `cursor` (string)
- `market_positions` (array of MarketPosition)
- `event_positions` (array of EventPosition)

**MarketPosition fields:**

| Field                      | Type              | Description |
|----------------------------|-------------------|-------------|
| `ticker`                   | string            | Market identifier |
| `position_fp`              | FixedPointCount   | Contract count (positive = YES, negative = NO) |
| `total_traded_dollars`     | FixedPointDollars | Total spending on market |
| `market_exposure_dollars`  | FixedPointDollars | Aggregate position cost |
| `realized_pnl_dollars`     | FixedPointDollars | Locked profit/loss |
| `fees_paid_dollars`        | FixedPointDollars | Fees on filled orders |
| `last_updated_ts`          | date-time         | Last position update |
| `resting_orders_count`     | integer           | **DEPRECATED** |

### 3.8 Create Order (Legacy endpoint — deprecated May 21, 2026)

**Source:** https://docs.kalshi.com/api-reference/orders/create-order.md

```
POST /portfolio/orders
```

**Request body fields:**

| Field                        | Type              | Required | Notes |
|------------------------------|-------------------|----------|-------|
| `ticker`                     | string            | Yes      | Market ticker |
| `side`                       | enum              | Yes      | `yes` or `no` |
| `action`                     | enum              | Yes      | `buy` or `sell` |
| `client_order_id`            | string            | No       | Idempotency key |
| `count`                      | integer           | No*      | Whole contracts only, min 1 |
| `count_fp`                   | FixedPointCount   | No*      | Fractional contracts as string |
| `yes_price`                  | integer           | No†      | Price in **cents** (1–99) |
| `no_price`                   | integer           | No†      | Price in **cents** (1–99) |
| `yes_price_dollars`          | FixedPointDollars | No†      | Price in fixed-point dollars |
| `no_price_dollars`           | FixedPointDollars | No†      | Price in fixed-point dollars |
| `time_in_force`              | string            | No       | `fill_or_kill`, `good_till_canceled`, `immediate_or_cancel` |
| `expiration_ts`              | int64             | No       | Unix seconds; for `good_till_canceled` orders |
| `post_only`                  | boolean           | No       |  |
| `reduce_only`                | boolean           | No       |  |
| `buy_max_cost`               | integer (cents)   | No       | Triggers FoK behavior |
| `self_trade_prevention_type` | enum              | No       | `taker_at_cross` or `maker` |
| `subaccount`                 | integer           | No       | Default 0 (primary) |
| `exchange_index`             | integer           | No       | Default 0 (only 0 supported) |

*Provide `count` or `count_fp`; if both, they must match.
†Provide price via integer cent field or `_dollars` field; if both, they must match.

> **MIGRATION NOTE:** The `yes_price` / `no_price` integer-cents fields are being phased out. As of March 2026, the API is fully fixed-point. Prefer `yes_price_dollars` / `no_price_dollars`.

> **Deprecation:** This endpoint (`POST /portfolio/orders`) is deprecated effective May 21, 2026. Rate-limit costs were bumped on that date. See V2 endpoint below.

### 3.9 Create Order V2 (Current recommended endpoint)

**Source:** https://docs.kalshi.com/api-reference/orders/create-order-v2

```
POST /portfolio/events/orders
```

**Required request body fields:**

| Field                        | Type              | Notes |
|------------------------------|-------------------|-------|
| `ticker`                     | string            | Market ticker |
| `client_order_id`            | string            | Required in V2 |
| `side`                       | BookSide          | `bid` or `ask` (not `yes`/`no`) |
| `count`                      | FixedPointCount   | Fixed-point string (e.g. `"1.00"`) |
| `price`                      | FixedPointDollars | Fixed-point dollar string |
| `time_in_force`              | string            | `fill_or_kill`, `good_till_canceled`, `immediate_or_cancel` |
| `self_trade_prevention_type` | string            | `taker_at_cross` or `maker` |

> Key difference: V2 uses single-book `bid`/`ask` side (not `yes`/`no` + `buy`/`sell`) and a single `price` field. The legacy `yes_price` / `no_price` distinction is gone.

**Response fields:** `order_id`, `client_order_id`, `fill_count`, `remaining_count`, `average_fill_price`, `average_fee_paid`, `ts_ms`

### 3.10 Cancel Order

**Source:** https://docs.kalshi.com/api-reference/orders/cancel-order.md

```
DELETE /portfolio/orders/{order_id}
```

> **Note:** Rate limit cost is 2 tokens (lower than default 10). The order is not deleted — remaining contracts are "zeroed."

**Query params:** `subaccount` (integer), `exchange_index` (integer)

**Response (HTTP 200):** Returns the cancelled order object plus `reduced_by_fp`.

### 3.11 Get Fills

**Source:** https://docs.kalshi.com/api-reference/portfolio/get-fills.md

```
GET /portfolio/fills
```

**Query parameters:** `ticker`, `order_id`, `min_ts`, `max_ts`, `limit` (1–1000, default 100), `cursor`, `subaccount`

**Fill object fields:**

| Field                | Type       | Description |
|----------------------|------------|-------------|
| `fill_id`            | string     | |
| `trade_id`           | string     | |
| `order_id`           | string     | |
| `ticker`             | string     | |
| `market_ticker`      | string     | |
| `side`               | enum       | `yes` or `no` |
| `action`             | enum       | `buy` or `sell` |
| `outcome_side`       | enum       | `yes` or `no` |
| `book_side`          | enum       | `bid` or `ask` |
| `count_fp`           | string     | Fractional contract count |
| `yes_price_dollars`  | string     | |
| `no_price_dollars`   | string     | |
| `is_taker`           | boolean    | True if this fill was a taker |
| `created_time`       | date-time  | |
| `fee_cost`           | string     | Fee charged for this fill |
| `ts`                 | integer    | Unix timestamp |
| `subaccount_number`  | integer (nullable) | |

---

## 4. Fee Formula

**Source (primary):** https://blog.polytrage.com/kalshis-fee-structure-explained/ (THIRD-PARTY — verbatim quote below)
**Source (corroborating):** https://pm.wiki/learn/kalshi-fees-explained (THIRD-PARTY)
**Source (corroborating):** https://pro.oddsassist.com/calculators/kalshi-fee-calculator (THIRD-PARTY)
**Source (official, mechanics only):** https://docs.kalshi.com/getting_started/fee_rounding.md
**Source (official, fee type):** https://docs.kalshi.com/api-reference/market/get-series-list (fee_type enum)

> **IMPORTANT NOTE:** The official Kalshi fee schedule PDF (`kalshi.com/docs/kalshi-fee-schedule.pdf`) returned HTTP 429 during this research session and could not be directly read. The formula and constants below are confirmed by multiple third-party sources that agree with each other and with the Kalshi API's `fee_type` enumeration (`quadratic`), but they are technically THIRD-PARTY sourced. Verification against the PDF or a live API fill response is recommended.

### Fee Formula (Taker)

```
taker_fee_cents = round_up(0.07 × C × (1 − C))   per contract
```

Where:
- `C` = contract price in **dollars** (range: 0.01 to 0.99)
- `0.07` = 7% taker fee rate
- `C × (1 − C)` = variance of a Bernoulli distribution (uncertainty measure)
- `round_up` = round up to the nearest cent

### Fee Formula (Maker)

```
maker_fee_cents = round_up(0.0175 × C × (1 − C))   per contract
```

Where:
- `0.0175` = 1.75% maker rate (25% of taker rate)

### Rounding Rule

From Polytrage (verbatim): *"Fees are always rounded up to the nearest cent."*

From official docs (verbatim): *"trade fee: rounded up to the nearest $0.0001 (centicent)"* — the official docs describe rounding at the centicent ($0.0001) level internally, with a rounding fee accumulator that issues $0.01 rebates once accumulation exceeds $0.01.

> The official fee_rounding docs describe a two-step process: (a) fee is rounded up to nearest $0.0001 internally, then (b) a rounding_fee is computed to ensure the balance change floors to the nearest $0.01. This is more nuanced than simple cent-rounding. See official docs for exact mechanics.

### API Fee Type Fields

From `GET /series` response:
- `fee_type`: `quadratic` (standard markets), `quadratic_with_maker_fees`, or `flat`
- `fee_multiplier`: floating-point multiplier applied to the fee calculation

The `quadratic` fee type corresponds to the `C × (1 − C)` formula. The `fee_multiplier` likely scales the base rate (0.07 for taker), but the exact interaction between `fee_type`, `fee_multiplier`, taker vs maker, and the base rate is **UNVERIFIED** from official docs.

### Worked Numeric Examples

**Example 1 (50¢ contract, 1 contract, taker):**
- `C = 0.50`
- `fee = round_up(0.07 × 0.50 × 0.50) = round_up(0.0175) = 1.75¢` per contract
- For 100 contracts: `100 × 1.75¢ = $1.75`

**Example 2 (10¢ contract, 1 contract, taker):**
- `C = 0.10`
- `fee = round_up(0.07 × 0.10 × 0.90) = round_up(0.0063) = 0.63¢` per contract

**Example 3 (90¢ contract, 1 contract, taker):**
- `C = 0.90`
- `fee = round_up(0.07 × 0.90 × 0.10) = round_up(0.0063) = 0.63¢` per contract

**Example 4 (55¢ contract, 100 contracts, maker):**
- `C = 0.55`
- `maker_fee = round_up(0.0175 × 0.55 × 0.45) = round_up(0.00433) = 0.44¢` per contract
- Total: `100 × 0.44¢ = $0.44`

**Note on rounding direction:** The fee formula produces a per-contract fee in **cents** (or fractions thereof). From third-party sources: rounding is *up* to nearest cent. Official docs describe sub-cent precision internally with a rebate mechanism.

---

## 5. Settlement: Weather/Temperature Market Rules

**Source:** https://help.kalshi.com/markets/popular-markets/weather-markets (official Kalshi help)
**Source:** https://docs.kalshi.com/api-reference/market/get-market.md (field definitions)

### Settlement Data Source

From official Kalshi help (verbatim): *"The only source used for settlement is the NWS Daily Climate Report."*

From official docs: *"Markets settle based on the final climate report issued by the National Weather Service (NWS), typically released the following morning."*

> **NOT** AccuWeather, iOS Weather, or Google Weather.

### Daylight Saving Time Window

From official help (verbatim): *"During Daylight Saving Time, the high temperature will be recorded between 1:00 AM and 12:59 AM local time the following day."*

### Field That Carries the Settlement Rule

The **`rules_primary`** field on the Market object carries the human-readable plain-language settlement rule. It is defined in the API as: *"Plain language description of the most important market terms."*

This field names the settlement weather station and the daily-max climate-day window for each specific market.

The **`rules_secondary`** field carries: *"Plain language description of secondary market terms."*

### Finding the Settlement Station

1. `GET /series/{series_ticker}` → inspect `settlement_sources` array (each entry has `name` and `url`)
2. `GET /markets/{ticker}` → read `rules_primary` for the specific station and window

**`settlement_sources` location:** On the **Series** object only. Not on the Market object.

---

## 6. Test Vectors

### Fee Test Vector

Derived from official fee formula (source: pm.wiki, corroborated by multiple third-party sources):

```
Input:  price_dollars = 0.50, count = 1, role = taker
Formula: fee = round_up(0.07 × 0.50 × 0.50)
       = round_up(0.0175)
       = 1.75 cents
Expected output: 1.75¢ (i.e., $0.0175 per contract)
```

```
Input:  price_dollars = 0.50, count = 100, role = taker
Expected output: $1.75 total fee
```

Source: From pm.wiki verbatim: *"At 50¢: Fee = 0.07 × 0.50 × 0.50 = 0.0175 = 1.75¢, which is the maximum fee per contract."*

> This is a THIRD-PARTY sourced test vector. The fee schedule PDF (official source) was rate-limited during retrieval. This vector must be verified against a live demo API fill before being used as a unit test regression anchor.

### Signing Test Vector

No published signing vector was found in official Kalshi documentation. The docs provide code examples but no input→output test vector.

**Resolution:** Signing will be verified in code via generate-RSA-keypair → sign → verify-with-public-key round trip using the recorded algorithm (RSA-PSS, SHA-256, MGF1(SHA-256), salt_length=DIGEST_LENGTH, base64 output).

---

## 7. UNVERIFIED / RISKS

The following items could not be confirmed from official primary sources, are ambiguous, or show conflicts across sources:

1. **Fee schedule PDF unavailable.** `kalshi.com/docs/kalshi-fee-schedule.pdf` returned HTTP 429 (rate-limited). The fee formula constants (7% taker, 1.75% maker) are from third-party sources that agree with each other and with Kalshi's `fee_type=quadratic` enum, but must be cross-checked against the PDF or a live fill's `fee_cost` field.

2. **fee_multiplier interaction.** The Series object has a `fee_multiplier` field. It is documented as "a floating point multiplier applied to fee calculations" but the exact multiplication target (rate, formula output, or something else) is not explained in official docs. Weather markets may have `fee_multiplier ≠ 1.0`. **Risk:** bot may compute wrong fees if multiplier is not 1.0 for KXHIGH series.

3. **fee_type = quadratic_with_maker_fees.** The distinction between `quadratic` and `quadratic_with_maker_fees` is not explained in official docs. This may affect whether maker discounts apply to KXHIGH markets.

4. **Weather series tickers.** `KXHIGHNY`, `KXHIGHCHI`, `KXHIGHMIA`, `KXHIGHLAX`, `KXHIGHDEN` are from third-party GitHub projects, not official Kalshi documentation. Must be confirmed via `GET /series?category=weather` or equivalent live call.

5. **Elections production base URL.** The OpenAPI spec lists `https://api.elections.kalshi.com/trade-api/v2` as a server. It is unclear if this is a general-purpose URL, election-market-specific, or deprecated. Use `https://external-api.kalshi.com/trade-api/v2` for general trading.

6. **Create Order V2 `side` semantics.** The V2 endpoint uses `bid`/`ask` instead of `yes`/`no` + `buy`/`sell`. The exact mapping (does `bid` mean "buy YES" or "buy NO"?) needs verification against live API behavior or more detailed V2 docs.

7. **Integer `yes_price`/`no_price` in legacy endpoint.** These were documented as valid (1–99 cents) in the endpoint docs but marked for migration. As of this research date (2026-05-16), the legacy endpoint is deprecated but the deprecation timeline says "no earlier than May 21, 2026" for rate-limit bumps. Whether integer fields still work in responses is unclear — official changelog says integer fields were removed from Market responses Jan 15, 2026 and count fields March 12, 2026.

8. **`/events` endpoint.** The official docs page at `docs.kalshi.com/api-reference/market/get-events` returned HTTP 404. The endpoint likely exists (referenced in other docs), but query parameters and full response schema were not directly confirmed.

9. **Base64 encoding variant.** Docs specify base64 encoding for the signature but do not specify standard vs. URL-safe base64. Standard base64 (with `+`, `/`, `=`) assumed. Must verify with a live authenticated request.

10. **Salt length constant.** `PSS.DIGEST_LENGTH` in Python's cryptography library equals the SHA-256 digest size (32 bytes). The docs don't state the byte value explicitly. This is correct per the Python library semantics but worth confirming with a test round-trip.

11. **"Zero trading fees" claim.** One third-party source (agentbets.ai) claimed "zero trading fees as of 2026." This contradicts all other sources including the official fee_rounding docs and the fee_type API field. Treat this as incorrect — likely referring to a promotional period or misinterpretation. **UNVERIFIED / contradicted.**

12. **Settlement source for specific NWS station.** The NWS station identifier (e.g., "Central Park" for NYC) that each KXHIGH market settles against is in `rules_primary` and `settlement_sources` but was not verified for specific tickers. Must be read from the live API.

---

## Appendix: Key Type Definitions

| Type              | Format |
|-------------------|--------|
| `FixedPointDollars` | string, fixed-point decimal, up to 6 decimal places in requests, 4 in responses (e.g. `"0.5500"`) |
| `FixedPointCount`   | string, fixed-point decimal, 0–2 decimal places (responses always 2 places, e.g. `"100.00"`) |
| `BookSide` (V2)     | enum: `bid` or `ask` |
| `Side` (legacy)     | enum: `yes` or `no` |

## Appendix: Tick Size Tiers

**Source:** https://docs.kalshi.com/getting_started/subpenny_pricing

| `price_level_structure` | Price Range | Tick Size |
|-------------------------|-------------|-----------|
| `linear_cent`           | $0.00–$1.00 | $0.01 |
| `tapered_deci_cent`     | $0.00–$0.10 and $0.90–$1.00 | $0.001 |
| `tapered_deci_cent`     | $0.10–$0.90 | $0.01 |
| `deci_cent`             | $0.00–$1.00 | $0.001 |

Use `market.price_level_structure` and `market.price_ranges[].step` to determine valid order prices.
