from __future__ import annotations
import os
from kaiju.types import TradeIntent, RiskDecision

class RiskGate:
    def __init__(self, kill_switch_path: str, max_contracts_per_market: int,
                 max_open_exposure_usd: float, max_daily_loss_usd: float,
                 bankroll_usd: float):
        self.kill = kill_switch_path
        self.max_ct = max_contracts_per_market
        self.max_exp = max_open_exposure_usd
        self.max_loss = max_daily_loss_usd
        self.bankroll = bankroll_usd

    def check(self, intent: TradeIntent, realized_loss_today_usd: float,
              open_exposure_usd: float) -> RiskDecision:
        if os.path.exists(self.kill):
            return RiskDecision(False, "kill switch engaged", 0)
        if realized_loss_today_usd >= self.max_loss:
            return RiskDecision(False, "daily loss limit reached", 0)
        if intent is None or intent.count < 1:
            return RiskDecision(False, "no tradeable intent", 0)
        count = min(intent.count, self.max_ct)
        add = count * intent.limit_price_cents / 100.0
        if open_exposure_usd + add > self.max_exp:
            return RiskDecision(False, "open exposure cap exceeded", 0)
        if add > self.bankroll:
            return RiskDecision(False, "exceeds bankroll", 0)
        return RiskDecision(True, "ok", count)
