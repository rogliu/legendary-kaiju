from kaiju.types import TradeIntent
from kaiju.state import State
from kaiju.execution.position_manager import PositionManager
from kaiju.execution.paper_sim import PaperBook, simulate_fills


def _pm(tmp):
    st = State(str(tmp / "s.sqlite"))
    st.init_schema()

    class NoBroker:  # shadow-paper: never used for orders
        def get_positions(self):
            return []

    return PositionManager(mode="shadow-paper", kalshi=NoBroker(), state=st), st


def test_marketable_limit_fills_against_book():
    pb = PaperBook()
    pb.update("M", yes=[[55, 100]], no=[[45, 100]])
    f = pb.try_fill("M", "yes", limit_price=55, count=2)  # buy yes, marketable at 55
    assert f["filled"] == 2 and f["price"] == 55


def test_unmarketable_limit_no_fill():
    pb = PaperBook()
    pb.update("M", yes=[[60, 100]], no=[[40, 100]])
    f = pb.try_fill("M", "yes", limit_price=55, count=2)
    assert f["filled"] == 0


def test_partial_fill_limited_by_resting_size():
    pb = PaperBook()
    pb.update("M", yes=[[55, 3]], no=[[45, 100]])
    f = pb.try_fill("M", "yes", limit_price=55, count=10)
    assert f["filled"] == 3 and f["price"] == 55


def test_simulate_fills_updates_position_and_releases_market_guard(tmp_path):
    pm, st = _pm(tmp_path)
    # entry recorded (shadow-paper): one working order for M, guard now blocks M
    pm.execute_entries([TradeIntent("M", "yes", 55, 2, 0.7, 0.15)], "2026-05-17")
    assert len(st.list_working_orders()) == 1
    pb = PaperBook()
    pb.update("M", yes=[[55, 100]], no=[[45, 100]])
    n = simulate_fills(pm, pb, "2026-05-17")  # apply paper fills
    assert n >= 1
    assert st.list_working_orders() == []  # guard RELEASED (clear_working_orders_for_market called)
    p = st.get_position("M")
    assert p is not None and p["count"] == 2 and p["side"] == "yes" and p["avg_entry_cents"] == 55
    # second entry at a NEW price now allowed (market no longer guard-blocked)
    pm.execute_entries([TradeIntent("M", "yes", 60, 3, 0.7, 0.20)], "2026-05-17")
    assert len(st.list_working_orders()) == 1


def test_simulate_fills_records_fill_and_flips_order_status(tmp_path):
    """Each paper fill writes a fills row and marks orders.status='filled'.

    Without this, settle_day and the gate can't see what actually traded — the
    bot's bookkeeping silently loses every paper round-trip.
    """
    pm, st = _pm(tmp_path)
    pm.execute_entries([TradeIntent("M", "yes", 55, 2, 0.7, 0.15)], "2026-05-17")
    # Grab the client_id of the working order so we can verify its status flip.
    working = st.list_working_orders()
    assert len(working) == 1
    client_id = working[0]["client_id"]
    assert st.get_order(client_id)["status"] == "submitted"
    assert st.list_fills() == []

    pb = PaperBook()
    pb.update("M", yes=[[55, 100]], no=[[45, 100]])
    n = simulate_fills(pm, pb, "2026-05-17")

    assert n == 1
    # Fill row persisted with the broker-side price (55), not the limit-price (also 55 here).
    fills = st.list_fills()
    assert len(fills) == 1
    assert fills[0]["client_id"] == client_id
    assert fills[0]["market"] == "M"
    assert fills[0]["count"] == 2
    assert fills[0]["price"] == 55
    # Order status flipped.
    assert st.get_order(client_id)["status"] == "filled"
