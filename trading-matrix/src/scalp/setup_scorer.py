"""Nyao-style setup score, evaluated on closed candles only.

The forming-bar blend in the EA would repaint. EnableNewBarEntryOnly is the
live default, so the score used here is the weighted average of the last N
closed bars (the EA's "base"), with no forming candle.
"""

from __future__ import annotations

import os

import numpy as np

EMA_FAST = 5
EMA_SLOW = 12
RSI_PERIOD = 8
ATR_PERIOD = 8
ATR_AVG = 10
SLOPE_LOOKBACK = 3
BODY_LOOKBACK = 10
IMPULSE_LOOKBACK = 3
SMOOTH_N = 2


def _ema(values: np.ndarray, period: int) -> np.ndarray:
    out = np.full(len(values), np.nan)
    if len(values) < period:
        return out
    alpha = 2.0 / (period + 1.0)
    out[period - 1] = float(np.mean(values[:period]))
    for i in range(period, len(values)):
        out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]
    return out


def _wilder_atr(high, low, close, period: int) -> np.ndarray:
    n = len(close)
    atr = np.full(n, np.nan)
    if n < 2:
        return atr
    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    if n <= period:
        return atr
    atr[period] = float(np.mean(tr[1 : period + 1]))
    alpha = 1.0 / period
    for i in range(period + 1, n):
        atr[i] = (1 - alpha) * atr[i - 1] + alpha * tr[i]
    return atr


def _rsi(close: np.ndarray, period: int) -> np.ndarray:
    rsi = np.full(len(close), np.nan)
    if len(close) <= period:
        return rsi
    delta = np.diff(close)
    gain = np.maximum(delta, 0.0)
    loss = np.maximum(-delta, 0.0)
    avg_g = float(np.mean(gain[:period]))
    avg_l = float(np.mean(loss[:period]))
    alpha = 1.0 / period

    def val(ag, al):
        if al == 0:
            return 100.0 if ag > 0 else 50.0
        rs = ag / al
        return 100.0 - 100.0 / (1.0 + rs)

    rsi[period] = val(avg_g, avg_l)
    for i in range(period, len(delta)):
        avg_g = (1 - alpha) * avg_g + alpha * gain[i]
        avg_l = (1 - alpha) * avg_l + alpha * loss[i]
        rsi[i + 1] = val(avg_g, avg_l)
    return rsi


def min_signal_score() -> float:
    return float(os.getenv("MIN_SIGNAL_SCORE", "4.5"))


def min_vol_ratio() -> float:
    return float(os.getenv("MIN_VOL_RATIO", "0.6"))


def prepare(candles: list[dict]) -> dict:
    close = np.array([c["close"] for c in candles], dtype=float)
    high = np.array([c["high"] for c in candles], dtype=float)
    low = np.array([c["low"] for c in candles], dtype=float)
    open_ = np.array([c["open"] for c in candles], dtype=float)
    return {
        "close": close,
        "high": high,
        "low": low,
        "open": open_,
        "ema_fast": _ema(close, EMA_FAST),
        "ema_slow": _ema(close, EMA_SLOW),
        "rsi": _rsi(close, RSI_PERIOD),
        "atr": _wilder_atr(high, low, close, ATR_PERIOD),
    }


def raw_score_at(prep: dict, i: int, side: str) -> dict:
    """side is UP or DOWN. Returns component dict; score 0 when the market is dead."""
    close = prep["close"]
    high = prep["high"]
    low = prep["low"]
    open_ = prep["open"]
    atr = prep["atr"]
    if i < ATR_AVG or np.isnan(prep["ema_fast"][i]) or np.isnan(prep["ema_slow"][i]) or np.isnan(atr[i]):
        return {"score": 0.0, "dead": False, "trend": 0.0, "momentum": 0.0, "chop": 0.0, "peak": 0.0, "volatility": 0.0, "penalty": 0.0, "atr": 0.0}
    window = atr[i - ATR_AVG + 1 : i + 1]
    avg_atr = float(np.mean(window))
    vol_ratio = float(atr[i] / avg_atr) if avg_atr > 0 else 0.0
    if min_vol_ratio() > 0 and vol_ratio > 0 and vol_ratio < min_vol_ratio():
        return {
            "score": 0.0,
            "dead": True,
            "trend": 0.0,
            "momentum": 0.0,
            "chop": 0.0,
            "peak": 0.0,
            "volatility": 0.0,
            "penalty": 0.0,
            "atr": float(atr[i]),
            "avg_atr": avg_atr,
            "vol_ratio": vol_ratio,
        }
    is_buy = side == "UP"
    ema_fast = float(prep["ema_fast"][i])
    ema_slow = float(prep["ema_slow"][i])
    ema_prev = float(prep["ema_fast"][i - SLOPE_LOOKBACK])
    trend = 0.0
    if is_buy and ema_fast > ema_slow:
        trend += 1.5
    if (not is_buy) and ema_fast < ema_slow:
        trend += 1.5
    if is_buy and ema_fast > ema_prev:
        trend += 1.5
    if (not is_buy) and ema_fast < ema_prev:
        trend += 1.5
    trend = min(trend, 3.0)

    bodies = np.abs(close[i - BODY_LOOKBACK : i] - open_[i - BODY_LOOKBACK : i])
    avg_body = float(np.mean(bodies)) if len(bodies) else 0.0
    current_body = abs(float(close[i] - open_[i]))
    rsi = float(prep["rsi"][i]) if not np.isnan(prep["rsi"][i]) else 50.0
    base = 0.0
    if is_buy:
        if 50 < rsi < 80:
            base += 1.0
        if rsi > 60:
            base += 0.5
        if current_body > avg_body:
            base += 1.5
    else:
        if 20 < rsi < 50:
            base += 1.0
        if rsi < 40:
            base += 0.5
        if current_body > avg_body:
            base += 1.5
    body_accel = min(3.0, current_body / avg_body) if avg_body > 0 else 0.0
    ranges = high[i - BODY_LOOKBACK : i] - low[i - BODY_LOOKBACK : i]
    avg_range = float(np.mean(ranges)) if len(ranges) else 0.0
    current_range = float(high[i] - low[i])
    range_accel = min(3.0, current_range / avg_range) if avg_range > 0 else 0.0
    same = 0
    for k in range(IMPULSE_LOOKBACK):
        j = i - k
        bull = close[j] > open_[j]
        bear = close[j] < open_[j]
        if is_buy and bull:
            same += 1
        elif (not is_buy) and bear:
            same += 1
        else:
            break
    continuity = same / IMPULSE_LOOKBACK
    raw_impulse = (0.5 * body_accel + 0.3 * range_accel + 0.2 * continuity) / 2.0
    raw_impulse = min(1.0, max(0.0, raw_impulse))
    momentum = min(3.0, base * (1.0 + raw_impulse))

    if vol_ratio > 1.0:
        chop = 2.0
    elif vol_ratio > 0.8:
        chop = 1.0
    else:
        chop = 0.0
    volatility = 1.0 if vol_ratio > 1.2 else 0.0
    if is_buy:
        local = float(np.max(high[i - 5 : i]))
        peak = 1.0 if close[i] > local else 0.0
    else:
        local = float(np.min(low[i - 5 : i]))
        peak = 1.0 if close[i] < local else 0.0
    upper = float(high[i] - max(open_[i], close[i]))
    lower_wick = float(min(open_[i], close[i]) - low[i])
    safe_body = max(current_body, avg_body * 1.5)
    rejection = 0.0
    if safe_body > 0:
        rejection = (upper if is_buy else lower_wick) / safe_body
    penalty = rejection * 1.0
    score = trend + momentum + chop + peak + volatility - penalty
    score = min(10.0, max(0.0, score))
    return {
        "score": float(score),
        "dead": False,
        "trend": float(trend),
        "momentum": float(momentum),
        "chop": float(chop),
        "peak": float(peak),
        "volatility": float(volatility),
        "penalty": float(penalty),
        "atr": float(atr[i]),
        "avg_atr": avg_atr,
        "vol_ratio": vol_ratio,
        "impulse": float(raw_impulse),
    }


def smoothed_score(prep: dict, i: int, side: str, n: int = SMOOTH_N) -> dict:
    weights = []
    acc = 0.0
    wsum = 0.0
    latest = raw_score_at(prep, i, side)
    for k in range(1, n + 1):
        idx = i - k + 1
        if idx < 0:
            continue
        # k=1 is the most recent closed bar (weight N)
        weight = float(n - k + 1)
        part = raw_score_at(prep, idx, side)
        acc += part["score"] * weight
        wsum += weight
        weights.append(part)
    base = acc / wsum if wsum else 0.0
    latest = dict(latest)
    # A dead bar scores 0. Smoothing must not revive it from the previous bar.
    latest["score"] = 0.0 if latest.get("dead") else float(min(10.0, max(0.0, base)))
    latest["smoothed"] = True
    return latest


def score_both(candles: list[dict]) -> list[dict]:
    prep = prepare(candles)
    out = []
    for i in range(len(candles)):
        buy = smoothed_score(prep, i, "UP") if i > 20 else {"score": 0.0, "dead": False, "atr": 0.0, "avg_atr": 0.0}
        sell = smoothed_score(prep, i, "DOWN") if i > 20 else {"score": 0.0, "dead": False, "atr": 0.0, "avg_atr": 0.0}
        if buy["score"] >= sell["score"]:
            side = "UP"
            chosen = buy
        else:
            side = "DOWN"
            chosen = sell
        out.append({"side": side, "buy": buy, "sell": sell, "chosen": chosen, "atr": chosen.get("atr") or buy.get("atr") or 0.0, "avg_atr": chosen.get("avg_atr") or buy.get("avg_atr") or 0.0})
    return out
