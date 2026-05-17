from kaiju.state import State


def test_position_and_working_order_and_calibration(tmp_path):
    db = State(str(tmp_path / "s.sqlite"))
    db.init_schema()
    db.upsert_position("M", "yes", 3, 45, "2026-05-17")
    db.upsert_position("M", "yes", 5, 46, "2026-05-17")  # idempotent upsert (latest wins)
    p = db.get_position("M")
    assert p["count"] == 5 and p["avg_entry_cents"] == 46
    db.record_working_order("c1", "M", "yes", 55, 1, "shadow-paper")
    db.record_working_order("c1", "M", "yes", 55, 1, "shadow-paper")
    assert len(db.list_working_orders()) == 1  # idempotent client_id
    db.clear_working_order("c1")
    assert db.list_working_orders() == []
    db.set_calibration("KNYC", bias=-1.2, spread_scale=1.05, n=40)
    db.set_calibration("KNYC", bias=-0.8, spread_scale=1.10, n=55)  # upsert latest
    c = db.get_calibration("KNYC")
    assert c["bias"] == -0.8 and c["n"] == 55
    assert db.get_position("NONE") is None and db.get_calibration("NONE") is None
    assert db.list_positions()[0]["market"] == "M"
