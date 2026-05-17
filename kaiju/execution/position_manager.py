"""
Position manager: execution layer for entry and exit orders.

Modes
------
- ``live``         — sends orders to the Kalshi broker via KalshiClient.
- ``shadow-paper`` — records orders locally but never calls broker.
- ``backtest``     — same as shadow-paper; purely local recording.

Idempotency key scheme
----------------------
Client order IDs are deterministic SHA-1 hashes of the logical order
parameters::

    sha1(f"{kind}|{climate_date}|{market}|{side}|{price}|{count}")[:16]

where ``kind`` is ``"entry"`` or ``"exit"``. The same logical order on any
re-run or WS reconnect produces the same client ID, so the broker and local
ledger both reject duplicates silently.

Idempotency ledger: the ``orders`` table in State (via ``record_order`` +
``get_order``). ``record_working_order`` tracks in-flight orders separately;
the skip-check and the record that matters for dedup both use the ``orders``
table so they are always consistent.

One-in-flight-order-per-market guard (conservative v1, no cancel-replace)
--------------------------------------------------------------------------
At most one in-flight order per market at any time. Before placing any new
order the manager checks ``list_working_orders()`` for a row with the same
market ticker; if found, the market is skipped for that tick. This prevents
oversell (multiple SELL orders for the same position) and entry-burst
(multiple BUY orders before any fill) that arise when fair value / ask drifts
between ticks and the client_id therefore changes (price is part of the key).

The runner MUST call ``clear_working_orders_for_market(market)`` when that
market's order fills or is cancelled (WS fill events) and on settlement;
``reconcile()`` clears markets the broker confirms.

Reconcile
---------
``reconcile()`` is ``async def`` so WsClient can ``await pm.reconcile()``
when passed as ``on_connect_reconcile``. Inside it calls the sync
KalshiClient.get_positions() and upserts each broker position into State,
making the broker authoritative on reconnect. After upserting,
``clear_working_orders_for_market`` is called for every market the broker
reported (their fate is now reflected in positions).

Quotes and open interest come from ``parse_event_snapshot`` elsewhere.
This manager only EXECUTES trade decisions; pricing / edge / exit decisions
are made by strategy modules.

CUT-without-limit fallback
--------------------------
If an ``ExitDecision(action=CUT, limit_price_cents=None, ...)`` is received,
this manager cannot price a market order (it holds no live quote). Fallback:
use the position's ``avg_entry_cents`` as the limit price. This is
documented behaviour — callers should prefer providing an explicit limit.
A WARNING is emitted when this fallback is triggered, because the fallback
price may not be marketable and the position may not close.
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

from kaiju.types import ExitAction, ExitDecision, TradeIntent

if TYPE_CHECKING:
    from kaiju.state import State

log = logging.getLogger(__name__)


class PositionManager:
    """Execution layer: submit/record entry and exit orders, reconcile positions."""

    def __init__(self, mode: str, kalshi, state: "State") -> None:
        self.mode = mode
        self.kalshi = kalshi
        self.state = state

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _client_id(
        self,
        climate_date: str,
        market: str,
        side: str,
        price: int,
        count: int,
        kind: str,
    ) -> str:
        """Return a stable 16-char hex idempotency key for this logical order.

        Inputs must be fully specified; same inputs always produce the same id.
        ``kind`` is ``"entry"`` or ``"exit"``.
        """
        raw = f"{kind}|{climate_date}|{market}|{side}|{price}|{count}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    def _is_submitted(self, client_id: str) -> bool:
        """Return True if this client_id is already in the orders ledger."""
        return self.state.get_order(client_id) is not None

    def _has_open_working_order(self, market: str) -> bool:
        """Return True if any working order exists for this market.

        Uses ``list_working_orders()`` which returns a list of dicts with at
        least ``client_id`` and ``market`` keys.  This is the primary guard
        that enforces the one-in-flight-order-per-market invariant.
        """
        return any(row["market"] == market for row in self.state.list_working_orders())

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def execute_entries(self, intents: list[TradeIntent], climate_date: str) -> None:
        """Submit (or record) entry orders for each intent.

        Idempotent: same intent on re-run is skipped if already in the orders
        ledger. In ``live`` mode the order is sent to the broker; in
        ``shadow-paper``/``backtest`` it is recorded locally only.
        """
        for intent in intents:
            # One-in-flight-order-per-market guard (Fix 1).
            # If any working order exists for this market, skip this tick.
            # This prevents entry-burst when the ask drifts between ticks,
            # changing the client_id and bypassing the per-id dedup.
            if self._has_open_working_order(intent.market_ticker):
                continue

            cid = self._client_id(
                climate_date,
                intent.market_ticker,
                intent.side,
                intent.limit_price_cents,
                intent.count,
                "entry",
            )

            # Skip if already submitted (idempotency — second layer of dedup).
            if self._is_submitted(cid):
                continue

            # Send to broker in live mode only.
            if self.mode == "live":
                self.kalshi.create_order(
                    client_order_id=cid,
                    ticker=intent.market_ticker,
                    side=intent.side,
                    action="buy",
                    count=intent.count,
                    price_cents=intent.limit_price_cents,
                )

            # Always record in both ledgers (idempotency + working order tracking).
            self.state.record_order(
                client_id=cid,
                market=intent.market_ticker,
                side=intent.side,
                price=intent.limit_price_cents,
                count=intent.count,
                mode=self.mode,
            )
            self.state.record_working_order(
                client_id=cid,
                market=intent.market_ticker,
                side=intent.side,
                price=intent.limit_price_cents,
                count=intent.count,
                mode=self.mode,
            )

    def execute_exits(
        self, decisions: dict[str, ExitDecision], climate_date: str
    ) -> None:
        """Submit (or record) exit orders for the given decisions.

        ``HOLD`` decisions are no-ops. ``EXIT`` and ``CUT`` close the held
        position by selling (for a YES position) or buying back (for a NO
        position).

        CUT-without-limit fallback: if ``decision.limit_price_cents is None``
        (only valid for CUT), the position's ``avg_entry_cents`` is used as
        the limit. Callers should provide an explicit limit where possible.

        Idempotent via the same ``orders`` ledger and ``_client_id`` scheme.
        """
        for market, decision in decisions.items():
            if decision.action == ExitAction.HOLD:
                continue

            # One-in-flight-order-per-market guard (Fix 1).
            # Applied to EXIT and CUT (not HOLD — HOLD is already skipped above).
            # Prevents oversell when bid/ask drifts between ticks: a new
            # client_id would otherwise bypass the per-id dedup and a second
            # SELL order would be placed while the first is still working.
            if self._has_open_working_order(market):
                continue

            pos = self.state.get_position(market)
            if pos is None:
                continue

            # Determine close price.
            if decision.limit_price_cents is not None:
                close_price = decision.limit_price_cents
            else:
                # CUT-without-limit: fall back to avg entry as a defined,
                # documented limit. Emit WARNING — this price may not be
                # marketable and the position may not close (Fix 3).
                log.warning(
                    "CUT for %s has no explicit limit; falling back to "
                    "avg_entry_cents=%s which may NOT be marketable "
                    "(position may not close). Runner should pass an explicit limit.",
                    market,
                    pos["avg_entry_cents"],
                )
                close_price = pos["avg_entry_cents"]

            cid = self._client_id(
                climate_date,
                market,
                pos["side"],
                close_price,
                pos["count"],
                "exit",
            )

            if self._is_submitted(cid):
                continue

            if self.mode == "live":
                self.kalshi.create_order(
                    client_order_id=cid,
                    ticker=market,
                    side=pos["side"],
                    action="sell",
                    count=pos["count"],
                    price_cents=close_price,
                )

            self.state.record_order(
                client_id=cid,
                market=market,
                side=pos["side"],
                price=close_price,
                count=pos["count"],
                mode=self.mode,
            )
            self.state.record_working_order(
                client_id=cid,
                market=market,
                side=pos["side"],
                price=close_price,
                count=pos["count"],
                mode=self.mode,
            )

    def clear_working_orders_for_market(self, market: str) -> None:
        """Release the one-in-flight-order guard for ``market``.

        Iterates ``state.list_working_orders()`` and calls
        ``state.clear_working_order(client_id)`` for every row whose
        ``market`` field equals ``market``.

        The runner MUST call this when a market's order fills or is
        cancelled (WS fill events) and on settlement, so the guard does
        not block new orders forever.  ``reconcile()`` calls this
        automatically for every market the broker reports.
        """
        for row in self.state.list_working_orders():
            if row["market"] == market:
                self.state.clear_working_order(row["client_id"])

    async def reconcile(self) -> None:
        """Sync local position state from the broker (source of truth on reconnect).

        Calls the synchronous KalshiClient.get_positions() inside this
        async def so WsClient can ``await pm.reconcile()`` as
        ``on_connect_reconcile``.

        After upserting broker positions, calls
        ``clear_working_orders_for_market`` for every market present in the
        broker response.  The broker is source of truth — their fate is now
        reflected in positions.  Only markets the broker reported are cleared;
        genuinely-still-pending orders for other markets are untouched.

        Field mapping from broker response dict:
          - ``ticker``           → market  (test keys + UNVERIFIED for live API)
          - ``side``             → side    (test keys; live API: UNVERIFIED — real
                                            MarketPosition uses ``position_fp`` sign
                                            convention, not a ``side`` string field)
          - ``count``            → count   (test keys; UNVERIFIED for live API —
                                            real API uses ``position_fp`` FixedPoint)
          - ``avg_entry_cents``  → avg_entry_cents (UNVERIFIED — not a documented
                                            field in kalshi-api-contract.md section 3.7;
                                            real API has ``total_traded_dollars`` /
                                            ``market_exposure_dollars`` but no explicit
                                            avg_entry_cents field)
          - ``climate_date``     → climate_date (UNVERIFIED — not in Kalshi API;
                                            kaiju-specific metadata)

        For the real KalshiClient, a translation layer will be needed to
        convert ``position_fp`` sign to (side, count) and derive
        avg_entry_cents from fill history or exposure dollars.
        """
        broker_positions = self.kalshi.get_positions()
        for bp in broker_positions:
            self.state.upsert_position(
                market=bp["ticker"],
                side=bp["side"],
                count=bp["count"],
                avg_entry_cents=bp["avg_entry_cents"],
                climate_date=bp.get("climate_date", ""),
            )
            # Broker is source of truth: clear working orders for this market
            # since their fate is now reflected in the upserted position.
            self.clear_working_orders_for_market(bp["ticker"])
