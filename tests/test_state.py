from kaiju.state import State


def test_state_roundtrip(tmp_path):
    db = State(str(tmp_path / "s.sqlite"))
    db.init_schema()
    db.record_prediction("KNYC", "2026-05-16", low_f=50, probs=[0.2, 0.8])
    p = db.get_prediction("KNYC", "2026-05-16")
    assert p["low_f"] == 50 and p["probs"] == [0.2, 0.8]

    db.record_order(client_id="c1", market="M", side="yes", price=40, count=2, mode="shadow-paper")
    assert db.get_order("c1")["count"] == 2
    db.record_order(client_id="c1", market="M", side="yes", price=40, count=2, mode="shadow-paper")
    assert len(db.list_orders()) == 1   # idempotent on client_id

    db.set_gate_status("qualified", brier=0.18, pnl=12.5)
    assert db.get_gate_status()["status"] == "qualified"
