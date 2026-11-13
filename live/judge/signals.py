"""Frozen paper rules. Percentiles and z-scores use earlier days only."""

from __future__ import annotations

import bisect
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

COSTS = (0.0012, 0.0010, 0.0006)
LADDER_COST = 0.0012
HOUR_MS = 3_600_000
DAY_MS = 86_400_000
MINUTE_MS = 60_000
FUNDING_HOURS = (0, 8, 16)


def day_start(day: str) -> int:
    dt = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def day_end(day: str) -> int:
    return day_start(day) + DAY_MS


def day_of(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000, timezone.utc).strftime("%Y-%m-%d")


def shift_day(day: str, days: int) -> str:
    dt = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=days)
    return dt.strftime("%Y-%m-%d")


def days_between(start: str, end: str) -> list[str]:
    """Inclusive calendar days."""
    out = []
    cur = start
    while cur <= end:
        out.append(cur)
        cur = shift_day(cur, 1)
    return out


def months_between(start: str, end: str) -> list[str]:
    seen = []
    for day in days_between(start, end):
        month = day[:7]
        if not seen or seen[-1] != month:
            seen.append(month)
    return seen


def quantile(values: list[float], q: float) -> float:
    """Linear quantile. Position (n - 1) * q, matching the backtest engine."""
    if not values:
        raise ValueError("empty")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    weight = pos - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def percentile(past: list[float], q: float) -> float:
    """Quantile of previous observations. The caller must leave out the current day."""
    if not past:
        raise ValueError("percentile needs previous days")
    return quantile(past, q)


def below_past(current: float, past: list[float], q: float) -> bool:
    if len(past) < 2:
        return False
    return current < percentile(past, q)


def above_past(current: float, past: list[float], q: float) -> bool:
    if len(past) < 2:
        return False
    return current > percentile(past, q)


def z_of(current: float, past: list[float]) -> float | None:
    n = len(past)
    if n < 2:
        return None
    mean = sum(past) / n
    var = sum((x - mean) ** 2 for x in past) / (n - 1)
    sd = var ** 0.5
    if sd == 0.0:
        return 0.0
    return (current - mean) / sd


def _last_at_or_before(series: list[tuple[int, float]], ts: int) -> tuple[int, float] | None:
    if not series:
        return None
    keys = [row[0] for row in series]
    idx = bisect.bisect_right(keys, ts) - 1
    if idx < 0:
        return None
    return series[idx]


def funding_boundaries(entry_ts: int, exit_ts: int, hours: tuple[int, ...] = FUNDING_HOURS) -> list[int]:
    """Clock marks inside (entry, exit]. BTC is every 8 hours. Gold is every 4."""
    if exit_ts <= entry_ts:
        return []
    start_day = day_of(entry_ts)
    end_day = day_of(exit_ts)
    marks = []
    for day in days_between(start_day, end_day):
        base = day_start(day)
        for hour in hours:
            mark = base + hour * HOUR_MS
            if entry_ts < mark <= exit_ts:
                marks.append(mark)
    return marks


def funding_covered(
    entry_ts: int,
    exit_ts: int,
    months_present: set[str],
    hours: tuple[int, ...] = FUNDING_HOURS,
) -> bool:
    """True when every funding mark in the hold belongs to a published month file."""
    for mark in funding_boundaries(entry_ts, exit_ts, hours):
        if day_of(mark)[:7] not in months_present:
            return False
    return True


def funding_paid(direction: str, entry_ts: int, exit_ts: int, events: list[tuple[int, float]]) -> float:
    """Long pays a positive rate. Short receives it. Events in (entry, exit]."""
    sign = 1.0 if direction == "UP" else -1.0
    total = 0.0
    for ts, rate in events:
        if entry_ts < ts <= exit_ts:
            total += rate
    return sign * total


def price_result(direction: str, entry: float, exit_px: float, paid: float) -> dict:
    sign = 1.0 if direction == "UP" else -1.0
    gross = sign * (exit_px / entry - 1.0)
    nets = {f"{cost:.4f}": gross - cost - paid for cost in COSTS}
    if exit_px > entry:
        move = 1
    elif exit_px < entry:
        move = -1
    else:
        move = 0
    hit = (direction == "UP" and move > 0) or (direction == "DOWN" and move < 0)
    return {"gross": gross, "nets": nets, "hit": hit, "move": move, "funding": paid}


def make_call(spec_id: str, signal: dict, entry: float, exit_px: float, events: list[tuple[int, float]]) -> dict:
    paid = funding_paid(signal["direction"], signal["entry_ts"], signal["exit_ts"], events)
    result = price_result(signal["direction"], entry, exit_px, paid)
    return {
        "type": "call",
        "id": spec_id,
        "day": day_of(signal["entry_ts"]),
        "signal_ts": signal["signal_ts"],
        "entry_ts": signal["entry_ts"],
        "exit_ts": signal["exit_ts"],
        "direction": signal["direction"],
        "entry": entry,
        "exit": exit_px,
        "gross": result["gross"],
        "funding": result["funding"],
        "nets": result["nets"],
        "hit": result["hit"],
        "move": result["move"],
    }


def hold_exit(entry_ts: int, hours: int) -> int:
    return entry_ts + hours * HOUR_MS


def next_minute_open(ts: int) -> int:
    if ts % MINUTE_MS == 0:
        return ts
    return ts + (MINUTE_MS - ts % MINUTE_MS)


def l1_signals(spec: dict, day: str, events: list[tuple[int, float]]) -> list[dict]:
    rule = spec["rule"]
    start = day_start(day)
    end = day_end(day)
    window_start = day_start(shift_day(day, -int(rule["lookback_days"])))
    past = [rate for ts, rate in events if window_start <= ts < start]
    hours = int(spec["hold_hours"])
    out = []
    for ts, rate in events:
        if ts < start or ts >= end:
            continue
        if not below_past(rate, past, float(rule["percentile"])):
            continue
        entry = next_minute_open(ts)
        out.append(
            {
                "signal_ts": ts,
                "entry_ts": entry,
                "exit_ts": hold_exit(entry, hours),
                "direction": "UP",
            }
        )
    return out


def _hourly_features(
    fut: dict[int, tuple[float, float]],
    spot: dict[int, tuple[float, float]],
    funding: list[tuple[int, float]],
    oi: list[tuple[int, float]],
    start: int,
    end: int,
) -> list[tuple[int, float, float, float]]:
    rows = []
    hour = start
    if hour % HOUR_MS:
        hour += HOUR_MS - (hour % HOUR_MS)
    while hour < end:
        minute = hour - MINUTE_MS
        fut_row = fut.get(minute)
        spot_row = spot.get(minute)
        gap = None
        if fut_row and spot_row and spot_row[1] != 0.0:
            gap = -(fut_row[1] / spot_row[1] - 1.0)
        fund_row = _last_at_or_before(funding, hour)
        fund = None if fund_row is None else -fund_row[1]
        now = _last_at_or_before(oi, hour)
        prev = _last_at_or_before(oi, hour - HOUR_MS)
        oi_signed = None
        if now and prev and prev[1] != 0.0:
            span = now[0] - prev[0]
            if 30 * MINUTE_MS <= span <= 2 * HOUR_MS:
                oi_signed = -((now[1] - prev[1]) / prev[1])
        if gap is not None and fund is not None and oi_signed is not None:
            rows.append((hour, gap, fund, oi_signed))
        hour += HOUR_MS
    return rows


def _scores_by_day(features: list[tuple[int, float, float, float]]) -> dict[str, list[float]]:
    by_day: dict[str, list[tuple[float, float, float]]] = {}
    for ts, gap, fund, oi_signed in features:
        by_day.setdefault(day_of(ts), []).append((gap, fund, oi_signed))
    scores: dict[str, list[float]] = {}
    for day, points in by_day.items():
        window_start = shift_day(day, -30)
        past_gap: list[float] = []
        past_fund: list[float] = []
        past_oi: list[float] = []
        for older, older_points in by_day.items():
            if window_start <= older < day:
                for gap, fund, oi_signed in older_points:
                    past_gap.append(gap)
                    past_fund.append(fund)
                    past_oi.append(oi_signed)
        day_scores = []
        for gap, fund, oi_signed in points:
            zg = z_of(gap, past_gap)
            zf = z_of(fund, past_fund)
            zo = z_of(oi_signed, past_oi)
            if zg is None or zf is None or zo is None:
                continue
            day_scores.append((zg + zf + zo) / 3.0)
        scores[day] = day_scores
    return scores


def l2_signals(spec: dict, day: str, book: dict) -> list[dict]:
    rule = spec["rule"]
    feature_days = int(rule["feature_lookback_days"])
    start = day_start(shift_day(day, -feature_days))
    end = day_end(day)
    features = _hourly_features(book["fut"], book["spot"], book["funding"], book["oi"], start, end)
    scores = _scores_by_day(features)
    past: list[float] = []
    window_start = shift_day(day, -int(rule["lookback_days"]))
    for older, values in scores.items():
        if window_start <= older < day:
            past.extend(values)
    # Today's hours use the same previous-days z window, paired back to the clock.
    history_gap: list[float] = []
    history_fund: list[float] = []
    history_oi: list[float] = []
    today_hours: list[tuple[int, float]] = []
    for ts, gap, fund, oi_signed in features:
        older = day_of(ts)
        if window_start <= older < day:
            history_gap.append(gap)
            history_fund.append(fund)
            history_oi.append(oi_signed)
        elif older == day:
            zg = z_of(gap, history_gap)
            zf = z_of(fund, history_fund)
            zo = z_of(oi_signed, history_oi)
            if zg is None or zf is None or zo is None:
                continue
            today_hours.append((ts, (zg + zf + zo) / 3.0))
    hours = int(spec["hold_hours"])
    out = []
    for ts, score in today_hours:
        if not above_past(score, past, float(rule["percentile"])):
            continue
        out.append(
            {
                "signal_ts": ts,
                "entry_ts": ts,
                "exit_ts": hold_exit(ts, hours),
                "direction": "UP",
            }
        )
    return out


def l3_signals(spec: dict, day: str, flow: list[dict]) -> list[dict]:
    start = day_start(day)
    end = day_end(day)
    hours = int(spec["hold_hours"])
    out = []
    for row in flow:
        boundary = int(row["boundary"])
        if boundary < start or boundary >= end:
            continue
        share = float(row["share"])
        if share > 0.5:
            direction = "UP"
        elif share < 0.5:
            direction = "DOWN"
        else:
            continue
        entry = boundary + MINUTE_MS
        out.append(
            {
                "signal_ts": boundary + int(spec["rule"]["window_ms"]),
                "entry_ts": entry,
                "exit_ts": hold_exit(entry, hours),
                "direction": direction,
            }
        )
    out.sort(key=lambda item: item["entry_ts"])
    return out


def _package_path() -> None:
    root = Path(__file__).resolve().parents[2]
    pkg = str(root / "trading-matrix")
    if pkg not in sys.path:
        sys.path.insert(0, pkg)


def t4_closes(fut: dict[int, tuple[float, float]], decision_ts: int, lookback_bars: int) -> list[float] | None:
    """Last `lookback_bars` closed 15-minute closes ending at decision_ts.

    A missing minute in that window means the vote is not read.
    """
    _package_path()
    from src.backtest.resample import closed_resampled

    need = lookback_bars * 15
    start = decision_ts - need * MINUTE_MS
    candles = []
    ts = start
    while ts < decision_ts:
        row = fut.get(ts)
        if row is None:
            return None
        candles.append(
            {
                "timestamp": ts,
                "open": row[0],
                "high": row[0],
                "low": row[0],
                "close": row[1],
                "volume": 0.0,
            }
        )
        ts += MINUTE_MS
    bars = closed_resampled(candles, 15 * MINUTE_MS)
    if len(bars) < lookback_bars:
        return None
    return [float(bar["close"]) for bar in bars[-lookback_bars:]]


def t4_direction(closes: list[float]) -> str | None:
    _package_path()
    from src.prediction.lens_technical import run_technical

    direction = run_technical(closes).direction
    if direction not in ("UP", "DOWN"):
        return None
    return direction


def l4_signals(spec: dict, day: str, fut: dict[int, tuple[float, float]]) -> list[dict]:
    rule = spec["rule"]
    lookback = int(rule["lookback_bars"])
    hours = int(spec["hold_hours"])
    start = day_start(day)
    out = []
    for step in range(0, 24, int(rule["decision_hours"])):
        decision = start + step * HOUR_MS
        closes = t4_closes(fut, decision, lookback)
        if not closes:
            continue
        direction = t4_direction(closes)
        if direction is None:
            continue
        out.append(
            {
                "signal_ts": decision,
                "entry_ts": decision,
                "exit_ts": hold_exit(decision, hours),
                "direction": direction,
            }
        )
    return out


def l5_signals(
    spec: dict,
    day: str,
    xau: dict[int, tuple[float, float]],
    index: dict[int, tuple[float, float]],
) -> list[dict]:
    rule = spec["rule"]
    start = day_start(day)
    end = day_end(day)
    window_start = day_start(shift_day(day, -int(rule["lookback_days"])))
    past = []
    ts = window_start
    while ts < start:
        perp = xau.get(ts)
        mark = index.get(ts)
        if perp and mark and mark[1] != 0.0:
            past.append(perp[1] / mark[1] - 1.0)
        ts += MINUTE_MS
    hours = int(spec["hold_hours"])
    out = []
    ts = start
    while ts < end:
        perp = xau.get(ts)
        mark = index.get(ts)
        if perp and mark and mark[1] != 0.0:
            gap = perp[1] / mark[1] - 1.0
            if below_past(gap, past, float(rule["percentile"])):
                entry = ts + MINUTE_MS
                out.append(
                    {
                        "signal_ts": ts + MINUTE_MS,
                        "entry_ts": entry,
                        "exit_ts": hold_exit(entry, hours),
                        "direction": "UP",
                    }
                )
        ts += MINUTE_MS
    return out


def signals_for(spec: dict, day: str, book: dict) -> list[dict]:
    kind = spec["rule"]["kind"]
    if kind == "funding_below_percentile":
        return l1_signals(spec, day, book["funding"])
    if kind == "crowding_score":
        return l2_signals(spec, day, book)
    if kind == "quarter_hour_flow":
        return l3_signals(spec, day, book["flow"])
    if kind == "t4_reversion":
        return l4_signals(spec, day, book["fut"])
    if kind == "index_gap_below_percentile":
        return l5_signals(spec, day, book["xau"], book["index"])
    raise ValueError(kind)


def take_flat(signals: list[dict], busy_until: int) -> list[dict]:
    """One position at a time. A new entry may start on the exit open."""
    taken = []
    for signal in signals:
        if signal["entry_ts"] < busy_until:
            continue
        taken.append(signal)
        busy_until = signal["exit_ts"]
    return taken
