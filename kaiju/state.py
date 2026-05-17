from __future__ import annotations

import json
import sqlite3
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions(
  station TEXT, climate_date TEXT, low_f INT, probs TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  PRIMARY KEY(station, climate_date));
CREATE TABLE IF NOT EXISTS orders(
  client_id TEXT PRIMARY KEY, market TEXT, side TEXT, price INT, count INT,
  mode TEXT, status TEXT DEFAULT 'submitted', created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS fills(
  client_id TEXT, market TEXT, price INT, count INT, ts TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS pnl(
  climate_date TEXT PRIMARY KEY, realized_usd REAL, mode TEXT);
CREATE TABLE IF NOT EXISTS gate(
  id INT PRIMARY KEY CHECK (id=1), status TEXT, brier REAL, pnl REAL,
  updated_at TEXT DEFAULT (datetime('now')));
"""


class State:
    def __init__(self, path: str) -> None:
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row

    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def record_prediction(
        self, station: str, climate_date: str, low_f: int, probs: list[float]
    ) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO predictions(station,climate_date,low_f,probs)"
            " VALUES(?,?,?,?)",
            (station, climate_date, low_f, json.dumps(list(probs))),
        )
        self.conn.commit()

    def get_prediction(self, station: str, climate_date: str) -> Optional[dict]:
        r = self.conn.execute(
            "SELECT * FROM predictions WHERE station=? AND climate_date=?",
            (station, climate_date),
        ).fetchone()
        if not r:
            return None
        d = dict(r)
        d["probs"] = json.loads(d["probs"])
        return d

    def record_order(
        self,
        client_id: str,
        market: str,
        side: str,
        price: int,
        count: int,
        mode: str,
    ) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO orders(client_id,market,side,price,count,mode)"
            " VALUES(?,?,?,?,?,?)",
            (client_id, market, side, price, count, mode),
        )
        self.conn.commit()

    def get_order(self, client_id: str) -> Optional[dict]:
        r = self.conn.execute(
            "SELECT * FROM orders WHERE client_id=?", (client_id,)
        ).fetchone()
        return dict(r) if r else None

    def list_orders(self) -> list[dict]:
        return [
            dict(r) for r in self.conn.execute("SELECT * FROM orders").fetchall()
        ]

    def set_gate_status(self, status: str, brier: float, pnl: float) -> None:
        self.conn.execute(
            "INSERT INTO gate(id,status,brier,pnl) VALUES(1,?,?,?)"
            " ON CONFLICT(id) DO UPDATE SET"
            " status=?,brier=?,pnl=?,updated_at=datetime('now')",
            (status, brier, pnl, status, brier, pnl),
        )
        self.conn.commit()

    def get_gate_status(self) -> Optional[dict]:
        r = self.conn.execute("SELECT * FROM gate WHERE id=1").fetchone()
        return dict(r) if r else None
