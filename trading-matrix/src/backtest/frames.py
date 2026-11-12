"""Diagnostic frames on the already-seen 2020-11 to 2022-10 window.

No trading rule is chosen here. Nothing is written to the ledger.
"""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from src.backtest.loader import month_iter, read_funding_zip, read_klines_zip, to_ms
from src.backtest.resample import ClosedResampler

QUARTER_MS = 15 * 60_000
WINDOW_MS = 10_000
FEE_TAKER = 0.0009
FEE_MAKER = 0.0006
START_MS = int(datetime(2020, 11, 1, tzinfo=timezone.utc).timestamp() * 1000)
END_MS = int(datetime(2022, 11, 1, tzinfo=timezone.utc).timestamp() * 1000)
FORBIDDEN_MS = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


def build_volume_bars(candles: list[dict], threshold: float) -> list[dict]:
    """Close a bar once added 1m volume reaches `threshold`. An unfinished bar is dropped."""
    if threshold <= 0:
        raise ValueError("threshold")
    bars: list[dict] = []
    cur: dict | None = None
    for candle in candles:
        ts = int(candle["timestamp"])
        high = float(candle["high"])
        low = float(candle["low"])
        if cur is None:
            cur = {
                "timestamp": ts,
                "open": float(candle["open"]),
                "high": high,
                "low": low,
                "close": float(candle["close"]),
                "volume": float(candle["volume"]),
                "minutes": 1,
                "close_time": ts + 60_000,
            }
        else:
            cur["high"] = max(cur["high"], high)
            cur["low"] = min(cur["low"], low)
            cur["close"] = float(candle["close"])
            cur["volume"] += float(candle["volume"])
            cur["minutes"] += 1
            cur["close_time"] = ts + 60_000
        if cur["volume"] >= threshold:
            bars.append(cur)
            cur = None
    return bars


def accumulate_boundary_windows(trades) -> list[dict]:
    """Buy and sell volume in the first 10 seconds after each quarter hour.

    `trades` are (timestamp_ms, qty, is_buyer_maker). is_buyer_maker means the
    taker sold, matching the archive reader. A trade at exactly +10 seconds is
    outside the window.
    """
    buy: dict[int, float] = {}
    sell: dict[int, float] = {}
    for ts, qty, maker in trades:
        ts = int(ts)
        boundary = ts - (ts % QUARTER_MS)
        if ts < boundary or ts >= boundary + WINDOW_MS:
            continue
        slot = sell if maker else buy
        slot[boundary] = slot.get(boundary, 0.0) + float(qty)
    rows = []
    for boundary in sorted(set(buy) | set(sell)):
        bought = buy.get(boundary, 0.0)
        sold = sell.get(boundary, 0.0)
        total = bought + sold
        if total <= 0:
            continue
        rows.append(
            {
                "boundary": boundary,
                "buy": bought,
                "sell": sold,
                "share": bought / total,
            }
        )
    return rows


def _day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def threshold_for_duration(candles: list[dict], target_minutes: int) -> tuple[float, float]:
    """Pick a BTC size whose finished bars last about `target_minutes` on average."""
    volumes = [float(candle["volume"]) for candle in candles]
    mean_volume = sum(volumes) / len(volumes)

    def realized(multiplier: float) -> float:
        bars = build_volume_bars(candles, mean_volume * multiplier)
        if not bars:
            return 0.0
        return sum(bar["minutes"] for bar in bars) / len(bars)

    low, high = 0.2, 80.0
    for _ in range(22):
        mid = (low + high) / 2.0
        if realized(mid) < target_minutes:
            low = mid
        else:
            high = mid
    chosen = mean_volume * high
    return chosen, realized(high)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return float(sum(values) / len(values))


def _t_of(values: list[float]) -> tuple[float | None, int]:
    n = len(values)
    if n < 3:
        return None, n
    arr = np.asarray(values, dtype=float)
    sd = float(arr.std(ddof=1))
    if sd == 0.0 or not np.isfinite(sd):
        return None, n
    return float(arr.mean() / (sd / np.sqrt(n))), n


def daily_total_t(times: list[int], pnls: list[float]) -> tuple[float | None, int]:
    buckets: dict[str, float] = {}
    for ts, pnl in zip(times, pnls):
        day = _day(int(ts))
        buckets[day] = buckets.get(day, 0.0) + float(pnl)
    return _t_of(list(buckets.values()))


def pearson(xs, ys) -> tuple[float | None, int]:
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    x = x[mask]
    y = y[mask]
    n = int(x.size)
    if n < 3:
        return None, n
    x = x - x.mean()
    y = y - y.mean()
    denom = float(np.sqrt((x * x).sum() * (y * y).sum()))
    if denom == 0.0 or not np.isfinite(denom):
        return None, n
    return float((x * y).sum() / denom), n


def daily_correlation_t(times, xs, ys) -> tuple[float | None, int]:
    buckets: dict[str, list] = {}
    for ts, x, y in zip(times, xs, ys):
        if not np.isfinite(x) or not np.isfinite(y):
            continue
        buckets.setdefault(_day(int(ts)), [[], []])
        buckets[_day(int(ts))][0].append(float(x))
        buckets[_day(int(ts))][1].append(float(y))
    corrs = []
    for pair in buckets.values():
        corr, n = pearson(pair[0], pair[1])
        if corr is not None and n >= 5:
            corrs.append(corr)
    return _t_of(corrs)


def label_return(gross: float | None, t_stat: float | None) -> str:
    if gross is None or t_stat is None or abs(t_stat) < 2:
        return "nothing"
    if abs(t_stat) >= 3.5 and gross > FEE_TAKER:
        return "bigger than the fee - worth ONE strategy test"
    return "real but smaller than the fee"


def _signed(signal: list[float], trade: list[float], times: list[int], fade: bool):
    pnls = []
    when = []
    for sig, nxt, ts in zip(signal, trade, times):
        if sig > 0:
            side = -1.0 if fade else 1.0
        elif sig < 0:
            side = 1.0 if fade else -1.0
        else:
            continue
        pnls.append(side * nxt)
        when.append(ts)
    return pnls, when


def _return_row(frame: str, measure: str, pnls: list[float], times: list[int]) -> dict:
    gross = _mean(pnls)
    t_stat, _days = daily_total_t(times, pnls)
    return {
        "frame": frame,
        "measure": measure,
        "n": len(pnls),
        "gross_effect": gross,
        "correlation": None,
        "fee": FEE_TAKER,
        "effect_over_fee": None if gross is None else gross / FEE_TAKER,
        "effect_over_maker_fee": None if gross is None else gross / FEE_MAKER,
        "t_stat": t_stat,
        "days": _days,
        "label": label_return(gross, t_stat),
        "kind": "return",
    }


def _corr_row(frame: str, measure: str, times, xs, ys) -> dict:
    corr, n = pearson(xs, ys)
    t_stat, days = daily_correlation_t(times, xs, ys)
    shown = measure if corr is None else f"{measure} {corr:.4f}"
    label = "nothing" if t_stat is None or abs(t_stat) < 2 else "not an up-or-down trade"
    return {
        "frame": frame,
        "measure": shown,
        "n": n,
        "gross_effect": None,
        "correlation": corr,
        "fee": None,
        "effect_over_fee": None,
        "effect_over_maker_fee": None,
        "t_stat": t_stat,
        "days": days,
        "label": label,
        "kind": "correlation",
    }


def _bar_rows(frame: str, name: str, series: list[tuple[int, float]]) -> list[dict]:
    if len(series) < 3:
        return []
    signal = [item[1] for item in series[:-1]]
    trade = [item[1] for item in series[1:]]
    times = [item[0] for item in series[:-1]]
    rows = [_corr_row(frame, f"{name} correlation, this bar's return with the next", times, signal, trade)]
    for fade, word in ((False, "follow the last bar"), (True, "fade the last bar")):
        pnls, when = _signed(signal, trade, times, fade)
        rows.append(_return_row(frame, f"{name}, {word}, held one bar", pnls, when))
    return rows


def _size_row(name: str, series: list[tuple[int, float]]) -> dict:
    signal = [abs(item[1]) for item in series[:-1]]
    trade = [abs(item[1]) for item in series[1:]]
    times = [item[0] for item in series[:-1]]
    return _corr_row("3", f"{name} correlation of the size of one move with the size of the next", times, signal, trade)


def clock_bars(candles: list[dict], minutes: int) -> list[dict]:
    sampler = ClosedResampler(minutes)
    bars = []
    for candle in candles:
        for bar in sampler.push(candle):
            bars.append(
                {
                    "timestamp": int(bar["timestamp"]),
                    "open": float(bar["open"]),
                    "high": float(bar["high"]),
                    "low": float(bar["low"]),
                    "close": float(bar["close"]),
                    "volume": float(bar["volume"]),
                }
            )
    return bars


def bar_return_series(bars: list[dict], step_ms: int | None) -> list[tuple[int, float]]:
    series = []
    for prev, cur in zip(bars, bars[1:]):
        if step_ms is not None and int(cur["timestamp"]) != int(prev["timestamp"]) + step_ms:
            continue
        base = float(prev["close"])
        if base == 0.0:
            continue
        close_time = int(cur["close_time"]) if step_ms is None else int(cur["timestamp"]) + step_ms
        series.append((close_time, float(cur["close"]) / base - 1.0))
    return series


def _guard_months(start: str, end: str) -> None:
    if start >= "2025-01" or end >= "2025-01":
        raise RuntimeError("2025-01 onward is reserved and was not loaded")


def load_klines(root: Path, symbol: str, market: str, start: str, end: str) -> tuple[list[dict], list[str]]:
    _guard_months(start, end)
    folder = root / ("futures" if market == "futures" else "spot") / symbol
    source = "BINANCE_UM" if market == "futures" else "BINANCE_SPOT"
    candles: list[dict] = []
    missing = []
    for month in month_iter(start, end):
        if month >= "2025-01":
            raise RuntimeError(month)
        path = folder / f"{symbol}-1m-{month}.zip"
        if not path.exists() or path.stat().st_size <= 0:
            missing.append(month)
            continue
        candles.extend(read_klines_zip(path, symbol, source))
    candles = [c for c in candles if START_MS <= int(c["timestamp"]) < END_MS and int(c["timestamp"]) < FORBIDDEN_MS]
    candles.sort(key=lambda c: int(c["timestamp"]))
    deduped = []
    seen = None
    for candle in candles:
        ts = int(candle["timestamp"])
        if ts == seen:
            deduped[-1] = candle
        else:
            deduped.append(candle)
            seen = ts
    return deduped, missing


def close_map(candles: list[dict]) -> dict[int, float]:
    return {int(c["timestamp"]): float(c["close"]) for c in candles}


def minute_returns(closes: dict[int, float]) -> dict[int, float]:
    out = {}
    for ts, price in closes.items():
        prev = closes.get(ts - 60_000)
        if prev and prev > 0:
            out[ts] = price / prev - 1.0
    return out


def forward(closes: dict[int, float], open_ts: int, horizon_ms: int) -> float | None:
    entry = closes.get(open_ts)
    exit_price = closes.get(open_ts + horizon_ms)
    if entry is None or exit_price is None or entry == 0.0:
        return None
    if open_ts >= FORBIDDEN_MS or open_ts + horizon_ms >= FORBIDDEN_MS:
        return None
    return exit_price / entry - 1.0


def _tail_rows(frame: str, measure_hi: str, measure_lo: str, values, forwards, times) -> list[dict]:
    usable = [(v, f, t) for v, f, t in zip(values, forwards, times) if f is not None and np.isfinite(v)]
    if len(usable) < 30:
        return []
    arr = np.asarray([item[0] for item in usable], dtype=float)
    lo = float(np.quantile(arr, 0.10))
    hi = float(np.quantile(arr, 0.90))
    high = [(item[1], item[2]) for item in usable if item[0] >= hi]
    low = [(item[1], item[2]) for item in usable if item[0] <= lo]
    rows = []
    if high:
        pnls = [item[0] for item in high]
        when = [item[1] for item in high]
        rows.append(_return_row(frame, measure_hi, pnls, when))
        rows.append(_return_row(frame, measure_hi.replace("long", "short"), [-p for p in pnls], when))
    if low:
        pnls = [item[0] for item in low]
        when = [item[1] for item in low]
        rows.append(_return_row(frame, measure_lo, pnls, when))
        rows.append(_return_row(frame, measure_lo.replace("long", "short"), [-p for p in pnls], when))
    return rows


def lead_rows(name: str, signal: dict[int, float], target: dict[int, float]) -> list[dict]:
    xs = []
    ys = []
    times = []
    pnls = []
    when = []
    for ts, sig in signal.items():
        nxt = target.get(ts + 60_000)
        if nxt is None or not np.isfinite(sig):
            continue
        known = ts + 60_000
        xs.append(sig)
        ys.append(nxt)
        times.append(known)
        if sig > 0:
            pnls.append(nxt)
            when.append(known)
        elif sig < 0:
            pnls.append(-nxt)
            when.append(known)
    return [
        _corr_row("2", name + " correlation", times, xs, ys),
        _return_row("2", name + ", follow it, held one minute", pnls, when),
    ]


def scan_agg_windows(path: Path) -> tuple[dict[int, float], dict[int, float]]:
    buy: dict[int, float] = {}
    sell: dict[int, float] = {}
    with zipfile.ZipFile(path) as zf:
        with zf.open(zf.namelist()[0]) as fh:
            for raw in fh:
                if not raw or raw[0] < 48 or raw[0] > 57:
                    continue
                parts = raw.split(b",")
                if len(parts) < 7:
                    continue
                ts = to_ms(int(float(parts[5])))
                if ts >= FORBIDDEN_MS:
                    continue
                boundary = ts - (ts % QUARTER_MS)
                if ts < boundary or ts >= boundary + WINDOW_MS:
                    continue
                qty = float(parts[2])
                maker = parts[6][:1] in (b"t", b"T", b"1")
                slot = sell if maker else buy
                slot[boundary] = slot.get(boundary, 0.0) + qty
    return buy, sell


def load_boundary_shares(root: Path, start: str, end: str) -> list[dict]:
    buy: dict[int, float] = {}
    sell: dict[int, float] = {}
    folder = root / "aggTrades" / "BTCUSDT"
    for month in month_iter(start, end):
        path = folder / f"BTCUSDT-aggTrades-{month}.zip"
        if not path.exists() or path.stat().st_size <= 0:
            raise FileNotFoundError(path)
        print(f"  boundary {month}", flush=True)
        month_buy, month_sell = scan_agg_windows(path)
        for key, qty in month_buy.items():
            buy[key] = buy.get(key, 0.0) + qty
        for key, qty in month_sell.items():
            sell[key] = sell.get(key, 0.0) + qty
    rows = []
    for boundary in sorted(set(buy) | set(sell)):
        if boundary < START_MS or boundary >= END_MS:
            continue
        bought = buy.get(boundary, 0.0)
        sold = sell.get(boundary, 0.0)
        total = bought + sold
        if total <= 0:
            continue
        rows.append({"boundary": boundary, "buy": bought, "sell": sold, "share": bought / total})
    return rows


def load_funding(root: Path, start: str, end: str) -> list[tuple[int, float]]:
    _guard_months(start, end)
    folder = root / "funding" / "BTCUSDT"
    rows = []
    for month in month_iter(start, end):
        path = folder / f"BTCUSDT-fundingRate-{month}.zip"
        if path.exists() and path.stat().st_size > 0:
            rows.extend(read_funding_zip(path))
    rows = [(int(ts), float(rate)) for ts, rate in rows if START_MS <= int(ts) < END_MS and int(ts) < FORBIDDEN_MS]
    rows.sort()
    return rows


def load_open_interest(root: Path) -> tuple[dict[int, float], int]:
    folder = root / "metrics" / "BTCUSDT"
    points: dict[int, float] = {}
    missing = 0
    day = datetime(2020, 11, 1, tzinfo=timezone.utc).date()
    last = datetime(2022, 10, 31, tzinfo=timezone.utc).date()
    while day <= last:
        path = folder / f"BTCUSDT-metrics-{day.isoformat()}.zip"
        if not path.exists() or path.stat().st_size <= 0:
            missing += 1
            day += timedelta(days=1)
            continue
        with zipfile.ZipFile(path) as zf:
            with zf.open(zf.namelist()[0]) as fh:
                for raw in fh:
                    line = raw.decode().strip()
                    if not line or not line[0].isdigit():
                        continue
                    parts = line.split(",")
                    if len(parts) < 3:
                        continue
                    ts = int(
                        datetime.strptime(parts[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
                        * 1000
                    )
                    if ts >= FORBIDDEN_MS or ts >= END_MS or ts < START_MS:
                        continue
                    points[ts] = float(parts[2])
        day += timedelta(days=1)
    return points, missing


def measure(root: Path) -> dict:
    start, end = "2020-11", "2022-10"
    print("load btc futures", flush=True)
    btc, btc_missing = load_klines(root, "BTCUSDT", "futures", start, end)
    print("load btc spot", flush=True)
    spot, spot_missing = load_klines(root, "BTCUSDT", "spot", start, end)
    print("load eth", flush=True)
    eth, eth_missing = load_klines(root, "ETHUSDT", "futures", start, end)
    rows: list[dict] = []
    notes = {
        "btc_futures_missing_months": btc_missing,
        "btc_spot_missing_months": spot_missing,
        "eth_missing_months": eth_missing,
        "open_interest": "measured",
    }

    futures_closes = close_map(btc)
    for minutes in (5, 15, 60):
        bars = clock_bars(btc, minutes)
        series = bar_return_series(bars, minutes * 60_000)
        rows.extend(_bar_rows("0", f"{minutes}m clock", series))
        if minutes in (15, 60):
            rows.append(_size_row(f"{minutes}m clock", series))

    volume_meta = []
    for minutes in (5, 15, 60):
        threshold, realized = threshold_for_duration(btc, minutes)
        bars = build_volume_bars(btc, threshold)
        volume_meta.append({"target_minutes": minutes, "threshold_btc": threshold, "realized_minutes": realized, "bars": len(bars)})
        series = bar_return_series(bars, None)
        rows.extend(_bar_rows("1", f"volume bar aimed at {minutes}m (average {realized:.1f}m)", series))

    spot_closes = close_map(spot)
    gap_values = {15: [], 60: []}
    gap_forward = {15: [], 60: []}
    gap_times = {15: [], 60: []}
    for ts, fut_px in futures_closes.items():
        spot_px = spot_closes.get(ts)
        if spot_px is None or spot_px == 0.0:
            continue
        gap = (fut_px - spot_px) / spot_px
        for horizon in (15, 60):
            fwd = forward(futures_closes, ts, horizon * 60_000)
            if fwd is None:
                continue
            gap_values[horizon].append(gap)
            gap_forward[horizon].append(fwd)
            gap_times[horizon].append(ts + 60_000)
    if spot_missing and not spot:
        notes["gap"] = "skipped: spot klines missing"
    else:
        for horizon in (15, 60):
            rows.extend(
                _tail_rows(
                    "2",
                    f"futures-spot gap in the top 10%, long the next {horizon}m",
                    f"futures-spot gap in the bottom 10%, long the next {horizon}m",
                    gap_values[horizon],
                    gap_forward[horizon],
                    gap_times[horizon],
                )
            )

    if eth:
        eth_ret = minute_returns(close_map(eth))
        btc_ret = minute_returns(futures_closes)
        rows.extend(lead_rows("ETH last minute, BTC next minute", eth_ret, btc_ret))
        rows.extend(lead_rows("BTC last minute, ETH next minute", btc_ret, eth_ret))
    else:
        notes["lead_lag"] = "skipped: ETHUSDT perpetual klines missing"

    print("boundary windows", flush=True)
    windows = load_boundary_shares(root, start, end)
    for horizon, word in ((60, "1h"), (240, "4h")):
        xs = []
        ys = []
        times = []
        pnls = []
        when = []
        for row in windows:
            boundary = int(row["boundary"])
            fwd = forward(futures_closes, boundary, horizon * 60_000)
            if fwd is None:
                continue
            share = float(row["share"]) - 0.5
            known = boundary + 60_000
            xs.append(share)
            ys.append(fwd)
            times.append(known)
            if share > 0:
                pnls.append(fwd)
                when.append(known)
            elif share < 0:
                pnls.append(-fwd)
                when.append(known)
        rows.append(_corr_row("4", f"quarter-hour buy share and the next {word} correlation", times, xs, ys))
        rows.append(_return_row("4", f"quarter-hour buy share, follow it, next {word}", pnls, when))

    funding = load_funding(root, start, end)
    fund_values = []
    fund_forward = []
    fund_times = []
    for ts, rate in funding:
        entry = ts - 60_000 if ts % 60_000 == 0 else (ts - (ts % 60_000)) - 60_000
        fwd = forward(futures_closes, entry, 8 * 60 * 60_000)
        if fwd is None:
            continue
        fund_values.append(rate)
        fund_forward.append(fwd)
        fund_times.append(ts)
    rows.extend(
        _tail_rows(
            "4",
            "funding rate in the top 10%, long the next 8h",
            "funding rate in the bottom 10%, long the next 8h",
            fund_values,
            fund_forward,
            fund_times,
        )
    )

    print("open interest", flush=True)
    oi, oi_missing = load_open_interest(root)
    notes["open_interest_missing_days"] = oi_missing
    if not oi:
        notes["open_interest"] = "skipped: metrics archive missing"
    else:
        changes = []
        forwards = []
        times = []
        for ts, value in oi.items():
            prev = oi.get(ts - 3_600_000)
            if prev is None or prev == 0.0:
                continue
            entry = ts - 60_000 if ts % 60_000 == 0 else (ts - (ts % 60_000)) - 60_000
            fwd = forward(futures_closes, entry, 3_600_000)
            if fwd is None:
                continue
            changes.append((value - prev) / prev)
            forwards.append(fwd)
            times.append(ts)
        rows.extend(
            _tail_rows(
                "4",
                "open interest 1h rise in the top 10%, long the next 1h",
                "open interest 1h fall in the bottom 10%, long the next 1h",
                changes,
                forwards,
                times,
            )
        )
        notes["monthly_metrics_zip"] = "404; daily metrics files were used"

    return {
        "period": "2020-11-01 to 2022-10-31",
        "symbol": "BTCUSDT",
        "fees": {"maker_in_taker_out": FEE_TAKER, "maker_both": FEE_MAKER},
        "volume_bars": volume_meta,
        "notes": notes,
        "rows": rows,
    }


def _fmt(value, digits=6) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}g}"


def _plain(rows: list[dict]) -> list[str]:
    def returns(frames: tuple[str, ...], contains: str | None = None, prefix: str | None = None) -> list[dict]:
        picked = []
        for row in rows:
            if row["kind"] != "return" or row["frame"] not in frames:
                continue
            if contains is not None and contains not in row["measure"]:
                continue
            if prefix is not None and not row["measure"].startswith(prefix):
                continue
            picked.append(row)
        return picked

    def bigger(subset: list[dict]) -> list[dict]:
        return [row for row in subset if row["label"].startswith("bigger")]

    def real(subset: list[dict]) -> list[dict]:
        return [row for row in subset if row["label"].startswith("real")]

    clock = returns(("0", "1"))
    if bigger(clock):
        clock_line = "Clock bars or volume bars: one reading is bigger than the fee."
    elif real(clock):
        clock_line = (
            "Short clock bars and volume bars: fading the last bar earns a little, and that little is smaller than the fee. "
            "The fifteen-minute and one-hour clock bars, and the one-hour volume bar, show nothing."
        )
    else:
        clock_line = "Clock bars and volume bars show nothing. Following the last bar, or fading it, does not clear the fee."

    gap = returns(("2",), contains="gap")
    gap_bigger = bigger(gap)
    if gap_bigger:
        gap_line = (
            "Futures versus spot: when futures are unusually cheap, the next hour's rise is a little bigger than the 0.0009 fee, "
            "and bigger than the 0.0006 fee too. The other gap readings are smaller than the fee, or show nothing."
        )
    elif real(gap):
        gap_line = "The futures-minus-spot gap shows a link, and it is smaller than the fee."
    else:
        gap_line = "An unusually wide futures-minus-spot gap shows nothing about the next futures move."

    lead = returns(("2",), contains="minute")
    if bigger(lead):
        lead_line = "Bitcoin and ether a minute apart: one reading is bigger than the fee."
    elif real(lead):
        lead_line = "Bitcoin and ether a minute apart: a tiny link, smaller than the fee."
    else:
        lead_line = "Ether's last minute does not predict bitcoin's next minute, and the reverse shows nothing either."

    size = [
        row
        for row in rows
        if row["frame"] == "3" and row["t_stat"] is not None and abs(row["t_stat"]) >= 2 and (row["correlation"] or 0) > 0
    ]
    if size:
        size_line = "A big move tends to be followed by another big move. That is calm or violent, not up or down, so it is not a fee test."
    else:
        size_line = "The size of a move does not reliably predict the size of the next one."

    quarter = returns(("4",), prefix="quarter")
    if bigger(quarter):
        quarter_line = "The first ten seconds of each quarter hour: one reading is bigger than the fee."
    elif real(quarter):
        quarter_line = "The first ten seconds of each quarter hour: a small link, smaller than the fee."
    else:
        quarter_line = "The first ten seconds after each quarter hour show nothing about the next hour or the next four hours."

    rest = [row for row in returns(("4",)) if not row["measure"].startswith("quarter")]
    funding = [row for row in rest if "funding" in row["measure"]]
    oi = [row for row in rest if "open interest" in row["measure"]]

    def corner(name: str, subset: list[dict]) -> str:
        above = [
            row
            for row in subset
            if row["gross_effect"] is not None and row["gross_effect"] > FEE_TAKER and not row["label"].startswith("bigger")
        ]
        if bigger(subset):
            return f"{name}: one reading is bigger than the fee."
        if above:
            return f"{name} can move more than the fee, but the evidence is too weak, so it counts as smaller than the fee."
        if real(subset):
            return f"{name} shows a link, and it is smaller than the fee."
        return f"{name} shows nothing."

    if funding or oi:
        rest_line = corner("Extreme funding", funding) + " " + corner("A sharp change in open interest", oi)
    else:
        rest_line = "Extreme funding and sharp open-interest changes show nothing."

    return [clock_line, gap_line, lead_line, size_line, quarter_line, rest_line]


def write_report(result: dict, md_path: Path, json_path: Path) -> None:
    rows = result["rows"]
    lines = _plain(rows)
    header = [
        "frame",
        "measure",
        "n",
        "gross effect per trade",
        "fee 0.0009",
        "effect / fee",
        "t-stat on daily totals",
        "label",
    ]
    table = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * len(header)) + " |",
    ]
    for row in rows:
        fee = "—" if row["fee"] is None else "0.0009"
        cells = [
            row["frame"],
            row["measure"],
            str(row["n"]),
            _fmt(row["gross_effect"]),
            fee,
            _fmt(row["effect_over_fee"], 3),
            _fmt(row["t_stat"], 2),
            row["label"],
        ]
        table.append("| " + " | ".join(cells) + " |")
    body = []
    body.extend(lines)
    body.append("")
    body.extend(table)
    body.append("")
    body.append(
        f"{len(rows)} rows were measured. With this many rows, one or two will look good by luck. That is why the bar is |t| >= 3.5."
    )
    body.append("")
    body.append(
        "Diagnostic on a seen period. Shows where to look. Not evidence of profit. Any idea from this table must be frozen and tested once on 2025-01 to 2026-10."
    )
    skipped = []
    notes = result["notes"]
    if notes.get("btc_spot_missing_months"):
        skipped.append("BTC spot missing months: " + ", ".join(notes["btc_spot_missing_months"]))
    if notes.get("eth_missing_months"):
        skipped.append("ETHUSDT perpetual missing months: " + ", ".join(notes["eth_missing_months"]))
    if str(notes.get("open_interest", "")).startswith("skipped"):
        skipped.append("Open interest was skipped. The monthly metrics archive returns 404 for this period, and no daily file was loaded.")
    elif notes.get("monthly_metrics_zip"):
        skipped.append("The monthly open-interest zip returns 404. The daily metrics archive for this period was used instead.")
    if skipped:
        body.append("")
        body.extend(skipped)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(body) + "\n")
    payload = dict(result)
    payload["plain"] = lines
    payload["rows_measured"] = len(rows)
    json_path.write_text(json.dumps(payload, indent=2) + "\n")


def main() -> None:
    root = Path(__file__).resolve().parents[2] / "data" / "history"
    result = measure(root)
    reports = Path(__file__).resolve().parents[2] / "reports"
    write_report(result, reports / "frame_check_2026-11-13.md", reports / "frame_check_2026-11-13.json")
    print(f"rows {len(result['rows'])}", flush=True)


if __name__ == "__main__":
    main()
