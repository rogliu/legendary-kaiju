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
  mode TEXT, status TEXT DEFAULT 'submitted', action TEXT DEFAULT 'buy',
  created_at TEXT DEFAULT (datetime('now')));
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
CREATE TABLE IF NOT EXISTS settlements(
  climate_date TEXT, station TEXT, realized_max INT, mode TEXT,
  updated_at TEXT DEFAULT (datetime('now')),
  PRIMARY KEY(climate_date, station));
"""


class State:
    def __init__(self, path: str) -> None:
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row

    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """Idempotent column migrations for DBs created before a column existed.

        ``CREATE TABLE IF NOT EXISTS`` does not add columns to a pre-existing
        table, so a persisted ``kaiju.sqlite`` from before ``orders.action``
        existed needs the column added explicitly. Safe to run on every startup.
        """
        order_cols = {
            r[1] for r in self.conn.execute("PRAGMA table_info(orders)").fetchall()
        }
        if "action" not in order_cols:
            self.conn.execute(
                "ALTER TABLE orders ADD COLUMN action TEXT DEFAULT 'buy'"
            )

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
        action: str = "buy",
    ) -> None:
        """Record an order in the idempotency ledger.

        ``action`` is ``"buy"`` (entry) or ``"sell"`` (exit) — the direction the
        paper-fill simulator and ``settle_day`` use to tell entries from exits.
        """
        self.conn.execute(
            "INSERT OR IGNORE INTO orders(client_id,market,side,price,count,mode,action)"
            " VALUES(?,?,?,?,?,?,?)",
            (client_id, market, side, price, count, mode, action),
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
        """Wholesale-replace the position row; caller must pass the POST-aggregation total count and weighted avg_entry_cents (NOT a single fill)."""
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

    def delete_position(self, market: str) -> None:
        """Remove a position row (used when the broker reports the market flat)."""
        self.conn.execute("DELETE FROM positions WHERE market=?", (market,))
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

    def record_settlement(
        self, climate_date: str, station: str, realized_max: int, mode: str
    ) -> None:
        """Upsert a settlement row recording the official realized max for a climate_date.

        Columns: climate_date + station (PK), realized_max, mode, updated_at.
        Called by settle_day after official_daily_max is resolved (success path only).
        The LookupError / not-ready path writes neither pnl, settlement, nor gate.
        """
        self.conn.execute(
            "INSERT INTO settlements(climate_date, station, realized_max, mode)"
            " VALUES(?,?,?,?)"
            " ON CONFLICT(climate_date, station) DO UPDATE SET"
            " realized_max=excluded.realized_max, mode=excluded.mode,"
            " updated_at=datetime('now')",
            (climate_date, station, realized_max, mode),
        )
        self.conn.commit()

    def get_settlement(self, climate_date: str, station: str) -> Optional[dict]:
        """Return the settlement row for (climate_date, station), or None if absent."""
        r = self.conn.execute(
            "SELECT * FROM settlements WHERE climate_date=? AND station=?",
            (climate_date, station),
        ).fetchone()
        return dict(r) if r else None

    def list_settlements(self) -> list[dict]:
        """Return all settlement rows ordered by climate_date ascending."""
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM settlements ORDER BY climate_date"
            ).fetchall()
        ]

    def record_fill(
        self, client_id: str, market: str, price: int, count: int
    ) -> None:
        """Append a fill row. Multiple fills per client_id are allowed (partial fills).

        Persisting fills creates the audit trail that ``settle_day`` and the gate's
        ``sim_pnl_usd`` metric have lacked: without this, even successful paper trades
        leave no record that they happened. Each call adds a row — callers are expected
        to also call ``mark_order_filled`` once the order is fully consumed.
        """
        self.conn.execute(
            "INSERT INTO fills(client_id, market, price, count) VALUES(?,?,?,?)",
            (client_id, market, price, count),
        )
        self.conn.commit()

    def list_fills(self) -> list[dict]:
        """Return all fills ordered by timestamp ascending."""
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM fills ORDER BY ts"
            ).fetchall()
        ]

    def get_fills_for_order(self, client_id: str) -> list[dict]:
        """Return fills for a specific client_id ordered by timestamp ascending."""
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM fills WHERE client_id=? ORDER BY ts", (client_id,)
            ).fetchall()
        ]

    def mark_order_filled(self, client_id: str) -> None:
        """Flip an order's status from 'submitted' to 'filled'.

        Idempotent: if the row is already 'filled' the UPDATE is a no-op. If the
        client_id doesn't exist (shouldn't happen given the ``record_order`` →
        ``record_fill`` → ``mark_order_filled`` ordering) the UPDATE affects 0 rows
        silently — callers should not rely on this for existence checks.
        """
        self.conn.execute(
            "UPDATE orders SET status='filled' WHERE client_id=?", (client_id,)
        )
        self.conn.commit()

    def record_pnl(self, climate_date: str, realized_usd: float, mode: str) -> None:
        """Upsert a pnl row for the given climate_date.

        Columns written: climate_date (PK), realized_usd, mode.
        These EXACTLY match the columns queried by runner._realized_loss_today:
            SELECT realized_usd FROM pnl WHERE climate_date=? AND mode=?
        Writing this row activates the RiskGate daily-loss limit (previously inert).

        Note: climate_date is the sole PRIMARY KEY so one row is kept per date.
        If mode changes between settlement runs the last writer wins (upsert).
        """
        self.conn.execute(
            "INSERT INTO pnl(climate_date, realized_usd, mode) VALUES(?,?,?)"
            " ON CONFLICT(climate_date) DO UPDATE SET"
            " realized_usd=excluded.realized_usd, mode=excluded.mode",
            (climate_date, realized_usd, mode),
        )
        self.conn.commit()
