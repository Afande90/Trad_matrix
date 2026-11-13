"""Four markets, 2022-01-01 to 2023-12-31. Mid-price moves, measured spread as the cost.

A hold that would cross a missing minute or the weekend close is dropped.
Nothing from 2025-01-01 onward is read.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from src.backtest.cheap_futures import MINUTE_MS, WINDOW_MS, rolling_thresholds
from src.backtest.frames import daily_correlation_t, daily_total_t, pearson

COMMISSION = 0.00007
PERIOD_START = "2022-01-01"
PERIOD_END = "2024-01-01"
INSTRUMENTS = (
    ("xauusd", "Gold"),
    ("xagusd", "Silver"),
    ("lightcmdusd", "Light crude"),
    ("eurusd", "EURUSD"),
    ("gbpusd", "GBPUSD"),
    ("usdjpy", "USDJPY"),
)


def hold_crosses_weekend(start_ms: int, end_ms: int) -> bool:
    """True when the hold touches the forex weekend close (Friday 22:00 UTC through Sunday 22:00 UTC)."""
    if _closed(start_ms) or _closed(end_ms):
        return True
    start = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
    days = (4 - start.weekday()) % 7
    friday = (start + timedelta(days=days)).replace(hour=22, minute=0, second=0, microsecond=0)
    mark = int(friday.timestamp() * 1000)
    if mark <= start_ms:
        mark += 7 * 24 * 60 * MINUTE_MS
    return start_ms < mark <= end_ms


def _closed(ts: int) -> bool:
    moment = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
    weekday = moment.weekday()
    minute = moment.hour * 60 + moment.minute
    if weekday == 5:
        return True
    if weekday == 6 and minute < 22 * 60:
        return True
    if weekday == 4 and minute >= 22 * 60:
        return True
    return False


def contiguous(present: np.ndarray, base_slot: int, start_ms: int, end_ms: int) -> bool:
    """Every 1m open from start through end exists, and the hold stays inside the week."""
    if end_ms < start_ms or hold_crosses_weekend(start_ms, end_ms):
        return False
    a = int(start_ms // MINUTE_MS) - base_slot
    b = int(end_ms // MINUTE_MS) - base_slot
    if a < 0 or b >= len(present) or b < a:
        return False
    return int(present[a : b + 1].sum()) == b - a + 1


def read_side(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    raw = np.loadtxt(path, delimiter=",", skiprows=1)
    if raw.ndim != 2 or raw.shape[1] < 5:
        raise RuntimeError(f"unexpected candle file {path}")
    ts = raw[:, 0].astype(np.int64)
    if np.any(ts >= int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)):
        raise RuntimeError("a 2025 timestamp was read")
    keep = ts < int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    ts = ts[keep]
    return ts, raw[keep, 1].astype(float), raw[keep, 4].astype(float)


def join_bid_ask(bid: tuple[np.ndarray, np.ndarray, np.ndarray], ask: tuple[np.ndarray, np.ndarray, np.ndarray]) -> dict:
    bid_ts, bid_open, bid_close = bid
    ask_ts, ask_open, ask_close = ask
    common, bi, ai = np.intersect1d(bid_ts, ask_ts, return_indices=True)
    mid_open = (bid_open[bi] + ask_open[ai]) / 2.0
    mid_close = (bid_close[bi] + ask_close[ai]) / 2.0
    spread = (ask_close[ai] - bid_close[bi]) / mid_close
    good = np.isfinite(spread) & (spread > 0) & np.isfinite(mid_close) & (mid_close > 0)
    common = common[good]
    mid_open = mid_open[good]
    mid_close = mid_close[good]
    spread = spread[good]
    order = np.argsort(common)
    return {
        "ts": common[order],
        "mid_open": mid_open[order],
        "mid_close": mid_close[order],
        "spread": spread[order],
    }


def slot_tables(ts: np.ndarray, mid_open: np.ndarray, mid_close: np.ndarray) -> tuple[int, np.ndarray, np.ndarray, np.ndarray]:
    base = int(ts[0] // MINUTE_MS)
    n = int(ts[-1] // MINUTE_MS) - base + 1
    present = np.zeros(n, dtype=np.int8)
    opens = np.full(n, np.nan)
    closes = np.full(n, np.nan)
    slots = (ts // MINUTE_MS - base).astype(np.int64)
    present[slots] = 1
    opens[slots] = mid_open
    closes[slots] = mid_close
    return base, present, opens, closes


def complete_bars(ts: np.ndarray, mid_open: np.ndarray, mid_close: np.ndarray, minutes: int) -> dict:
    step = minutes * MINUTE_MS
    open_ts = []
    close_ts = []
    ret = []
    i = 0
    n = len(ts)
    while i < n:
        bucket = int(ts[i] - ts[i] % step)
        j = i + 1
        while j < n and int(ts[j] - ts[j] % step) == bucket:
            j += 1
        if (
            j - i == minutes
            and int(ts[i]) == bucket
            and int(ts[j - 1]) == bucket + (minutes - 1) * MINUTE_MS
            and mid_open[i] > 0
        ):
            open_ts.append(bucket)
            close_ts.append(bucket + step)
            ret.append(float(mid_close[j - 1]) / float(mid_open[i]) - 1.0)
        i = j
    return {
        "open_ts": np.asarray(open_ts, dtype=np.int64),
        "close_ts": np.asarray(close_ts, dtype=np.int64),
        "ret": np.asarray(ret, dtype=float),
    }


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return float(sum(values) / len(values))


def label_trade(gross: float | None, t_stat: float | None, cost: float) -> str:
    if gross is None or t_stat is None or abs(t_stat) < 2:
        return "nothing"
    if abs(t_stat) >= 3.5 and gross > cost:
        return "bigger than the cost - worth ONE strategy test"
    return "real but smaller than the cost"


def label_corr(t_stat: float | None) -> str:
    if t_stat is None or abs(t_stat) < 2:
        return "nothing"
    return "not an up-or-down trade"


def _trade_row(instrument: str, measure: str, times: list[int], pnls: list[float], cost: float) -> dict:
    gross = _mean(pnls)
    t_stat, _days = daily_total_t(times, pnls)
    return {
        "instrument": instrument,
        "measure": measure,
        "n": len(pnls),
        "gross_effect": gross,
        "cost": cost,
        "effect_over_cost": None if gross is None or cost == 0 else gross / cost,
        "t_stat": t_stat,
        "label": label_trade(gross, t_stat, cost),
        "kind": "return",
    }


def _corr_row(instrument: str, measure: str, times, xs, ys) -> dict:
    corr, n = pearson(xs, ys)
    t_stat, _days = daily_correlation_t(times, xs, ys)
    shown = measure if corr is None else f"{measure} {corr:.4f}"
    return {
        "instrument": instrument,
        "measure": shown,
        "n": n,
        "gross_effect": None,
        "cost": None,
        "effect_over_cost": None,
        "t_stat": t_stat,
        "label": label_corr(t_stat),
        "kind": "correlation",
    }


def adjacent_signed(bars: dict, name: str, instrument: str, cost: float, step_ms: int) -> list[dict]:
    open_ts = bars["open_ts"]
    ret = bars["ret"]
    step = int(step_ms)
    times = []
    follow = []
    fade = []
    prev = []
    nxt = []
    for i in range(len(ret) - 1):
        if int(open_ts[i + 1]) != int(open_ts[i]) + step:
            continue
        if ret[i] == 0:
            continue
        sign = 1.0 if ret[i] > 0 else -1.0
        times.append(int(bars["close_ts"][i]))
        follow.append(sign * float(ret[i + 1]))
        fade.append(-sign * float(ret[i + 1]))
        prev.append(abs(float(ret[i])))
        nxt.append(abs(float(ret[i + 1])))
    rows = [
        _trade_row(instrument, f"{name}, follow the last bar, held one bar", times, follow, cost),
        _trade_row(instrument, f"{name}, fade the last bar, held one bar", times, fade, cost),
    ]
    if name in ("15m", "60m"):
        rows.append(_corr_row(instrument, f"{name} correlation of the size of one move with the size of the next", times, prev, nxt))
    return rows


def session_rows(name: str, base: int, present: np.ndarray, opens: np.ndarray, closes: np.ndarray, hour: int, minute: int, cost: float) -> dict:
    start_min = hour * 60 + minute
    times = []
    pnls = []
    # Days are UTC midnights present in the grid.
    day_ms = 24 * 60 * MINUTE_MS
    first_day = (base * MINUTE_MS // day_ms) * day_ms
    last_day = ((base + len(present)) * MINUTE_MS // day_ms) * day_ms
    day = first_day
    while day <= last_day:
        begin = day + start_min * MINUTE_MS
        signal_minute = begin + 14 * MINUTE_MS
        exit_minute = signal_minute + 4 * 60 * MINUTE_MS
        if contiguous(present, base, begin, exit_minute):
            a = int(begin // MINUTE_MS) - base
            s = int(signal_minute // MINUTE_MS) - base
            e = int(exit_minute // MINUTE_MS) - base
            move = float(closes[s]) / float(opens[a]) - 1.0
            if move != 0.0 and closes[s] > 0 and closes[e] > 0:
                forward = float(closes[e]) / float(closes[s]) - 1.0
                sign = 1.0 if move > 0 else -1.0
                times.append(signal_minute + MINUTE_MS)
                pnls.append(sign * forward)
        day += day_ms
    clock = f"{hour:02d}:{minute:02d}"
    return _trade_row(name, f"follow the first 15m after {clock} UTC, next 4h", times, pnls, cost)


def large_move_rows(name: str, bars: dict, base: int, present: np.ndarray, closes: np.ndarray, cost: float) -> list[dict]:
    size = np.abs(bars["ret"])
    threshold = rolling_thresholds(bars["close_ts"], size, WINDOW_MS, (0.90,))[:, 0] if len(size) else np.zeros(0)
    follow_t, follow_p, fade_p = [], [], []
    for i, close_ts in enumerate(bars["close_ts"].tolist()):
        level = threshold[i]
        if level != level or size[i] < level or bars["ret"][i] == 0:
            continue
        start = int(bars["open_ts"][i])
        end = int(close_ts) - MINUTE_MS + 60 * MINUTE_MS
        if not contiguous(present, base, start, end):
            continue
        s = int((int(close_ts) - MINUTE_MS) // MINUTE_MS) - base
        e = int(end // MINUTE_MS) - base
        if not (closes[s] > 0 and closes[e] > 0):
            continue
        forward = float(closes[e]) / float(closes[s]) - 1.0
        sign = 1.0 if bars["ret"][i] > 0 else -1.0
        follow_t.append(int(close_ts))
        follow_p.append(sign * forward)
        fade_p.append(-sign * forward)
    return [
        _trade_row(name, "after a top-10% 15m move, follow it, next 1h", follow_t, follow_p, cost),
        _trade_row(name, "after a top-10% 15m move, fade it, next 1h", follow_t, fade_p, cost),
    ]


def load_instrument(folder: Path, symbol: str) -> dict | None:
    bid = folder / f"{symbol}-m1-bid-2022-01-01-2024-01-01.csv"
    ask = folder / f"{symbol}-m1-ask-2022-01-01-2024-01-01.csv"
    if not bid.exists() or not ask.exists():
        return None
    joined = join_bid_ask(read_side(bid), read_side(ask))
    if len(joined["ts"]) == 0:
        return None
    cost = float(np.median(joined["spread"])) + COMMISSION
    base, present, opens, closes = slot_tables(joined["ts"], joined["mid_open"], joined["mid_close"])
    return {**joined, "cost": cost, "base": base, "present": present, "opens": opens, "closes": closes, "median_spread": cost - COMMISSION}


def measure_instrument(name: str, data: dict) -> list[dict]:
    rows = []
    cost = float(data["cost"])
    for minutes, label in ((5, "5m"), (15, "15m"), (60, "60m")):
        bars = complete_bars(data["ts"], data["mid_open"], data["mid_close"], minutes)
        rows.extend(adjacent_signed(bars, label, name, cost, minutes * MINUTE_MS))
        if minutes == 15:
            rows.extend(large_move_rows(name, bars, data["base"], data["present"], data["closes"], cost))
    rows.append(session_rows(name, data["base"], data["present"], data["opens"], data["closes"], 7, 0, cost))
    rows.append(session_rows(name, data["base"], data["present"], data["opens"], data["closes"], 13, 30, cost))
    return rows


def ratio_rows(gold: dict, silver: dict) -> list[dict]:
    common, gi, si = np.intersect1d(gold["ts"], silver["ts"], return_indices=True)
    ratio = gold["mid_close"][gi] / silver["mid_close"][si]
    levels = rolling_thresholds(common, ratio, WINDOW_MS, (0.10, 0.90))
    cost = float(gold["cost"]) + float(silver["cost"])
    tails = {"bottom 10%": [], "top 10%": []}
    times = {"bottom 10%": [], "top 10%": []}
    for i, ts in enumerate(common.tolist()):
        lo, hi = levels[i]
        if lo != lo:
            continue
        end = int(ts) + 4 * 60 * MINUTE_MS
        if not contiguous(gold["present"], gold["base"], int(ts), end):
            continue
        if not contiguous(silver["present"], silver["base"], int(ts), end):
            continue
        g0 = _slot(gold, int(ts))
        g1 = _slot(gold, end)
        s0 = _slot(silver, int(ts))
        s1 = _slot(silver, end)
        if min(g0, g1, s0, s1) <= 0:
            continue
        relative = (g1 / g0 - 1.0) - (s1 / s0 - 1.0)
        if ratio[i] <= lo:
            tails["bottom 10%"].append(relative)
            times["bottom 10%"].append(int(ts) + MINUTE_MS)
        elif ratio[i] >= hi:
            tails["top 10%"].append(relative)
            times["top 10%"].append(int(ts) + MINUTE_MS)
    rows = []
    for label, pnls in tails.items():
        rows.append(
            _trade_row(
                "Gold/Silver",
                f"ratio in the {label}, gold minus silver over the next 4h",
                times[label],
                pnls,
                cost,
            )
        )
    return rows


def _slot(data: dict, ts: int) -> float:
    slot = int(ts // MINUTE_MS) - int(data["base"])
    if slot < 0 or slot >= len(data["closes"]):
        return 0.0
    value = float(data["closes"][slot])
    if value != value:
        return 0.0
    return value


def lead_rows(left_name: str, left: dict, right_name: str, right: dict) -> list[dict]:
    left_close = {int(ts): float(px) for ts, px in zip(left["ts"], left["mid_close"])}
    right_close = {int(ts): float(px) for ts, px in zip(right["ts"], right["mid_close"])}

    def rets(closes: dict[int, float]) -> dict[int, float]:
        out = {}
        for ts, px in closes.items():
            prev = closes.get(ts - MINUTE_MS)
            if prev and prev > 0 and px > 0:
                out[ts] = px / prev - 1.0
        return out

    left_ret = rets(left_close)
    right_ret = rets(right_close)
    rows = []
    for signal_name, signal, target_name, target, cost in (
        (left_name, left_ret, right_name, right_ret, right["cost"]),
        (right_name, right_ret, left_name, left_ret, left["cost"]),
    ):
        xs, ys, times, pnls, trade_times = [], [], [], [], []
        for ts, value in signal.items():
            nxt = target.get(ts + MINUTE_MS)
            if nxt is None:
                continue
            known = ts + MINUTE_MS
            xs.append(value)
            ys.append(nxt)
            times.append(known)
            if value > 0:
                pnls.append(nxt)
                trade_times.append(known)
            elif value < 0:
                pnls.append(-nxt)
                trade_times.append(known)
        rows.append(_corr_row(f"{signal_name}/{target_name}", f"{signal_name} last minute, {target_name} next minute correlation", times, xs, ys))
        rows.append(_trade_row(f"{signal_name}/{target_name}", f"{signal_name} last minute, follow it in {target_name}, held one minute", trade_times, pnls, float(cost)))
    return rows


def measure_folder(folder: Path) -> tuple[list[dict], list[str], dict]:
    loaded = {}
    missing = []
    costs = {}
    for symbol, name in INSTRUMENTS:
        data = load_instrument(folder, symbol)
        if data is None:
            missing.append(name)
            continue
        loaded[name] = data
        costs[name] = {"median_spread": data["median_spread"], "commission": COMMISSION, "cost": data["cost"], "minutes": int(len(data["ts"]))}
        print(f"  {name} minutes {len(data['ts'])} cost {data['cost']:.6g}", flush=True)
    rows: list[dict] = []
    for name, data in loaded.items():
        print(f"  measure {name}", flush=True)
        rows.extend(measure_instrument(name, data))
    if "Gold" in loaded and "Silver" in loaded:
        print("  gold/silver ratio", flush=True)
        rows.extend(ratio_rows(loaded["Gold"], loaded["Silver"]))
    if "EURUSD" in loaded and "GBPUSD" in loaded:
        print("  eur/gbp", flush=True)
        rows.extend(lead_rows("EURUSD", loaded["EURUSD"], "GBPUSD", loaded["GBPUSD"]))
    return rows, missing, costs
