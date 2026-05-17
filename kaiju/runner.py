"""Intraday runner / orchestrator for the Kaiju Kalshi weather-temp bot.

Public API
----------
run_intraday_once(station, climate_date, db_path, mode, deps, net_edge_threshold,
                  min_open_interest, *, kelly_fraction, bankroll_usd, max_bankroll_frac,
                  max_contracts_per_market, max_open_exposure_usd, max_daily_loss_usd,
                  kill_switch_path) -> dict
    ONE deterministic evaluation tick with all I/O injected via deps.
    Safe to call from tests without any network or env vars.

run_intraday(station, mode, *, settings=None) -> None
    Production wiring: constructs real clients, WS, loops.
    Heavy imports (herbie, websockets, httpx) are deferred inside this
    function so offline tests never trigger them.

CLI (python -m kaiju.runner):
    run      --station --mode
    settle   (stub; implemented in Task 18)
    retrain  (stub; implemented in Task 19)

Cross-task contracts honoured
------------------------------
1. select_trades (v1) is DELETED from edge.py; only select_gap_trades used here.
2. WsClient on_connect_reconcile = pm.reconcile (async def) — passed directly.
3. Paper-proof: shadow-paper fill path uses simulate_fills(pm, paper_book, climate_date)
   which calls clear_working_orders_for_market per filled market; live fill events also
   call pm.clear_working_orders_for_market(market).
4. OI source: quotes/buckets from parse_event_snapshot(list_markets(...)); never from
   get_quote (which always returns OI=0).
5. CUT exits: runner builds an explicit limit_price_cents from the current quote (the
   bid of the held side) before calling execute_exits, so PositionManager never needs
   the avg_entry fallback for CUT decisions.
6. IEM errors: LookupError -> data not ready (log + skip); httpx errors -> transient
   (log + backoff). The two exception types are not conflated.
7. Multi-city / unmapped series: resolve_settlement raises KeyError on unknown tickers,
   which propagates loud — intentional, not suppressed.

Known v1 limitations
---------------------
- Daily-loss realized-PnL source is not yet wired (Task 18 will add the pnl table).
  Until then, RiskGate's daily-loss kill is INERT. See run_intraday for loud warnings.
- orderbook_delta WS messages are currently applied as snapshots (v1 limitation);
  incremental delta application is deferred to a future task.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from kaiju.state import State
from kaiju.strategy.edge import select_gap_trades
from kaiju.strategy.sizing import size_event
from kaiju.risk.limits import RiskGate
from kaiju.types import ExitAction, ExitDecision

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Conservative defaults used when caller does not override sizing/risk params.
# These keep run_intraday_once env-free (no Settings construction).
# ---------------------------------------------------------------------------
_DEFAULT_KELLY = 0.25
_DEFAULT_BANKROLL = 500.0
_DEFAULT_MAX_FRAC = 0.10
_DEFAULT_MAX_CT = 50
_DEFAULT_MAX_EXP = 250.0   # 50% of default bankroll
_DEFAULT_MAX_LOSS = 50.0
_DEFAULT_KILL_PATH = "/tmp/kaiju_kill"

# Named constant for min_open_interest default (Fix #7 — no magic literal in loop).
_DEFAULT_MIN_OPEN_INTEREST = 100


# ---------------------------------------------------------------------------
# Deterministic tick (all IO via deps)
# ---------------------------------------------------------------------------

def run_intraday_once(
    station: str,
    climate_date: str,
    db_path: str,
    mode: str,
    deps: Any,
    net_edge_threshold: float,
    min_open_interest: int,
    *,
    kelly_fraction: float = _DEFAULT_KELLY,
    bankroll_usd: float = _DEFAULT_BANKROLL,
    max_bankroll_frac: float = _DEFAULT_MAX_FRAC,
    max_contracts_per_market: int = _DEFAULT_MAX_CT,
    max_open_exposure_usd: float = _DEFAULT_MAX_EXP,
    max_daily_loss_usd: float = _DEFAULT_MAX_LOSS,
    kill_switch_path: str | None = None,
) -> dict:
    """Execute one evaluation tick; all side-effects via deps.

    Parameters
    ----------
    station:
        Human-readable station identifier (for reporting / state keys).
    climate_date:
        ISO date string for the trading day (e.g. "2026-05-17").
    db_path:
        Path to the SQLite state file; will be created if absent.
    mode:
        "shadow-paper", "backtest", or "live".
    deps:
        Injected I/O provider.  Must expose:
          .fair_prices()    -> dict[str, int]       fair cents per ticker
          .quotes()         -> dict[str, MarketQuote]
          .positions()      -> dict[str, Position]
          .place(intents, climate_date) -> None     called with sized+approved entries
          .exit_decisions() -> dict[str, ExitDecision]
          .apply_exits(decisions, climate_date) -> None
    net_edge_threshold:
        Minimum net edge (fraction) for a trade to be accepted.
    min_open_interest:
        Minimum open interest for a market to be considered.
    kill_switch_path:
        Optional path to kill-switch file (overrides the default /tmp/kaiju_kill).
        Passing a path to an existing file will block all entries — useful in tests.

    Returns
    -------
    dict with keys: station, climate_date, mode, n_entries, n_exits, report
    """
    # Resolve kill-switch path (optional override for testing, default otherwise).
    ks_path = kill_switch_path if kill_switch_path is not None else _DEFAULT_KILL_PATH

    # Open / init state (needed for RiskGate realized-loss query).
    state = State(db_path)
    state.init_schema()

    # Gather current market picture from deps (all injected, no network).
    fair = deps.fair_prices()
    quotes = deps.quotes()
    positions = deps.positions()

    # --- Entry logic ---
    raw_intents = select_gap_trades(
        fair_cents=fair,
        quotes=quotes,
        positions=positions,
        net_edge_threshold=net_edge_threshold,
        min_open_interest=min_open_interest,
    )

    sized = size_event(
        intents=raw_intents,
        bankroll_usd=bankroll_usd,
        kelly_fraction=kelly_fraction,
        max_bankroll_frac=max_bankroll_frac,
    )

    # RiskGate: per-intent approval.
    gate = RiskGate(
        kill_switch_path=ks_path,
        max_contracts_per_market=max_contracts_per_market,
        max_open_exposure_usd=max_open_exposure_usd,
        max_daily_loss_usd=max_daily_loss_usd,
        bankroll_usd=bankroll_usd,
    )
    realized_loss = _realized_loss_today(state, climate_date, mode)
    open_exposure = _open_exposure(positions)

    approved = []
    running_exposure = open_exposure
    for intent in sized:
        dec = gate.check(intent, realized_loss, running_exposure)
        if dec.approved:
            # Adjust count if gate clamped it.
            if dec.adjusted_count != intent.count:
                from kaiju.types import TradeIntent
                intent = TradeIntent(
                    intent.market_ticker,
                    intent.side,
                    intent.limit_price_cents,
                    dec.adjusted_count,
                    intent.model_prob,
                    intent.net_edge,
                )
            approved.append(intent)
            running_exposure += intent.count * intent.limit_price_cents / 100.0
        else:
            log.debug("RiskGate rejected %s: %s", intent.market_ticker, dec.reason)

    if approved:
        deps.place(approved, climate_date)

    # --- Exit logic ---
    exit_decisions = deps.exit_decisions()
    n_exits = 0
    if exit_decisions:
        # Contract 5: CUT decisions must carry an explicit limit_price_cents.
        # If decide_exit returned CUT with limit=None, set marketable limit from
        # the quote (the bid for the side we hold, which is our sell price).
        patched: dict[str, ExitDecision] = {}
        for market, decision in exit_decisions.items():
            if decision.action == ExitAction.CUT and decision.limit_price_cents is None:
                q = quotes.get(market)
                pos = positions.get(market)
                if q is not None and pos is not None:
                    # Sell at the best bid for our side (marketable close).
                    explicit_limit = q.yes_bid if pos.side == "yes" else q.no_bid
                    if explicit_limit is not None:
                        decision = ExitDecision(
                            ExitAction.CUT,
                            explicit_limit,
                            decision.reason,
                        )
                        log.debug(
                            "CUT for %s: set explicit limit %s from quote bid",
                            market,
                            explicit_limit,
                        )
                    else:
                        log.warning(
                            "CUT for %s: no bid available in quote, leaving limit None "
                            "(PositionManager avg_entry fallback will warn)",
                            market,
                        )
            patched[market] = decision

        deps.apply_exits(patched, climate_date)
        n_exits = len([d for d in patched.values() if d.action != ExitAction.HOLD])

    return {
        "station": station,
        "climate_date": climate_date,
        "mode": mode,
        "n_entries": len(approved),
        "n_exits": n_exits,
        "report": (
            f"entries={len(approved)} exits={n_exits} "
            f"fair_tickers={list(fair.keys())}"
        ),
    }


# ---------------------------------------------------------------------------
# Helpers for run_intraday_once (no IO)
# ---------------------------------------------------------------------------

def _realized_loss_today(state: State, climate_date: str, mode: str) -> float:
    """Query today's realized loss from state. Returns 0.0 if no row exists."""
    row = state.conn.execute(
        "SELECT realized_usd FROM pnl WHERE climate_date=? AND mode=?",
        (climate_date, mode),
    ).fetchone()
    if row is None:
        return 0.0
    val = row[0]
    # loss is stored as negative; we return a positive magnitude for comparison.
    return max(0.0, -(val or 0.0))


def _open_exposure(positions: dict) -> float:
    """Estimate open exposure in USD from current positions.

    Uses avg_entry_cents * count for each position (conservative upper bound).
    Positions may be Position dataclass objects or dicts.
    """
    total = 0.0
    for pos in positions.values():
        if hasattr(pos, "avg_entry_cents"):
            total += pos.avg_entry_cents * pos.count / 100.0
        elif isinstance(pos, dict):
            total += pos.get("avg_entry_cents", 0) * pos.get("count", 0) / 100.0
    return total


# ---------------------------------------------------------------------------
# Production wiring (heavy imports deferred)
# ---------------------------------------------------------------------------

def run_intraday(station: str, mode: str, *, settings: Any = None) -> None:
    """Production orchestration loop for one trading day.

    Constructs all real clients (Kalshi REST, IEM, Herbie/GEFS, WS) and runs
    a fair-value recompute + trade loop until time-stop.

    Heavy imports (herbie, websockets, httpx) are deferred inside this function
    so offline tests that import only run_intraday_once are not affected.

    Contract references:
      2. pm.reconcile (async) passed as on_connect_reconcile — honoured below.
      3. shadow-paper: simulate_fills called after execute_entries AND execute_exits.
         live: fill WS events call pm.clear_working_orders_for_market.
      4. OI from parse_event_snapshot(list_markets(...)), never from get_quote.
      5. CUT exits: explicit limit from current quote bid before execute_exits.
      6. LookupError vs httpx errors split in IEM/forecast calls.
      7. resolve_settlement raises on unknown series — propagates loud.

    Safety note: RiskGate daily-loss limit is INERT until Task 18 wires the pnl table.
    """
    # --- Deferred heavy imports ---
    import asyncio
    import time
    from datetime import datetime

    import httpx

    from kaiju.config import Settings
    from kaiju.data.forecast import fetch_nbm_percentiles, fetch_gefs_members
    from kaiju.data.obs import IEMClient
    from kaiju.execution.paper_sim import PaperBook, simulate_fills
    from kaiju.execution.position_manager import PositionManager
    from kaiju.markets.kalshi_client import KalshiClient
    from kaiju.markets.parser import parse_event_snapshot, resolve_settlement
    from kaiju.markets.ws_client import WsClient, make_kalshi_ws_connect
    from kaiju.model.calibration import apply_calibration, CalibrationParams
    from kaiju.model.distribution import blend_pmfs, pmf_from_nbm_percentiles
    from kaiju.model.nowcast import nowcast_pmf
    from kaiju.strategy.exit_policy import decide_exit
    from kaiju.strategy.fairvalue import fair_prices as compute_fair_prices

    cfg: Any = settings or Settings()  # type: ignore[call-arg]

    # Fix #1: Loud safety warnings — pnl/daily-loss source not yet wired (Task 18).
    # This runs unconditionally before the loop so operators always see it.
    log.warning(
        "SAFETY: pnl/realized-loss source not yet wired (Task 18); "
        "RiskGate daily-loss limit is INERT."
    )
    if mode == "live":
        log.error(
            "UNSAFE: live mode with INERT daily-loss limit — "
            "do NOT run live until Task 18 pnl wiring lands."
        )

    # --- Resolve settlement metadata (raises KeyError for unknown series) ---
    # Map station human name to series ticker.
    # Contract 7: resolve_settlement must fail loud for unmapped series.
    # For NYC the series is KXHIGHNY.
    series_ticker = _station_to_series(station)
    settlement = resolve_settlement(series_ticker)
    iem_station = settlement["iem_station"]
    # iem_network reserved for future official_daily_max calls in Task 18 settle path

    # --- Build clients ---
    kalshi = KalshiClient(
        key_id=cfg.kalshi_key_id,
        private_key_pem=cfg.kalshi_private_key.get_secret_value(),
        base_url="https://external-api.kalshi.com/trade-api/v2",
    )
    iem = IEMClient()

    # --- State + PositionManager ---
    state = State(cfg.db_path)
    state.init_schema()
    pm = PositionManager(mode=mode, kalshi=kalshi, state=state)

    # --- PaperBook (used in shadow-paper; ignored in live) ---
    paper_book = PaperBook()

    # --- Derive climate_date (today in station tz) ---
    from zoneinfo import ZoneInfo  # stdlib Python 3.9+
    tz = ZoneInfo(settlement["tz"])
    climate_date = datetime.now(tz).strftime("%Y-%m-%d")

    # --- Forecast + nowcast ---
    nbm_pct: dict[float, float] | None = None
    gefs_members: list[float] | None = None
    obs_max: int | None = None
    pmf = None

    def _refresh_forecast() -> None:
        """Re-fetch forecast and nowcast; updates pmf in the enclosing scope.

        Fix #2b: uses fresh datetime.now(tz) at call time so post-startup
        NBM/GEFS runs are picked up during the trading day.
        """
        nonlocal nbm_pct, gefs_members, obs_max, pmf

        # Fix #2b: fresh local time at each recompute call (not stale startup time).
        now = datetime.now(tz)

        # NBM percentiles.
        try:
            run_dt = _latest_nbm_run(now)
            nbm_pct = fetch_nbm_percentiles(
                lat=_station_lat(station),
                lon=_station_lon360(station),
                run=run_dt,
            )
        except Exception as exc:
            log.warning("NBM fetch failed: %s", exc)

        # GEFS members.
        try:
            run_dt = _latest_gefs_run(now)
            gefs_members = fetch_gefs_members(
                lat=_station_lat(station),
                lon=_station_lon360(station),
                run=run_dt,
            )
        except Exception as exc:
            log.warning("GEFS fetch failed: %s", exc)

        if nbm_pct is None and gefs_members is None:
            log.warning("No forecast data available; skipping PMF construction.")
            return

        # Build base PMF from available data.
        parts = []
        if nbm_pct:
            parts.append((pmf_from_nbm_percentiles(nbm_pct), 0.6))
        if gefs_members:
            parts.append((_pmf_from_members(gefs_members), 0.4))
        base = blend_pmfs(parts)

        # Apply calibration if stored.
        cal_row = state.get_calibration(station)
        if cal_row is not None:
            cal = CalibrationParams(
                bias=cal_row["bias"],
                spread_scale=cal_row["spread_scale"],
                n_samples=cal_row["n"],
            )
            base = apply_calibration(base, cal)

        # Nowcast: observed max so far (contract 6 — LookupError vs httpx split).
        try:
            obs_max = iem.observed_max_so_far(iem_station, climate_date)
        except LookupError as exc:
            log.info("IEM observed_max not ready: %s", exc)
            obs_max = None
        except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as exc:
            log.warning("IEM transient error fetching obs: %s", exc)
            obs_max = None

        if obs_max is not None:
            pmf = nowcast_pmf(
                base=base,
                observed_max_f=obs_max,
                minutes_past_peak=0,
                remaining_forecast_max_f=None,
            )
        else:
            pmf = base

    # Initial forecast pull.
    _refresh_forecast()

    # --- Market snapshot (OI from list_markets — contract 4) ---
    # Build event ticker from series + climate_date.
    event_ticker = _event_ticker(series_ticker, climate_date)
    raw_markets = kalshi.list_markets(event_ticker)
    if isinstance(raw_markets, dict):
        raw_markets = raw_markets.get("markets", [])

    snapshot = parse_event_snapshot(
        event_ticker=event_ticker,
        station_id=iem_station,
        climate_date=climate_date,
        raw_markets=raw_markets,
    )

    # Live quote prices (for intraday price updates only; OI stays from snapshot).
    live_quotes: dict = dict(snapshot.quotes)  # mutable copy for WS updates

    # --- WS event handler ---
    def _on_ws_event(evt: dict) -> None:
        msg_type = evt.get("type", "")
        market_ticker = evt.get("market_ticker", "")

        if msg_type in ("orderbook_snapshot", "orderbook_delta"):
            if msg_type == "orderbook_delta":
                # v1 limitation: delta messages are applied as snapshots.
                # Incremental delta application is deferred to a future task.
                log.debug(
                    "orderbook_delta received; v1 applies snapshots only, "
                    "delta not incrementally applied"
                )

            # Update PaperBook for shadow-paper sim.
            yes_lvls = evt.get("yes_dollars_fp") or []
            no_lvls = evt.get("no_dollars_fp") or []

            # Fix #4: _lvl_to_cents returns a 2-element [price_cents, size] list.
            def _lvl_to_cents(lvl: list) -> list[int]:
                return [round(float(lvl[0]) * 100), int(float(lvl[1]))]

            paper_book.update(
                market_ticker,
                yes=[_lvl_to_cents(lvl) for lvl in yes_lvls if len(lvl) >= 2],
                no=[_lvl_to_cents(lvl) for lvl in no_lvls if len(lvl) >= 2],
            )
            # Refresh live bid/ask prices while preserving OI from snapshot.
            orig = live_quotes.get(market_ticker)
            if orig is not None and yes_lvls and no_lvls:
                from kaiju.types import MarketQuote
                yes_bid = round(float(yes_lvls[0][0]) * 100) if yes_lvls else orig.yes_bid
                no_bid = round(float(no_lvls[0][0]) * 100) if no_lvls else orig.no_bid
                yes_ask = (100 - no_bid) if no_bid is not None else orig.yes_ask
                no_ask = (100 - yes_bid) if yes_bid is not None else orig.no_ask
                live_quotes[market_ticker] = MarketQuote(
                    market_ticker=market_ticker,
                    yes_bid=yes_bid,
                    yes_ask=yes_ask,
                    no_bid=no_bid,
                    no_ask=no_ask,
                    volume=orig.volume,
                    open_interest=orig.open_interest,  # OI from snapshot, not WS
                )

        elif msg_type == "fill":
            # Contract 3 (live): release guard so the market can accept new orders.
            if market_ticker:
                pm.clear_working_orders_for_market(market_ticker)
                log.info("Fill received for %s; cleared working orders.", market_ticker)

    # --- Build WS client (contract 2: on_connect_reconcile = pm.reconcile async) ---
    market_tickers = [b.market_ticker for b in snapshot.buckets]
    ws_connect = make_kalshi_ws_connect(
        key_id=cfg.kalshi_key_id,
        private_key_pem=cfg.kalshi_private_key.get_secret_value(),
        base_ws_url="wss://external-api-ws.kalshi.com/trade-api/ws/v2",
        market_tickers=market_tickers,
    )
    ws = WsClient(
        connect=ws_connect,
        on_event=_on_ws_event,
        on_connect_reconcile=pm.reconcile,  # async def — contract 2
    )

    # Fix #5: construct RiskGate ONCE before the loop (params are frozen from cfg).
    gate = RiskGate(
        kill_switch_path="/tmp/kaiju_kill",
        max_contracts_per_market=cfg.max_contracts_per_market,
        max_open_exposure_usd=cfg.bankroll_usd * 0.5,
        max_daily_loss_usd=cfg.max_daily_loss_usd,
        bankroll_usd=cfg.bankroll_usd,
    )

    # --- Main async loop ---
    async def _main() -> None:
        RECOMPUTE_INTERVAL_S = 300   # Re-pull forecast every 5 min
        TIMESTOP_MINUTES = 30        # Stop entering N min before day ends

        ws_task = asyncio.create_task(ws.run_forever())
        last_recompute = 0.0
        timestop_reached = False

        try:
            while not timestop_reached:
                now_mono = time.monotonic()

                # Periodic forecast recompute.
                if now_mono - last_recompute >= RECOMPUTE_INTERVAL_S:
                    _refresh_forecast()
                    last_recompute = now_mono

                if pmf is None:
                    log.warning("PMF not available; sleeping before retry.")
                    await asyncio.sleep(30)
                    continue

                # Check time-stop (outside the per-tick try/except — must terminate loop).
                minutes_to_close = _minutes_to_day_close(tz)
                if minutes_to_close < TIMESTOP_MINUTES:
                    log.info(
                        "Time-stop reached (%d min to close). Stopping entries.",
                        minutes_to_close,
                    )
                    timestop_reached = True
                    ws.stop()
                    break

                # Fix #2a: wrap the trade evaluation body so one bad tick never kills
                # the day. Time-stop, WS lifecycle, and sleep stay OUTSIDE this block.
                try:
                    # Compute fair values.
                    fair = compute_fair_prices(pmf, snapshot.buckets)

                    # Current positions from state.
                    pos_rows = state.list_positions()
                    from kaiju.types import Position as _Position
                    current_positions = {
                        r["market"]: _Position(
                            market_ticker=r["market"],
                            side=r["side"],
                            count=r["count"],
                            avg_entry_cents=r["avg_entry_cents"],
                            climate_date=r["climate_date"],
                        )
                        for r in pos_rows
                        if r["count"] > 0
                    }

                    # --- Exits (contract 5: explicit CUT limit from current quote) ---
                    exit_decisions: dict = {}
                    for market, pos in current_positions.items():
                        q = live_quotes.get(market)
                        if q is None:
                            continue
                        fair_cents_for_market = fair.get(market)
                        if fair_cents_for_market is None:
                            continue
                        dec = decide_exit(
                            position=pos,
                            fair_cents=fair_cents_for_market,
                            quote=q,
                            minutes_to_timestop=minutes_to_close - TIMESTOP_MINUTES,
                            exit_margin_cents=3,
                            fill_margin_cents=1,
                        )
                        # Contract 5: patch CUT with explicit limit from quote bid.
                        if dec.action == ExitAction.CUT and dec.limit_price_cents is None:
                            bid = q.yes_bid if pos.side == "yes" else q.no_bid
                            if bid is not None:
                                dec = ExitDecision(ExitAction.CUT, bid, dec.reason)
                            else:
                                log.warning(
                                    "CUT for %s: no bid in live quote, "
                                    "PositionManager avg_entry fallback will fire.",
                                    market,
                                )
                        exit_decisions[market] = dec

                    if exit_decisions:
                        pm.execute_exits(exit_decisions, climate_date)

                        # Fix #2c: simulate_fills after exits so exit working orders
                        # get paper-filled and clear_working_orders_for_market releases
                        # the guard — otherwise markets with a placed exit are blocked.
                        if mode in ("shadow-paper", "backtest"):
                            simulate_fills(pm, paper_book, climate_date)

                    # --- Entries ---
                    raw_intents = select_gap_trades(
                        fair_cents=fair,
                        quotes=live_quotes,
                        positions=current_positions,
                        net_edge_threshold=cfg.net_edge_threshold,
                        # Fix #7: use named constant instead of magic literal 100.
                        min_open_interest=_DEFAULT_MIN_OPEN_INTEREST,
                    )
                    sized = size_event(
                        intents=raw_intents,
                        bankroll_usd=cfg.bankroll_usd,
                        kelly_fraction=cfg.kelly_fraction,
                        max_bankroll_frac=cfg.max_bankroll_frac_per_event,
                    )
                    realized_loss = _realized_loss_today(state, climate_date, mode)
                    open_exp = _open_exposure(current_positions)
                    approved_entries = []
                    running_exp = open_exp
                    for intent in sized:
                        dec_r = gate.check(intent, realized_loss, running_exp)
                        if dec_r.approved:
                            if dec_r.adjusted_count != intent.count:
                                from kaiju.types import TradeIntent
                                intent = TradeIntent(
                                    intent.market_ticker,
                                    intent.side,
                                    intent.limit_price_cents,
                                    dec_r.adjusted_count,
                                    intent.model_prob,
                                    intent.net_edge,
                                )
                            approved_entries.append(intent)
                            running_exp += intent.count * intent.limit_price_cents / 100.0

                    if approved_entries:
                        pm.execute_entries(approved_entries, climate_date)

                        # Contract 3 / Fix #2c: simulate fills after entries.
                        if mode in ("shadow-paper", "backtest"):
                            simulate_fills(pm, paper_book, climate_date)

                except Exception:  # unattended: never let one bad tick kill the day
                    log.error("tick error; continuing", exc_info=True)

                await asyncio.sleep(60)  # keep cadence regardless

        finally:
            ws.stop()
            await ws_task

    asyncio.run(_main())


# ---------------------------------------------------------------------------
# Production helpers (no IO on their own)
# ---------------------------------------------------------------------------

def _station_to_series(station: str) -> str:
    """Map a human station name to the Kalshi series ticker.

    Contract 7: fails loud for unmapped stations — caller catches KeyError.
    """
    _MAP = {
        "NYC": "KXHIGHNY",
        "KNYC": "KXHIGHNY",
    }
    if station not in _MAP:
        raise KeyError(
            f"Station {station!r} has no Kalshi series ticker mapping. "
            "Add it only after verifying the IEM station cross-check."
        )
    return _MAP[station]


def _station_lat(station: str) -> float:
    _LATS = {"NYC": 40.7790, "KNYC": 40.7790}
    return _LATS.get(station, 40.7790)


def _station_lon360(station: str) -> float:
    """Return longitude in 0-360 grid (western longitudes = lon + 360)."""
    _LONS = {"NYC": 286.0307, "KNYC": 286.0307}
    return _LONS.get(station, 286.0307)


def _event_ticker(series_ticker: str, climate_date: str) -> str:
    """Build the Kalshi event ticker for a series + date.

    Format: KXHIGHNY-26MAY17 (series + YY + MON + DD).
    """
    from datetime import date
    d = date.fromisoformat(climate_date)
    return f"{series_ticker}-{d.strftime('%y%b%d').upper()}"


def _latest_nbm_run(now_local):
    """Return the most recent NBM model run datetime (UTC, 6-hourly: 00/06/12/18Z)."""
    from datetime import timezone, timedelta
    now_utc = now_local.astimezone(timezone.utc)
    # NBM runs at 00/06/12/18Z; use the run that's at least 2h old.
    for h in (18, 12, 6, 0):
        candidate = now_utc.replace(hour=h, minute=0, second=0, microsecond=0)
        if (now_utc - candidate).total_seconds() >= 7200:
            return candidate
    # Fallback: previous day 18Z.
    prev = now_utc - timedelta(days=1)
    return prev.replace(hour=18, minute=0, second=0, microsecond=0)


def _latest_gefs_run(now_local):
    """Return the most recent GEFS model run datetime (UTC, 6-hourly: 00/06/12/18Z)."""
    return _latest_nbm_run(now_local)


def _minutes_to_day_close(tz) -> int:
    """Return minutes until midnight local time (rough proxy for daily settlement).

    Fix #6: computes datetime.now(tz) internally; no stale today_local parameter.
    """
    from datetime import datetime, timedelta
    now = datetime.now(tz)
    midnight = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return int((midnight - now).total_seconds() / 60)


def _pmf_from_members(members: list[float]):
    """Build a TempPMF from GEFS ensemble member °F values via empirical CDF."""
    import numpy as np
    from kaiju.types import TempPMF

    if not members:
        raise ValueError("GEFS members list is empty")
    arr = np.array(members, dtype=float)
    lo = int(np.floor(arr.min())) - 1
    hi = int(np.ceil(arr.max())) + 1
    grid = np.arange(lo, hi + 1, dtype=float)
    # Empirical PMF: count members in each 1°F bucket.
    probs = np.zeros(len(grid))
    for m in arr:
        idx = int(round(m)) - lo
        if 0 <= idx < len(probs):
            probs[idx] += 1.0
    return TempPMF.from_probs(low_f=lo, probs=probs)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_arg_parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m kaiju.runner",
        description="Kaiju intraday weather-temp trading bot.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- run ---
    run_p = sub.add_parser("run", help="Run the intraday bot for a station.")
    run_p.add_argument(
        "--station",
        required=True,
        help="Station identifier (e.g. NYC, KNYC).",
    )
    run_p.add_argument(
        "--mode",
        default="shadow-paper",
        choices=["shadow-paper", "backtest", "live"],
        help="Trading mode (default: shadow-paper).",
    )

    # --- settle (Task 18) ---
    settle_p = sub.add_parser(
        "settle", help="Settle completed trading days (implemented in Task 18)."
    )
    settle_p.add_argument("--station", required=True, help="Station identifier.")
    settle_p.add_argument("--date", required=True, help="Climate date (YYYY-MM-DD).")

    # --- retrain (Task 19) ---
    retrain_p = sub.add_parser(
        "retrain", help="Retrain calibration model (implemented in Task 19)."
    )
    retrain_p.add_argument("--station", required=True, help="Station identifier.")

    return parser


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    parser = _build_arg_parser()
    args = parser.parse_args()

    if args.command == "run":
        run_intraday(station=args.station, mode=args.mode)

    elif args.command == "settle":
        # Task 18 will implement settle_day; scaffold only.
        raise SystemExit(
            "settle is not yet implemented (Task 18). "
            "Run: python -m kaiju.runner settle --station NYC --date 2026-05-17"
        )

    elif args.command == "retrain":
        # Task 19 will implement retrain_calibration; scaffold only.
        raise SystemExit(
            "retrain is not yet implemented (Task 19). "
            "Run: python -m kaiju.runner retrain --station NYC"
        )

    else:
        parser.print_help()
        sys.exit(1)
