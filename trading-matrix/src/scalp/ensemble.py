"""Six freqtrade entry conditions, long-only, as published.

A strategy fires UP or stays silent. Direction is the majority of the
strategies that fired. Confidence is firing_count / 6. No fire → silent.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.prediction.schemas import LensResult


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_g = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_l = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_g / avg_l.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _cci(df: pd.DataFrame, period: int) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    sma = tp.rolling(period).mean()
    mad = (tp - sma).abs().rolling(period).mean()
    return (tp - sma) / (0.015 * mad.replace(0, np.nan))


def _stoch(df: pd.DataFrame, k_period: int = 5, d_period: int = 3):
    low = df["low"].rolling(k_period).min()
    high = df["high"].rolling(k_period).max()
    fastk = 100 * (df["close"] - low) / (high - low).replace(0, np.nan)
    fastd = fastk.rolling(d_period).mean()
    return fastk, fastd


def _mfi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    rmf = tp * df["volume"]
    pos = rmf.where(tp > tp.shift(1), 0.0)
    neg = rmf.where(tp < tp.shift(1), 0.0)
    mr = pos.rolling(period).sum() / neg.rolling(period).sum().replace(0, np.nan)
    return 100 - 100 / (1 + mr)


def _bb(series: pd.Series, window: int, nstd: float):
    mid = series.rolling(window).mean()
    std = series.rolling(window).std(ddof=0)
    return mid - nstd * std, mid, mid + nstd * std


def _supertrend_up(df: pd.DataFrame, multiplier: float, period: int) -> pd.Series:
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    close = df["close"].to_numpy()
    tr = np.zeros(len(df))
    tr[0] = high[0] - low[0]
    for i in range(1, len(df)):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    atr = pd.Series(tr).rolling(period).mean().to_numpy()
    basic_ub = (high + low) / 2 + multiplier * atr
    basic_lb = (high + low) / 2 - multiplier * atr
    final_ub = np.zeros(len(df))
    final_lb = np.zeros(len(df))
    for i in range(period, len(df)):
        final_ub[i] = basic_ub[i] if basic_ub[i] < final_ub[i - 1] or close[i - 1] > final_ub[i - 1] else final_ub[i - 1]
        final_lb[i] = basic_lb[i] if basic_lb[i] > final_lb[i - 1] or close[i - 1] < final_lb[i - 1] else final_lb[i - 1]
    st = np.zeros(len(df))
    for i in range(period, len(df)):
        if st[i - 1] == final_ub[i - 1]:
            st[i] = final_ub[i] if close[i] <= final_ub[i] else final_lb[i]
        elif st[i - 1] == final_lb[i - 1]:
            st[i] = final_lb[i] if close[i] >= final_lb[i] else final_ub[i]
        else:
            st[i] = final_lb[i] if close[i] >= final_lb[i] else final_ub[i]
    up = (st > 0) & (close >= st)
    return pd.Series(up, index=df.index)


def _frame(candles: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(candles)


def fires(candles: list[dict]) -> dict[str, str | None]:
    """Return strategy name → 'UP' or None on the last closed bar."""
    if len(candles) < 80:
        return {name: None for name in ("Strategy001", "Strategy003", "Strategy005", "Bandtastic", "Supertrend", "SwingHighToSky")}
    df = _frame(candles)
    out: dict[str, str | None] = {}

    ema20 = _ema(df["close"], 20)
    ema50 = _ema(df["close"], 50)
    ha_close = (df["open"] + df["high"] + df["low"] + df["close"]) / 4
    ha_open = ha_close.copy()
    ha_open.iloc[0] = (df["open"].iloc[0] + df["close"].iloc[0]) / 2
    for i in range(1, len(df)):
        ha_open.iloc[i] = (ha_open.iloc[i - 1] + ha_close.iloc[i - 1]) / 2
    cross = ema20.iloc[-2] <= ema50.iloc[-2] and ema20.iloc[-1] > ema50.iloc[-1]
    out["Strategy001"] = "UP" if cross and ha_close.iloc[-1] > ema20.iloc[-1] and ha_open.iloc[-1] < ha_close.iloc[-1] else None

    rsi = _rsi(df["close"])
    mfi = _mfi(df)
    fastk, fastd = _stoch(df)
    fisher = (np.exp(0.2 * (rsi - 50)) - 1) / (np.exp(0.2 * (rsi - 50)) + 1)
    ema5 = _ema(df["close"], 5)
    ema10 = _ema(df["close"], 10)
    ema100 = _ema(df["close"], 100)
    sma40 = df["close"].rolling(40).mean()
    tp = (df["high"] + df["low"] + df["close"]) / 3
    bb_lower, _, _ = _bb(tp, 20, 2)
    cond3 = (
        rsi.iloc[-1] < 28
        and rsi.iloc[-1] > 0
        and df["close"].iloc[-1] < sma40.iloc[-1]
        and fisher.iloc[-1] < -0.94
        and mfi.iloc[-1] < 16
        and (ema50.iloc[-1] > ema100.iloc[-1] or (ema5.iloc[-2] <= ema10.iloc[-2] and ema5.iloc[-1] > ema10.iloc[-1]))
        and fastd.iloc[-1] > fastk.iloc[-1]
        and fastd.iloc[-1] > 0
    )
    out["Strategy003"] = "UP" if bool(cond3) else None

    # Strategy005 buy_params override the defaults.
    vol_avg = df["volume"].rolling(150).mean()
    fisher_norm = 50 * (fisher + 1)
    cond5 = (
        df["close"].iloc[-1] > 0.000002
        and df["volume"].iloc[-1] > vol_avg.iloc[-1] * 4
        and df["close"].iloc[-1] < sma40.iloc[-1]
        and fastd.iloc[-1] > fastk.iloc[-1]
        and rsi.iloc[-1] > 26
        and fastd.iloc[-1] > 1
        and fisher_norm.iloc[-1] < 5
    )
    out["Strategy005"] = "UP" if bool(cond5) else None

    bb1_lower, _, _ = _bb(tp, 20, 1)
    cond_b = df["close"].iloc[-1] < bb1_lower.iloc[-1] and df["volume"].iloc[-1] > 0
    out["Bandtastic"] = "UP" if bool(cond_b) else None

    st1 = _supertrend_up(df, 4, 8)
    st2 = _supertrend_up(df, 7, 9)
    st3 = _supertrend_up(df, 1, 8)
    out["Supertrend"] = "UP" if bool(st1.iloc[-1] and st2.iloc[-1] and st3.iloc[-1] and df["volume"].iloc[-1] > 0) else None

    cci = _cci(df, 72)
    rsi36 = _rsi(df["close"], 36)
    out["SwingHighToSky"] = "UP" if bool(cci.iloc[-1] < -175 and rsi36.iloc[-1] < 90) else None
    return out


def majority(votes: dict[str, str | None]) -> LensResult | None:
    firing = [d for d in votes.values() if d in ("UP", "DOWN")]
    if not firing:
        return None
    up = firing.count("UP")
    down = firing.count("DOWN")
    if up == down:
        return None
    direction = "UP" if up > down else "DOWN"
    conf = len(firing) / 6.0
    return LensResult(
        "ensemble",
        direction,
        conf,
        f"firing {len(firing)}/6 direction {direction}",
        {"votes": votes, "silent": False, "firing_count": len(firing)},
    )


def ensemble_lens(candles: list[dict]) -> LensResult | None:
    return majority(fires(candles))
