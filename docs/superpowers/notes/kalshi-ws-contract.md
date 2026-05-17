# Kalshi WebSocket Contract — Verified Research Notes

**Retrieved: 2026-05-17**

Sources: official Kalshi documentation fetched via WebFetch on 2026-05-17.
- https://docs.kalshi.com/getting_started/quick_start_websockets
- https://docs.kalshi.com/asyncapi.yaml (AsyncAPI spec, 109.5KB YAML)
- https://docs.kalshi.com/websockets/websocket-connection.md
- https://docs.kalshi.com/websockets/orderbook-updates.md
- https://docs.kalshi.com/websockets/user-fills.md
- https://docs.kalshi.com/websockets/connection-keep-alive.md

All items are sourced from official Kalshi documentation unless marked **UNVERIFIED**.

---

## 1. Connection URLs

| Environment | WebSocket URL |
|-------------|---------------|
| Production  | `wss://external-api-ws.kalshi.com/trade-api/ws/v2` |
| Demo        | `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` |

Legacy endpoints (still supported per docs):
- `wss://api.elections.kalshi.com/trade-api/ws/v2`
- `wss://demo-api.kalshi.co/trade-api/ws/v2`

---

## 2. Authentication Handshake

### Headers (exact names — same three as REST)

| Header Name                | Value Description                                 |
|----------------------------|---------------------------------------------------|
| `KALSHI-ACCESS-KEY`        | API Key ID (UUID)                                 |
| `KALSHI-ACCESS-SIGNATURE`  | RSA-PSS signature, base64-encoded                 |
| `KALSHI-ACCESS-TIMESTAMP`  | Unix time in milliseconds (integer as string)     |

These headers are sent as part of the WebSocket HTTP Upgrade request.

### Signed String — Exact Format

```
timestamp_ms_string + "GET" + "/trade-api/ws/v2"
```

**Example:** `"1703123456789GET/trade-api/ws/v2"`

Source (verbatim from quick_start_websockets docs):
> "The string to sign follows this exact format: `timestamp + "GET" + "/trade-api/ws/v2"`"

**CRITICAL NOTE on path:** The WS signed path is `/trade-api/ws/v2` — this is DIFFERENT from
the REST base path `/trade-api/v2`. The WS path has `ws` before `v2`, not after.

### Signing Algorithm

Identical to REST (see `kalshi-api-contract.md §2`):
- RSA-PSS, SHA-256 digest, MGF1(SHA-256), salt_length = PSS.DIGEST_LENGTH (32 bytes)
- Output: standard base64-encoded string

### Reuse of `sign_request`

`kaiju.markets.kalshi_client.sign_request(private_key_pem, "GET", "/trade-api/ws/v2", timestamp_ms)`
produces the correct `(sig_b64, ts_str)` for WS auth — passing the literal path `/trade-api/ws/v2`
directly (no base_url prefix manipulation needed; the WS path IS the full signing path from host root).

---

## 3. Subscribe Message Format

### Subscribe to a single market

```json
{
  "id": 1,
  "cmd": "subscribe",
  "params": {
    "channels": ["orderbook_delta"],
    "market_ticker": "KXHARRIS24-LSV"
  }
}
```

### Subscribe to multiple markets

```json
{
  "id": 2,
  "cmd": "subscribe",
  "params": {
    "channels": ["orderbook_delta"],
    "market_tickers": ["KXFUT24-LSV", "KXHARRIS24-LSV"]
  }
}
```

### Subscribe to fills (no market filter needed for account-wide fills)

```json
{
  "id": 3,
  "cmd": "subscribe",
  "params": {
    "channels": ["fill"]
  }
}
```

**Required fields:**
- `id` (integer): Unique command identifier per connection session
- `cmd` (string): `"subscribe"`
- `params.channels` (array of strings): channel names

**Optional params fields:**
- `market_ticker` (string): single market filter
- `market_tickers` (array of strings): multiple market filter
- `send_initial_snapshot` (boolean): request initial snapshot on subscribe — **UNVERIFIED** (mentioned in asyncapi.yaml, not in quick_start docs)

### Subscribed Confirmation Message

```json
{
  "id": 1,
  "type": "subscribed",
  "msg": {
    "channel": "orderbook_delta",
    "sid": 1
  }
}
```

---

## 4. Message Shapes

All messages from the server have this outer envelope:

```json
{
  "type": "<message_type>",
  "sid": <subscription_id_integer>,
  "seq": <sequence_number_integer>,
  "msg": { ... }
}
```

`seq`: sequential number to detect missed messages (UNVERIFIED: whether seq is per-channel or global).

### 4.1 orderbook_snapshot

Sent when first subscribing to `orderbook_delta` channel; provides full current orderbook state.

```json
{
  "type": "orderbook_snapshot",
  "sid": 2,
  "seq": 2,
  "msg": {
    "market_ticker": "FED-23DEC-T3.00",
    "market_id": "9b0f6b43-5b68-4f9f-9f02-9a2d1b8ac1a1",
    "yes_dollars_fp": [
      ["0.0800", "300.00"],
      ["0.2200", "333.00"]
    ],
    "no_dollars_fp": [
      ["0.5400", "20.00"],
      ["0.5600", "146.00"]
    ]
  }
}
```

**msg fields:**
- `market_ticker` (string): market identifier
- `market_id` (string, UUID): internal market UUID
- `yes_dollars_fp` (array of [price_str, count_str]): YES side levels
- `no_dollars_fp` (array of [price_str, count_str]): NO side levels

Each level: `[price_dollars_string, count_fp_string]`  e.g. `["0.0800", "300.00"]`

**FIELD MAPPING NOTE:** The WS snapshot uses `yes_dollars_fp` / `no_dollars_fp`
(with `_fp` suffix), while the REST orderbook endpoint uses `yes_dollars` / `no_dollars`
(no `_fp` suffix). These are DIFFERENT field names for the same concept.

**Level ordering:** UNVERIFIED — assumed best-first (highest bid first) per REST analogy.
Confirm during Task 17 live demo.

### 4.2 orderbook_delta

Incremental update to the orderbook after receiving the snapshot.

```json
{
  "type": "orderbook_delta",
  "sid": 2,
  "seq": 3,
  "msg": {
    "market_ticker": "FED-23DEC-T3.00",
    "market_id": "9b0f6b43-5b68-4f9f-9f02-9a2d1b8ac1a1",
    "price_dollars": "0.960",
    "delta_fp": "-54.00",
    "side": "yes",
    "ts": "2022-11-22T20:44:01Z",
    "ts_ms": 1669149841000
  }
}
```

**msg fields:**
- `market_ticker` (string): market identifier
- `market_id` (string, UUID): internal market UUID
- `price_dollars` (string): price level being updated (fixed-point dollar string)
- `delta_fp` (string): signed quantity change (negative = removal); fixed-point count string
- `side` (string): `"yes"` or `"no"`
- `ts` (string): ISO 8601 timestamp
- `ts_ms` (integer): Unix timestamp in milliseconds

**Delta application:** positive `delta_fp` = add quantity at this price; negative = remove.
A price level with resulting quantity = 0 should be removed from the local book.

### 4.3 fill

User's order fill notifications (authenticated channel).

```json
{
  "type": "fill",
  "sid": 13,
  "msg": {
    "trade_id": "d91bc706-ee49-470d-82d8-11418bda6fed",
    "order_id": "ee587a1c-8b87-4dcf-b721-9f6f790619fa",
    "market_ticker": "HIGHNY-22DEC23-B53.5",
    "is_taker": true,
    "side": "yes",
    "yes_price_dollars": "0.750",
    "count_fp": "278.00",
    "action": "buy",
    "ts": 1671899397,
    "ts_ms": 1671899397000,
    "post_position_fp": "500.00",
    "purchased_side": "yes",
    "subaccount": 3
  }
}
```

**msg fields:**
- `trade_id` (string, UUID): trade identifier
- `order_id` (string, UUID): the order that was filled
- `market_ticker` (string): market identifier
- `is_taker` (boolean): true if this fill was a taker
- `side` (string): `"yes"` or `"no"` — which side was filled
- `yes_price_dollars` (string): fixed-point dollar price
- `count_fp` (string): fixed-point count of contracts filled
- `action` (string): `"buy"` or `"sell"`
- `ts` (integer): Unix timestamp (seconds)
- `ts_ms` (integer): Unix timestamp (milliseconds)
- `post_position_fp` (string): position size after this fill
- `purchased_side` (string): `"yes"` or `"no"` — UNVERIFIED: distinction from `side`
- `subaccount` (integer): subaccount number

**Note:** The `fill` channel does NOT have a `seq` field in the outer envelope per the example
(only `sid` shown, no `seq`). UNVERIFIED: may be omitted for account channels.

---

## 5. Other Channel Types (for reference, not implemented in Task 14)

| Channel name              | Type    | Description |
|---------------------------|---------|-------------|
| `ticker`                  | Public  | Real-time price/volume/OI updates |
| `trade`                   | Public  | Public trade executions |
| `market_lifecycle_v2`     | Public  | Market state changes |
| `market_positions`        | Private | Real-time position updates |
| `user_orders`             | Private | Order created/updated notifications |
| `order_group_updates`     | Private | Order group lifecycle |
| `communications`          | Private | RFQ/quote notifications |

---

## 6. Heartbeat / Keep-Alive

From official docs (verbatim):
> "Kalshi sends Ping frames (0x9) every 10 seconds with body `heartbeat` to maintain the connection. Clients should respond with Pong frames (0xA)."

- **Frequency:** every 10 seconds
- **Ping payload:** literal string `"heartbeat"`
- **Pong payload:** empty string `''`
- **Client-initiated:** clients may also send Ping frames; Kalshi responds with Pong
- **`websockets` library:** handles Ping/Pong automatically at the protocol level (no manual handling needed with Python `websockets>=10`)

---

## 7. Error Message Format

```json
{
  "id": 123,
  "type": "error",
  "msg": {
    "code": 6,
    "msg": "Already subscribed"
  }
}
```

Known error codes (from docs examples): `2` = "Params required", `6` = "Already subscribed".

---

## 8. UNVERIFIED / RISKS

The following items could not be fully confirmed from official docs or require live confirmation in Task 17:

1. **WS path in signing string.** The docs show `"/trade-api/ws/v2"` as the signed path. This is NOT the same as the REST base path `/trade-api/v2`. Confirmed from `quick_start_websockets` verbatim. VERIFY that the actual server accepts this path in the signature (not e.g. the full URL path `/trade-api/ws/v2` with host, or a different path).

2. **`send_initial_snapshot` param.** AsyncAPI spec mentions this boolean param on subscribe. The quick_start docs do not show it. The `orderbook_delta` channel docs say a snapshot is always sent first automatically. Behavior when `send_initial_snapshot=false` is unverified.

3. **`seq` field on fill channel.** The fill example in docs omits `seq` from the outer envelope. Whether it is present (and whether clients need to track it) is unverified.

4. **Level ordering in `orderbook_snapshot`.** The snapshot `yes_dollars_fp` / `no_dollars_fp` are assumed to be sorted best-first (highest bid first). Not explicitly stated in WS docs. Must verify on Task 17 live data.

5. **`purchased_side` vs `side` in fill.** Both fields appear in the fill message. The distinction (e.g. `side` = book side, `purchased_side` = outcome side?) is not explained in docs. UNVERIFIED.

6. **Demo key rejection.** The `.env` key may be a production key only; the demo WS endpoint may reject it. This is an acceptable signal to record in Task 17.

7. **`update_subscription` cmd.** Docs mention an `update_subscription` command with `add_markets`, `delete_markets`, `get_snapshot` actions. Full schema not verified.

8. **Base64 encoding variant.** Same as REST: standard base64 (not URL-safe) assumed. Verify on Task 17.

9. **Orderbook snapshot field name mismatch.** REST uses `yes_dollars`/`no_dollars` (no `_fp`); WS snapshot uses `yes_dollars_fp`/`no_dollars_fp`. This asymmetry was confirmed from docs — but the exact behavior (is there a non-`_fp` alias?) is unverified.
