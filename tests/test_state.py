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


def test_record_fill_and_list(tmp_path):
    db = State(str(tmp_path / "s.sqlite"))
    db.init_schema()
    db.record_order(client_id="c1", market="M", side="yes", price=40, count=2, mode="shadow-paper")

    db.record_fill(client_id="c1", market="M", price=39, count=2)

    fills = db.list_fills()
    assert len(fills) == 1
    f = fills[0]
    assert f["client_id"] == "c1" and f["market"] == "M"
    assert f["price"] == 39 and f["count"] == 2


def test_record_fill_allows_partials(tmp_path):
    """Two fills against the same client_id (partial-fill case) — both rows kept."""
    db = State(str(tmp_path / "s.sqlite"))
    db.init_schema()
    db.record_order(client_id="c1", market="M", side="yes", price=40, count=10, mode="shadow-paper")

    db.record_fill(client_id="c1", market="M", price=39, count=3)
    db.record_fill(client_id="c1", market="M", price=39, count=7)

    fills = db.get_fills_for_order("c1")
    assert len(fills) == 2
    assert sum(f["count"] for f in fills) == 10


def test_mark_order_filled_flips_status(tmp_path):
    db = State(str(tmp_path / "s.sqlite"))
    db.init_schema()
    db.record_order(client_id="c1", market="M", side="yes", price=40, count=2, mode="shadow-paper")
    assert db.get_order("c1")["status"] == "submitted"

    db.mark_order_filled("c1")

    assert db.get_order("c1")["status"] == "filled"


# ---------------------------------------------------------------------------
# Task 0005: orders carry a buy/sell action (so paper exits reduce positions and
# settle_day can later pair round-trips). Direction is a property of the order.
# ---------------------------------------------------------------------------


def test_orders_record_and_read_action(tmp_path):
    db = State(str(tmp_path / "s.sqlite"))
    db.init_schema()
    db.record_order(client_id="b1", market="M", side="yes", price=40, count=2,
                    mode="shadow-paper", action="buy")
    db.record_order(client_id="s1", market="M", side="yes", price=55, count=2,
                    mode="shadow-paper", action="sell")
    assert db.get_order("b1")["action"] == "buy"
    assert db.get_order("s1")["action"] == "sell"


def test_record_order_action_defaults_to_buy(tmp_path):
    db = State(str(tmp_path / "s.sqlite"))
    db.init_schema()
    db.record_order(client_id="c1", market="M", side="yes", price=40, count=2,
                    mode="shadow-paper")
    assert db.get_order("c1")["action"] == "buy"


def test_orders_action_migration_adds_column_and_is_idempotent(tmp_path):
    """An existing orders table without `action` is migrated; re-running is safe."""
    import sqlite3

    db_path = str(tmp_path / "old.sqlite")
    conn = sqlite3.connect(db_path)
    conn.executescript(
        "CREATE TABLE orders(client_id TEXT PRIMARY KEY, market TEXT, side TEXT,"
        " price INT, count INT, mode TEXT, status TEXT DEFAULT 'submitted',"
        " created_at TEXT DEFAULT (datetime('now')));"
    )
    conn.commit()
    conn.close()

    st = State(db_path)
    st.init_schema()  # must ALTER orders to add the action column
    cols = [r[1] for r in st.conn.execute("PRAGMA table_info(orders)").fetchall()]
    assert "action" in cols

    st.init_schema()  # idempotent — running the migration again must not error
    st.record_order(client_id="c1", market="M", side="yes", price=40, count=2,
                    mode="shadow-paper", action="sell")
    assert st.get_order("c1")["action"] == "sell"
