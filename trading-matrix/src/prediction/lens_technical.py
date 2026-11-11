"""Technical lens: RSI, MACD, Bollinger. Causal series used by live and backtest."""

from __future__ import annotations

import numpy as np

from src.prediction.schemas import LensResult


def _ema(values: np.ndarray, period: int) -> np.ndarray:
    out = np.full(len(values), np.nan)
    if len(values) < period:
        return out
    alpha = 2.0 / (period + 1.0)
    out[period - 1] = float(np.mean(values[:period]))
    for i in range(period, len(values)):
        out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]
    return out


def rsi_wilder(closes: np.ndarray, period: int = 14) -> np.ndarray:
    closes = np.asarray(closes, dtype=float)
    rsi = np.full(len(closes), np.nan)
    if len(closes) <= period:
        return rsi
    delta = np.diff(closes)
    gain = np.maximum(delta, 0.0)
    loss = np.maximum(-delta, 0.0)
    avg_g = float(np.mean(gain[:period]))
    avg_l = float(np.mean(loss[:period]))
    alpha = 1.0 / period

    def _value(ag: float, al: float) -> float:
        if al == 0.0:
            return 100.0 if ag > 0.0 else 50.0
        rs = ag / al
        return 100.0 - 100.0 / (1.0 + rs)

    rsi[period] = _value(avg_g, avg_l)
    for i in range(period, len(delta)):
        avg_g = (1.0 - alpha) * avg_g + alpha * gain[i]
        avg_l = (1.0 - alpha) * avg_l + alpha * loss[i]
        rsi[i + 1] = _value(avg_g, avg_l)
    return rsi


def macd_parts(closes: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    closes = np.asarray(closes, dtype=float)
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd = ema12 - ema26
    # EMA9 of macd, skipping leading nans
    hist = np.full(len(closes), np.nan)
    signal = np.full(len(closes), np.nan)
    valid = np.where(~np.isnan(macd))[0]
    if len(valid) < 9:
        return macd, signal, hist
    start = int(valid[0])
    series = macd[start:]
    sig = _ema(series, 9)
    signal[start:] = sig
    hist[start:] = macd[start:] - sig
    return macd, signal, hist


def bollinger(closes: np.ndarray, period: int = 20, nstd: float = 2.0):
    closes = np.asarray(closes, dtype=float)
    mid = np.full(len(closes), np.nan)
    upper = np.full(len(closes), np.nan)
    lower = np.full(len(closes), np.nan)
    if len(closes) < period:
        return mid, upper, lower
    csum = np.cumsum(closes)
    csum2 = np.cumsum(closes * closes)
    for i in range(period - 1, len(closes)):
        if i == period - 1:
            s = csum[i]
            s2 = csum2[i]
        else:
            s = csum[i] - csum[i - period]
            s2 = csum2[i] - csum2[i - period]
        mean = s / period
        var = max(s2 / period - mean * mean, 0.0)
        std = var ** 0.5
        mid[i] = mean
        upper[i] = mean + nstd * std
        lower[i] = mean - nstd * std
    return mid, upper, lower


def _rsi_signal(rsi: float) -> tuple[str, float]:
    if np.isnan(rsi):
        return "SIDEWAYS", 0.0
    if rsi > 70:
        direction = "DOWN"
    elif rsi < 30:
        direction = "UP"
    else:
        direction = "SIDEWAYS"
    return direction, float(abs(rsi - 50.0) / 50.0)


def _macd_signal(hist: np.ndarray, i: int) -> tuple[str, float]:
    if i < 1 or np.isnan(hist[i]):
        return "SIDEWAYS", 0.0
    start = max(1, i - 3)
    last = None
    for j in range(start, i + 1):
        if np.isnan(hist[j]) or np.isnan(hist[j - 1]):
            continue
        if hist[j - 1] <= 0.0 < hist[j]:
            last = "UP"
        elif hist[j - 1] >= 0.0 > hist[j]:
            last = "DOWN"
    window = hist[max(0, i - 49) : i + 1]
    window = window[~np.isnan(window)]
    denom = float(np.max(np.abs(window))) if len(window) else 0.0
    conf = 0.0 if denom == 0.0 else float(abs(hist[i]) / denom)
    return (last or "SIDEWAYS"), conf


def _bb_signal(price: float, mid: float, upper: float, lower: float) -> tuple[str, float]:
    if any(np.isnan(v) for v in (mid, upper, lower)):
        return "SIDEWAYS", 0.0
    width = upper - lower
    if width <= 0:
        return "SIDEWAYS", 0.1
    from_lower = (price - lower) / width
    from_upper = (upper - price) / width
    if from_lower <= 0.10:
        direction = "UP"
    elif from_upper <= 0.10:
        direction = "DOWN"
    else:
        direction = "SIDEWAYS"
    half = width / 2.0
    frac = min(1.0, abs(price - mid) / half) if half > 0 else 0.0
    conf = 0.1 + 0.8 * frac
    return direction, float(conf)


def combine_signals(parts: list[tuple[str, float]]) -> tuple[str, float]:
    directions = [d for d, _ in parts]
    winner = "SIDEWAYS"
    for candidate in ("UP", "DOWN", "SIDEWAYS"):
        if directions.count(candidate) >= 2:
            winner = candidate
            break
    agreeing = [c for d, c in parts if d == winner]
    if not agreeing:
        agreeing = [c for _, c in parts] or [0.0]
    return winner, float(sum(agreeing) / len(agreeing))


def technical_at(closes: np.ndarray, i: int | None = None) -> tuple[str, float, str, dict]:
    closes = np.asarray(closes, dtype=float)
    if i is None:
        i = len(closes) - 1
    rsi = rsi_wilder(closes)
    _, _, hist = macd_parts(closes)
    mid, upper, lower = bollinger(closes)
    rsi_d, rsi_c = _rsi_signal(float(rsi[i]) if i < len(rsi) else np.nan)
    macd_d, macd_c = _macd_signal(hist, i)
    bb_d, bb_c = _bb_signal(
        float(closes[i]),
        float(mid[i]),
        float(upper[i]),
        float(lower[i]),
    )
    direction, conf = combine_signals([(rsi_d, rsi_c), (macd_d, macd_c), (bb_d, bb_c)])
    rsi_v = None if np.isnan(rsi[i]) else round(float(rsi[i]), 4)
    hist_v = None if np.isnan(hist[i]) else round(float(hist[i]), 6)
    reasoning = (
        f"RSI={rsi_v} verdict {rsi_d}; "
        f"MACD_hist={hist_v} verdict {macd_d}; "
        f"Bollinger close={float(closes[i]):.6g} mid={None if np.isnan(mid[i]) else round(float(mid[i]), 6)} "
        f"upper={None if np.isnan(upper[i]) else round(float(upper[i]), 6)} "
        f"lower={None if np.isnan(lower[i]) else round(float(lower[i]), 6)} verdict {bb_d}"
    )
    raw = {
        "rsi": rsi_v,
        "rsi_direction": rsi_d,
        "rsi_confidence": rsi_c,
        "macd_hist": hist_v,
        "macd_direction": macd_d,
        "macd_confidence": macd_c,
        "bb_direction": bb_d,
        "bb_confidence": bb_c,
    }
    return direction, conf, reasoning, raw


def run_technical(closes) -> LensResult:
    direction, conf, reasoning, raw = technical_at(np.asarray(closes, dtype=float))
    return LensResult("technical", direction, conf, reasoning, raw)
