from __future__ import annotations
import os
from kaiju.types import TradeIntent, RiskDecision

class RiskGate:
    def __init__(self, kill_switch_path: str, max_contracts_per_market: int,
                 max_open_exposure_usd: float, max_daily_loss_usd: float,
                 bankroll_usd: float):
        # Fix A: reject empty/None kill_switch_path at construction (fail-closed)
        if not kill_switch_path:
            raise ValueError("kill_switch_path must be a non-empty string")
        self.kill = kill_switch_path
        self.max_ct = max_contracts_per_market
        self.max_exp = max_open_exposure_usd
        self.max_loss = max_daily_loss_usd
        self.bankroll = bankroll_usd

    def check(self, intent: TradeIntent, realized_loss_today_usd: float,
              open_exposure_usd: float) -> RiskDecision:
        # 1. kill-switch
        if os.path.exists(self.kill):
            return RiskDecision(False, "kill switch engaged", 0)
        # 2. daily-loss (>=)
        if realized_loss_today_usd >= self.max_loss:
            return RiskDecision(False, "daily loss limit reached", 0)
        # 3. None / zero-count intent
        if intent is None or intent.count < 1:
            return RiskDecision(False, "no tradeable intent", 0)
        # Fix E: price sanity guard (Kalshi prices are 1..99 cents)
        if not (1 <= intent.limit_price_cents <= 99):
            return RiskDecision(False, f"price out of range: {intent.limit_price_cents}", 0)
        # Fix F: reject corrupted negative open exposure
        if open_exposure_usd < 0:
            return RiskDecision(False, "invalid open exposure (<0)", 0)
        # per-market clamp
        count = min(intent.count, self.max_ct)
        # Fix B: zero contracts after clamp → reject
        if count < 1:
            return RiskDecision(False, "zero contracts after per-market clamp", 0)
        add = count * intent.limit_price_cents / 100.0
        # Fix D: exposure cap is fail-safe at equality (>=)
        if open_exposure_usd + add >= self.max_exp:
            return RiskDecision(False, "open exposure cap exceeded", 0)
        # Fix C: bankroll check includes open exposure
        if open_exposure_usd + add > self.bankroll:
            return RiskDecision(False, "exceeds bankroll", 0)
        return RiskDecision(True, "ok", count)
