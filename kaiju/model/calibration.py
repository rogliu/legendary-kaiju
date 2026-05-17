from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from kaiju.types import TempPMF


@dataclass(frozen=True)
class CalibrationParams:
    bias: float
    spread_scale: float
    n_samples: int


def fit_calibration(fc_medians, realized, min_samples: int) -> CalibrationParams:
    fc = np.asarray(fc_medians, float)
    ob = np.asarray(realized, float)
    if fc.shape != ob.shape:
        raise ValueError(f"fc_medians and realized must have equal length, got {fc.shape} vs {ob.shape}")
    n = len(fc)
    raw_bias = float(np.mean(ob - fc)) if n else 0.0
    shrink = n / (n + min_samples) if (n + min_samples) > 0 else 0.0
    bias = shrink * raw_bias
    if n >= 2:
        std_fc = float(np.std(fc))
        if std_fc < 1e-6:
            scale = 1.0   # no forecast spread => cannot estimate a ratio
        else:
            err = ob - fc - raw_bias
            raw_scale = float(np.std(err) / std_fc)
            if raw_scale == 0.0:
                raw_scale = 1.0
            scale = 1.0 + shrink * (raw_scale - 1.0)
    else:
        scale = 1.0
    return CalibrationParams(bias=bias, spread_scale=max(0.5, min(scale, 3.0)), n_samples=n)


def apply_calibration(pmf: TempPMF, cal: CalibrationParams) -> TempPMF:
    temps = np.arange(pmf.low_f, pmf.high_f + 1, dtype=float)
    mean = float((temps * pmf.probs).sum())
    new_temps = mean + cal.bias + (temps - mean) * cal.spread_scale
    lo = int(np.floor(new_temps.min()))
    hi = int(np.ceil(new_temps.max()))
    grid = np.arange(lo, hi + 1)
    acc = np.zeros(len(grid))
    idx = np.clip(np.round(new_temps).astype(int) - lo, 0, len(grid) - 1)
    np.add.at(acc, idx, pmf.probs)
    return TempPMF.from_probs(low_f=lo, probs=acc)
