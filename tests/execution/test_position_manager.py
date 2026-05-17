import asyncio

from kaiju.execution.position_manager import PositionManager
from kaiju.state import State
from kaiju.types import ExitAction, ExitDecision, TradeIntent


class FakeKalshi:
    def __init__(self):
        self.created = []
        self.cancelled = []
        self._positions = []

    def create_order(self, **kw):
        self.created.append(kw)
        return {"order_id": "o-" + kw["client_order_id"]}

    def cancel_order(self, order_id):
        self.cancelled.append(order_id)
        return {"ok": True}

    def get_positions(self):
        return list(self._positions)


def _pm(tmp, mode):
    st = State(str(tmp / "s.sqlite"))
    st.init_schema()
    return PositionManager(mode=mode, kalshi=FakeKalshi(), state=st), st


def test_shadow_paper_records_not_sends(tmp_path):
    pm, st = _pm(tmp_path, "shadow-paper")
    pm.execute_entries([TradeIntent("M", "yes", 55, 2, 0.7, 0.15)], "2026-05-17")
    assert pm.kalshi.created == []  # NOT sent to broker
    assert len(st.list_working_orders()) == 1  # recorded


def test_live_sends_once_idempotent(tmp_path):
    pm, st = _pm(tmp_path, "live")
    i = [TradeIntent("M", "yes", 55, 2, 0.7, 0.15)]
    pm.execute_entries(i, "2026-05-17")
    pm.execute_entries(i, "2026-05-17")
    assert len(pm.kalshi.created) == 1  # idempotent client id


def test_execute_exits_cut_and_exit(tmp_path):
    pm, st = _pm(tmp_path, "live")
    st.upsert_position("M", "yes", 3, 50, "2026-05-17")
    pm.execute_exits({"M": ExitDecision(ExitAction.EXIT, 68, "converged")}, "2026-05-17")
    assert len(pm.kalshi.created) == 1 and pm.kalshi.created[0]["action"] == "sell"
    pm.execute_exits({"M": ExitDecision(ExitAction.HOLD, None, "gap open")}, "2026-05-17")
    assert len(pm.kalshi.created) == 1  # HOLD does nothing


def test_reconcile_is_async_and_syncs_positions(tmp_path):
    pm, st = _pm(tmp_path, "live")
    pm.kalshi._positions = [
        {
            "ticker": "M",
            "side": "yes",
            "count": 4,
            "avg_entry_cents": 47,
            "climate_date": "2026-05-17",
        }
    ]
    asyncio.run(pm.reconcile())  # MUST be awaitable
    p = st.get_position("M")
    assert p["count"] == 4 and p["avg_entry_cents"] == 47


def test_exit_not_reissued_while_working_order_open(tmp_path):
    pm, st = _pm(tmp_path, "live")
    st.upsert_position("M", "yes", 3, 50, "2026-05-17")
    pm.execute_exits({"M": ExitDecision(ExitAction.EXIT, 68, "converged")}, "2026-05-17")
    pm.execute_exits({"M": ExitDecision(ExitAction.EXIT, 66, "converged")}, "2026-05-17")  # drifted price, same position
    sells = [c for c in pm.kalshi.created if c.get("action") == "sell"]
    assert len(sells) == 1  # NOT 2 -> no oversell


def test_entry_burst_guarded_to_one_per_market(tmp_path):
    pm, st = _pm(tmp_path, "live")
    pm.execute_entries([TradeIntent("M", "yes", 55, 2, 0.7, 0.15)], "2026-05-17")
    pm.execute_entries([TradeIntent("M", "yes", 54, 2, 0.7, 0.16)], "2026-05-17")  # drifted ask, no fill yet
    pm.execute_entries([TradeIntent("M", "yes", 56, 2, 0.7, 0.15)], "2026-05-17")
    buys = [c for c in pm.kalshi.created if c.get("action") == "buy"]
    assert len(buys) == 1  # one in-flight order per market


def test_clear_working_orders_for_market_releases_guard(tmp_path):
    pm, st = _pm(tmp_path, "live")
    pm.execute_entries([TradeIntent("M", "yes", 55, 2, 0.7, 0.15)], "2026-05-17")
    assert len([c for c in pm.kalshi.created if c.get("action") == "buy"]) == 1
    pm.clear_working_orders_for_market("M")  # simulate fill/cancel released
    assert st.list_working_orders() == []
    pm.execute_entries([TradeIntent("M", "yes", 55, 2, 0.7, 0.15)], "2026-05-17")
    # NOTE: still deduped by orders-ledger client_id (same price/count) -> still 1
    # so use a different price to prove a NEW order can be placed after release:
    pm.execute_entries([TradeIntent("M", "yes", 60, 2, 0.7, 0.20)], "2026-05-17")
    assert len([c for c in pm.kalshi.created if c.get("action") == "buy"]) == 2


def test_cut_without_limit_logs_warning(tmp_path, caplog):
    pm, st = _pm(tmp_path, "live")
    st.upsert_position("M", "yes", 3, 50, "2026-05-17")
    import logging
    with caplog.at_level(logging.WARNING):
        pm.execute_exits({"M": ExitDecision(ExitAction.CUT, None, "thesis invalidated")}, "2026-05-17")
    assert any("avg_entry" in r.message or "marketable" in r.message for r in caplog.records)
