"""
Shadow-paper fill simulator: the paper-proof analog of the live WebSocket fill handler.

This module closes the paper-proof guard-release hole: in shadow-paper mode there are
no live WS fill events, so working orders are never cleared by the broker. Without this
module, every market becomes permanently blocked after its first paper order and all
gate metrics (Brier/PnL/CRPS) are invalid because the position manager stops trading.

Fill model (deliberately simple / conservative)
------------------------------------------------
PaperBook stores the best resting level per market and side (yes/no). A buy of ``side``
at ``limit_price`` is marketable if ``limit_price >= resting_price`` for that side.
Filled quantity = min(requested count, resting size) at resting_price. This is a
conservative taker model: we assume we lift the best offer and get partial fill if the
offer size is smaller than our order. Exact microstructure (queue position, iceberg
orders, price-time priority across levels) is out of scope for v1 — the model is
intentionally simple and deterministic.

Position-aggregation rule
--------------------------
simulate_fills computes the POST-aggregation (count, avg_entry_cents) by combining the
fill with any existing position for that market:
- Same-direction: weighted average of avg_entry_cents; total count = existing + fill.
- Opposite-direction (v1 simplification): net the counts; if the fill fully closes,
  count becomes 0 (or the remainder); if excess, the remaining count takes the fill's
  price as the new avg_entry. This case should not arise in normal v1 operation because
  working orders for a market are placed same-direction within a climate day — documented
  as a simplification.

Partial-fill requeue
---------------------
v1 treats any filled > 0 as the working order fully consumed and released. Partial-fill
requeue (placing a new working order for the remaining unfilled quantity) is out of scope
for v1. The working order is always cleared on any partial fill; the runner may re-enter
on the next tick. Document this for Task 17.

CRITICAL — clear_working_orders_for_market
-------------------------------------------
simulate_fills MUST call pm.clear_working_orders_for_market(market) for every market
with a successful fill. This is what releases the one-in-flight-order guard so subsequent
entries for that market are allowed. Failure to call this makes every market permanently
blocked after its first shadow-paper order and renders all paper-proof gate metrics
invalid. This call mirrors what the live WS fill handler does on receipt of a fill event.

YAGNI: only PaperBook and simulate_fills are exported.

Fill persistence: each successful fill is recorded via State.record_fill and the
originating order is flipped to status='filled' via State.mark_order_filled.
This is what gives settle_day and the gate an audit trail of what paper trades
actually happened.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kaiju.execution.position_manager import PositionManager


class PaperBook:
    """Stores the top-of-book (best level) per market per side for paper-fill simulation.

    Pure and deterministic: no external I/O, no randomness. Stores only the best
    resting level per (market, side) — KISS; additional depth levels are ignored.
    """

    def __init__(self) -> None:
        # _book[(market, side)] = (price_cents, size)
        self._book: dict[tuple[str, str], tuple[int, int]] = {}

    def update(
        self,
        market: str,
        *,
        yes: list[list[int]],
        no: list[list[int]],
    ) -> None:
        """Store the best resting level for each side of ``market``.

        ``yes`` and ``no`` are lists of [price_cents, size] levels ordered
        best-first (lowest ask / highest bid first). Only the first level is
        stored; additional depth is ignored for v1 simplicity.

        Args:
            market: Market ticker string.
            yes: Resting yes levels [[price_cents, size], ...] best-first.
            no: Resting no levels [[price_cents, size], ...] best-first.
        """
        if yes:
            self._book[(market, "yes")] = (int(yes[0][0]), int(yes[0][1]))
        if no:
            self._book[(market, "no")] = (int(no[0][0]), int(no[0][1]))

    def try_fill(
        self,
        market: str,
        side: str,
        limit_price: int,
        count: int,
    ) -> dict[str, int]:
        """Simulate a marketable-limit taker fill against the resting book.

        A buy of ``side`` at ``limit_price`` fills against the best resting level
        for that side if ``limit_price >= resting_price`` (marketable). Filled
        quantity = min(count, resting_size). If not marketable or no book entry
        exists, returns filled=0.

        This is a conservative single-level taker model. Queue position and
        multi-level sweeps are out of scope for v1.

        Args:
            market: Market ticker.
            side: "yes" or "no".
            limit_price: Our limit price in cents (0-99).
            count: Number of contracts we want to buy.

        Returns:
            {"filled": int, "price": int} — filled=0 and price=0 if no fill.
        """
        entry = self._book.get((market, side))
        if entry is None:
            return {"filled": 0, "price": 0}

        resting_price, resting_size = entry
        if limit_price < resting_price:
            # Not marketable.
            return {"filled": 0, "price": 0}

        filled = min(count, resting_size)
        return {"filled": filled, "price": resting_price}


def simulate_fills(
    pm: "PositionManager",
    book: PaperBook,
    climate_date: str,
) -> int:
    """Apply paper fills for all open working orders against the current book.

    This is the shadow-paper analog of the live WS fill handler. It iterates
    all open working orders from pm.state, attempts a fill via book.try_fill,
    and for each successful fill:

    1. Computes the POST-aggregation (count, avg_entry_cents) by combining the
       fill with any existing position (weighted average, same-direction assumed).
    2. Calls pm.state.upsert_position with the full post-aggregation totals.
    3. CRITICALLY: calls pm.clear_working_orders_for_market(market) to release
       the one-in-flight guard — exactly as the live WS fill handler does on
       receipt of a fill event. Without this, markets are permanently blocked.

    v1 simplifications (documented):
    - Partial fills: any filled > 0 fully consumes the working order. The
      remainder is NOT requeued. The runner may re-enter on the next tick.
    - Same-direction assumption: working orders for a market are expected to be
      same-direction as any existing position within a climate day. Opposite-side
      netting is handled conservatively (net counts, remainder takes fill price)
      but should not arise in normal v1 operation.
    - Each fill is persisted to the fills table and the originating order's
      status is flipped to 'filled' (in line with the "any filled fully consumes
      the working order" rule above).

    Args:
        pm: PositionManager (must be in shadow-paper or backtest mode).
        book: PaperBook with current top-of-book data loaded via update().
        climate_date: The climate date string for position records (e.g. "2026-05-17").

    Returns:
        Number of working orders that received a fill (full or partial).
    """
    filled_count = 0

    for row in pm.state.list_working_orders():
        client_id: str = row["client_id"]
        market: str = row["market"]
        side: str = row["side"]
        price: int = row["price"]
        count: int = row["count"]

        result = book.try_fill(market, side, limit_price=price, count=count)
        if result["filled"] <= 0:
            continue

        fill_qty: int = result["filled"]
        fill_price: int = result["price"]

        # Compute POST-aggregation position (weighted avg, same-direction assumed).
        existing = pm.state.get_position(market)
        if existing is None:
            new_count = fill_qty
            new_avg = fill_price
            new_side = side
        elif existing["side"] == side:
            # Same direction: accumulate with weighted average.
            old_count: int = existing["count"]
            old_avg: int = existing["avg_entry_cents"]
            new_count = old_count + fill_qty
            new_avg = (old_avg * old_count + fill_price * fill_qty) // new_count
            new_side = side
        else:
            # Opposite direction (v1 simplification: should not arise in normal
            # operation). Net the counts; if fill closes, remainder = 0 (or
            # flips direction if fill exceeds existing count).
            old_count = existing["count"]
            net = old_count - fill_qty
            if net > 0:
                # Partially closed — keep existing side, old avg, reduced count.
                new_count = net
                new_avg = existing["avg_entry_cents"]
                new_side = existing["side"]
            elif net == 0:
                # Fully closed — count = 0. Upsert with 0 to record the close.
                new_count = 0
                new_avg = 0
                new_side = existing["side"]
            else:
                # Fill exceeded existing position: flip to fill side.
                new_count = -net  # positive remainder
                new_avg = fill_price
                new_side = side

        # Wholesale-replace the position row with post-aggregation totals.
        pm.state.upsert_position(market, new_side, new_count, new_avg, climate_date)

        # Persist the fill and mark the order filled — without this, settle_day
        # and the gate have no audit trail of what actually traded. v1 treats any
        # filled > 0 as fully consuming the working order (see "Partial-fill
        # requeue" in the module docstring), so we mark the order filled now.
        pm.state.record_fill(client_id, market, fill_price, fill_qty)
        pm.state.mark_order_filled(client_id)

        # CRITICAL: release the one-in-flight guard so this market can accept
        # new orders on the next tick. This mirrors the live WS fill handler.
        pm.clear_working_orders_for_market(market)

        filled_count += 1

    return filled_count
