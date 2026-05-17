from __future__ import annotations
import numpy as np
from kaiju.types import TempPMF

def nowcast_pmf(base: TempPMF, observed_max_f: int, minutes_past_peak: int,
                remaining_forecast_max_f: int | None) -> TempPMF:
    """Condition the calibrated daily-max PMF on intraday observations.

    - Left-truncate at observed_max_f (daily max cannot be below it).
    - Cap the upside at the still-attainable max: if past the peak hour
      (minutes_past_peak >= 0) the ceiling is max(observed, remaining
      forecast); pre-peak the ceiling is max(observed, remaining forecast
      max), falling back to the base high when remaining_forecast_max_f
      is None. Mass outside [floor, ceil] is removed and the distribution
      renormalized (no artificial point mass) -- except when the
      observation falls entirely outside model support, in which case a
      degenerate point mass at observed_max_f is returned.

    minutes_past_peak is reserved for future tuning; the ceiling formula is currently identical regardless of its sign.
    """
    temps = np.arange(base.low_f, base.high_f + 1)
    floor = observed_max_f
    if remaining_forecast_max_f is None:
        ceil = base.high_f
    else:
        ceil = max(observed_max_f, remaining_forecast_max_f)
    mask = (temps >= floor) & (temps <= ceil)
    w = np.where(mask, base.probs, 0.0)
    if w.sum() <= 0:
        return TempPMF.from_probs(low_f=observed_max_f, probs=[1.0])
    return TempPMF.from_probs(low_f=base.low_f, probs=w)
