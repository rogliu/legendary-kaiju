from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Optional
import numpy as np

@dataclass(frozen=True)
class TempPMF:
    """Discrete PMF over integer °F for the official NWS daily max."""
    low_f: int
    probs: np.ndarray  # probs[i] = P(temp == low_f + i)

    @property
    def high_f(self) -> int:
        return self.low_f + len(self.probs) - 1

    @classmethod
    def from_probs(cls, low_f: int, probs) -> "TempPMF":
        arr = np.asarray(probs, dtype=float)
        if (arr < 0).any():
            raise ValueError("PMF has negative mass")
        total = arr.sum()
        if total <= 0:
            raise ValueError("PMF mass is non-positive")
        return cls(low_f=int(low_f), probs=arr / total)

    def prob_at(self, t: int) -> float:
        i = t - self.low_f
        return float(self.probs[i]) if 0 <= i < len(self.probs) else 0.0

    def prob_interval(self, lo: Optional[int], hi: Optional[int]) -> float:
        temps = np.arange(self.low_f, self.high_f + 1)
        mask = np.ones(len(temps), dtype=bool)
        if lo is not None:
            mask &= temps >= lo
        if hi is not None:
            mask &= temps <= hi
        return float(self.probs[mask].sum())

@dataclass(frozen=True)
class Bucket:
    market_ticker: str
    lower_f: Optional[float]   # None = open low tail
    upper_f: Optional[float]   # None = open high tail (inclusive bounds)

    def contains(self, t: float) -> bool:
        if self.lower_f is not None and t < self.lower_f:
            return False
        if self.upper_f is not None and t > self.upper_f:
            return False
        return True

@dataclass(frozen=True)
class MarketQuote:
    market_ticker: str
    yes_bid: Optional[int]
    yes_ask: Optional[int]
    no_bid: Optional[int]
    no_ask: Optional[int]
    volume: int
    open_interest: int

@dataclass(frozen=True)
class EventSnapshot:
    event_ticker: str
    station_id: str
    climate_date: str            # ISO date in the station's climate-day tz
    buckets: list[Bucket]
    quotes: dict[str, MarketQuote]

@dataclass(frozen=True)
class TradeIntent:
    market_ticker: str
    side: Literal["yes", "no"]
    limit_price_cents: int
    count: int
    model_prob: float
    net_edge: float

@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str
    adjusted_count: int
