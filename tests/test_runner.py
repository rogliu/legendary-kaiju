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
