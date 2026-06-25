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


# ---------------------------------------------------------------------------
# Task 0002: incremental orderbook_delta application (full-depth book)
#
# Before this task PaperBook stored only top-of-book and deltas were dropped,
# so the shadow-paper book silently diverged from the real stream between
# snapshots — biasing simulated fills and thus the paper-proof. These tests
# pin: snapshots fully replace, deltas mutate incrementally (add / modify /
# remove-to-zero), an orphan delta never corrupts the book, and top-of-book
# (what try_fill uses) tracks the resulting levels.
# ---------------------------------------------------------------------------


def test_snapshot_stores_full_depth_not_just_top():
    pb = PaperBook()
    pb.update("M", yes=[[96, 100], [95, 30]], no=[[3, 50]])
    assert pb.levels("M", "yes") == {96: 100, 95: 30}
    assert pb.levels("M", "no") == {3: 50}


def test_delta_modifies_existing_level_incrementally():
    pb = PaperBook()
    pb.update("M", yes=[[96, 100], [95, 30]], no=[[3, 50]])
    applied = pb.apply_delta("M", "yes", 96, 50)  # +50 at an existing level
    assert applied is True
    # Incremental: 96 grew to 150 and the 95 level is untouched. A wholesale
    # replace-with-payload (the old bug) would have wiped the 95 level.
    assert pb.levels("M", "yes") == {96: 150, 95: 30}


def test_delta_adds_new_level():
    pb = PaperBook()
    pb.update("M", yes=[[96, 100]], no=[[3, 50]])
    pb.apply_delta("M", "yes", 94, 25)  # a new price level appears
    assert pb.levels("M", "yes") == {96: 100, 94: 25}


def test_delta_adds_level_on_seeded_side_absent_from_snapshot():
    pb = PaperBook()
    pb.update("M", yes=[[96, 100]], no=[[3, 50]])
    pb.apply_delta("M", "no", 5, 20)  # 'no' side present; add a deeper level
    assert pb.levels("M", "no") == {3: 50, 5: 20}


def test_delta_removes_level_at_zero():
    pb = PaperBook()
    pb.update("M", yes=[[96, 100], [95, 30]], no=[[3, 50]])
    pb.apply_delta("M", "yes", 96, -100)  # exactly to zero -> level removed
    assert pb.levels("M", "yes") == {95: 30}


def test_delta_overdraw_removes_level_never_negative():
    pb = PaperBook()
    pb.update("M", yes=[[96, 100]], no=[[3, 50]])
    pb.apply_delta("M", "yes", 96, -250)  # more than present -> removed, not negative
    assert pb.levels("M", "yes") == {}


def test_delta_before_snapshot_dropped_and_book_uncorrupted():
    """Orphan delta (market not seeded) must NOT create a phantom level."""
    pb = PaperBook()
    applied = pb.apply_delta("M", "yes", 96, 50)
    assert applied is False  # signalled: needs resync (await fresh snapshot)
    assert pb.levels("M", "yes") == {}  # book uncorrupted
    assert pb.try_fill("M", "yes", limit_price=99, count=5)["filled"] == 0


def test_snapshot_fully_replaces_book():
    pb = PaperBook()
    pb.update("M", yes=[[96, 100]], no=[[3, 50]])
    pb.update("M", yes=[[50, 20]], no=[[40, 10]])  # a later full snapshot
    assert pb.levels("M", "yes") == {50: 20}  # old 96 level gone (full replace)
    assert pb.levels("M", "no") == {40: 10}


def test_snapshot_with_empty_side_clears_that_side():
    """A snapshot is the full authoritative state: an empty side clears stale depth."""
    pb = PaperBook()
    pb.update("M", yes=[[96, 100]], no=[[3, 50]])
    pb.update("M", yes=[[95, 80]], no=[])  # snapshot now reports no 'no' levels
    assert pb.levels("M", "yes") == {95: 80}
    assert pb.levels("M", "no") == {}  # fully replaced — stale 'no' depth gone


def test_try_fill_tracks_top_of_book_after_delta():
    """A delta adding a higher resting level moves the price try_fill uses."""
    pb = PaperBook()
    pb.update("M", yes=[[50, 100]], no=[[3, 50]])
    # Before: top-of-book yes = 50; a buy at 50 is marketable.
    assert pb.try_fill("M", "yes", limit_price=50, count=5) == {"filled": 5, "price": 50}
    pb.apply_delta("M", "yes", 96, 10)  # a higher resting level appears
    # After: top-of-book yes = 96; the same 50-limit buy is no longer marketable.
    assert pb.try_fill("M", "yes", limit_price=50, count=5)["filled"] == 0
    assert pb.try_fill("M", "yes", limit_price=96, count=5) == {"filled": 5, "price": 96}
