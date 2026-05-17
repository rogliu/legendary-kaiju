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
    db.record_working_order("c1","M","yes",99,999,"live")   # same client_id, different payload
    wos=db.list_working_orders()
    assert len(wos)==1 and wos[0]["price"]==55 and wos[0]["count"]==1 and wos[0]["mode"]=="shadow-paper"
    db.clear_working_order("c1")
    assert db.list_working_orders() == []
    db.set_calibration("KNYC", bias=-1.2, spread_scale=1.05, n=40)
    db.set_calibration("KNYC", bias=-0.8, spread_scale=1.10, n=55)  # upsert latest
    c = db.get_calibration("KNYC")
    assert c["bias"] == -0.8 and c["n"] == 55
    assert db.get_position("NONE") is None and db.get_calibration("NONE") is None
    assert db.list_positions()[0]["market"] == "M"


def test_upsert_position_is_wholesale_replace_not_accumulate(tmp_path):
    db=State(str(tmp_path/"s.sqlite"))
    db.init_schema()
    db.upsert_position("M","yes",3,45,"2026-05-17")
    db.upsert_position("M","yes",2,50,"2026-05-17")   # NOT additive: latest row wins
    p=db.get_position("M")
    assert p["count"]==2 and p["avg_entry_cents"]==50   # wholesale replace, not 5/47
