"""Tests for kaiju.runner.run_intraday_once.

All I/O is injected via the Deps object — no network, no real Kalshi/IEM/Herbie,
no real asyncio WS. The tick is deterministic.
"""

from __future__ import annotations

from kaiju.runner import run_intraday_once


class Deps:
    """Injected test doubles so the runner tick is deterministic."""

    def __init__(self) -> None:
        self.placed: list = []
        self.exited: list = []

    def fair_prices(self) -> dict[str, int]:
        return {"MID": 70}

    def quotes(self) -> dict:
        from kaiju.types import MarketQuote

        return {"MID": MarketQuote("MID", 50, 55, 45, 50, 500, 1000)}

    def positions(self) -> dict:
        return {}

    def place(self, intents, climate_date: str) -> None:  # type: ignore[override]
        self.placed += intents

    def exit_decisions(self) -> dict:
        return {}  # market -> ExitDecision

    def apply_exits(self, decisions: dict, climate_date: str) -> None:
        self.exited.append(decisions)


def test_one_tick_enters_mispriced_market(tmp_path):
    d = Deps()
    res = run_intraday_once(
        station="NYC",
        climate_date="2026-05-17",
        db_path=str(tmp_path / "s.sqlite"),
        mode="shadow-paper",
        deps=d,
        net_edge_threshold=0.08,
        min_open_interest=100,
    )
    assert len(d.placed) >= 1  # fair 70 vs yes_ask 55 -> entered
    assert res["station"] == "NYC" and "report" in res


def test_tick_with_position_applies_exit_decisions(tmp_path):
    from kaiju.types import ExitAction, ExitDecision, Position

    d = Deps()
    d.positions = lambda: {"MID": Position("MID", "yes", 2, 55, "2026-05-17")}  # type: ignore[method-assign]
    d.exit_decisions = lambda: {  # type: ignore[method-assign]
        "MID": ExitDecision(ExitAction.EXIT, 68, "converged")
    }
    run_intraday_once(
        station="NYC",
        climate_date="2026-05-17",
        db_path=str(tmp_path / "s.sqlite"),
        mode="shadow-paper",
        deps=d,
        net_edge_threshold=0.08,
        min_open_interest=100,
    )
    assert d.exited and d.exited[0]["MID"].action is ExitAction.EXIT
    assert d.placed == []  # already positioned -> no new entry


def test_kill_switch_blocks_all_entries(tmp_path):
    """Kill-switch file present -> RiskGate rejects all entries; placed stays empty."""
    ks = tmp_path / "KILL"
    ks.write_text("stop")

    d = Deps()
    res = run_intraday_once(
        station="NYC",
        climate_date="2026-05-17",
        db_path=str(tmp_path / "s.sqlite"),
        mode="shadow-paper",
        deps=d,
        net_edge_threshold=0.08,
        min_open_interest=100,
        kill_switch_path=str(ks),
    )
    assert d.placed == [], f"expected no entries with kill-switch; got {d.placed}"
    assert res["n_entries"] == 0


def test_cut_decision_limit_patched_from_quote_bid(tmp_path):
    """CUT decision with limit=None gets patched with the quote bid for the held side."""
    from kaiju.types import Position, ExitDecision, ExitAction

    d = Deps()
    d.positions = lambda: {"MID": Position("MID", "yes", 2, 55, "2026-05-17")}  # type: ignore[method-assign]
    d.exit_decisions = lambda: {"MID": ExitDecision(ExitAction.CUT, None, "thesis")}  # type: ignore[method-assign]

    run_intraday_once(
        station="NYC",
        climate_date="2026-05-17",
        db_path=str(tmp_path / "s.sqlite"),
        mode="shadow-paper",
        deps=d,
        net_edge_threshold=0.08,
        min_open_interest=100,
    )

    assert d.exited, "apply_exits should have been called"
    applied = d.exited[0]["MID"]
    assert applied.action is ExitAction.CUT
    # Runner must have patched in the yes_bid from the quote (50 cents from Deps.quotes).
    assert applied.limit_price_cents is not None, "limit_price_cents must be patched from quote bid"
    assert applied.limit_price_cents == 50  # yes_bid from MarketQuote("MID", 50, ...)
