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
CREATE TABLE IF NOT EXISTS positions(
  market TEXT PRIMARY KEY, side TEXT, count INT, avg_entry_cents INT,
  climate_date TEXT, updated_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS working_orders(
  client_id TEXT PRIMARY KEY, market TEXT, side TEXT, price INT, count INT,
  mode TEXT, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS calibration(
  station TEXT PRIMARY KEY, bias REAL, spread_scale REAL, n INT,
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

    def upsert_position(
        self,
        market: str,
        side: str,
        count: int,
        avg_entry_cents: int,
        climate_date: str,
    ) -> None:
        self.conn.execute(
            "INSERT INTO positions(market,side,count,avg_entry_cents,climate_date)"
            " VALUES(?,?,?,?,?)"
            " ON CONFLICT(market) DO UPDATE SET"
            " side=excluded.side, count=excluded.count,"
            " avg_entry_cents=excluded.avg_entry_cents,"
            " climate_date=excluded.climate_date, updated_at=datetime('now')",
            (market, side, count, avg_entry_cents, climate_date),
        )
        self.conn.commit()

    def get_position(self, market: str) -> Optional[dict]:
        r = self.conn.execute(
            "SELECT * FROM positions WHERE market=?", (market,)
        ).fetchone()
        return dict(r) if r else None

    def list_positions(self) -> list[dict]:
        return [
            dict(r) for r in self.conn.execute("SELECT * FROM positions").fetchall()
        ]

    def record_working_order(
        self,
        client_id: str,
        market: str,
        side: str,
        price: int,
        count: int,
        mode: str,
    ) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO working_orders(client_id,market,side,price,count,mode)"
            " VALUES(?,?,?,?,?,?)",
            (client_id, market, side, price, count, mode),
        )
        self.conn.commit()

    def list_working_orders(self) -> list[dict]:
        return [
            dict(r)
            for r in self.conn.execute("SELECT * FROM working_orders").fetchall()
        ]

    def clear_working_order(self, client_id: str) -> None:
        self.conn.execute(
            "DELETE FROM working_orders WHERE client_id=?", (client_id,)
        )
        self.conn.commit()

    def set_calibration(
        self, station: str, bias: float, spread_scale: float, n: int
    ) -> None:
        self.conn.execute(
            "INSERT INTO calibration(station,bias,spread_scale,n) VALUES(?,?,?,?)"
            " ON CONFLICT(station) DO UPDATE SET"
            " bias=excluded.bias, spread_scale=excluded.spread_scale,"
            " n=excluded.n, updated_at=datetime('now')",
            (station, bias, spread_scale, n),
        )
        self.conn.commit()

    def get_calibration(self, station: str) -> Optional[dict]:
        r = self.conn.execute(
            "SELECT * FROM calibration WHERE station=?", (station,)
        ).fetchone()
        return dict(r) if r else None
