"""Cheap-futures diagnostic. One long-only rule, six train variants, then a gate.

The rolling threshold uses only the previous 30 days. A bar is usable only
after it closes. Nothing from 2025-01-01 onward is loaded unless the train
gate has passed and the holdout ledger has accepted the frozen rule.
"""

from __future__ import annotations

import bisect
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from config.costs import round_trip_cost
from src.backtest.download import ensure_funding, ensure_klines
from src.backtest.ledger import HoldoutRefused, register_holdout
from src.backtest.loader import load_funding, month_iter, read_klines_zip
from src.verification.graduation import daily_net_lower_bound
from src.backtest.sentence import cumulative_net_drawdown

MINUTE_MS = 60_000
WINDOW_MS = 30 * 24 * 60 * MINUTE_MS
COST = round_trip_cost("crypto", "futures", "taker", 0.0001)
COST_X2 = COST * 2.0
COST_X3 = COST * 3.0
Z = 2.88
RANDOM_SEED = 3558
PERCENTILES = (10, 5, 2)
HOLDS = ("1h", "4h")
HOLD_MS = {"1h": 60 * MINUTE_MS, "4h": 4 * 60 * MINUTE_MS}

TRAIN_WARMUP = "2020-11-01"
TRAIN_START = "2020-12-01"
TRAIN_END = "2022-10-31"
HOLDOUT_WARMUP = "2024-12-01"
HOLDOUT_START = "2025-01-01"
HOLDOUT_END = "2026-10-31"
FORBIDDEN_MONTH = "2025-01"
FORBIDDEN_DAY = "2025-01-01"


def _ms(day: str) -> int:
    return int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


def _day(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def _month(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m")


def _exclusive_end(day: str) -> int:
    return _ms(day) + 24 * 60 * MINUTE_MS


def calendar_days(start: str, end: str) -> list[str]:
    cur = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    last = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    out = []
    while cur <= last:
        out.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return out


def calendar_months(start: str, end: str) -> list[str]:
    months = []
    for day in calendar_days(start, end):
        month = day[:7]
        if not months or months[-1] != month:
            months.append(month)
    return months


class Fenwick:
    """Counts by rank. kth(k) is the smallest 1-based index whose prefix is at least k."""

    def __init__(self, n: int):
        self.n = int(n)
        self.t = [0] * (self.n + 1)

    def add(self, i: int, delta: int) -> None:
        while i <= self.n:
            self.t[i] += delta
            i += i & -i

    def kth(self, k: int) -> int:
        idx = 0
        bit = 1 << (self.n.bit_length() - 1)
        while bit:
            nxt = idx + bit
            if nxt <= self.n and self.t[nxt] < k:
                idx = nxt
                k -= self.t[nxt]
            bit >>= 1
        return idx + 1


def rolling_thresholds(ts: np.ndarray, values: np.ndarray, window_ms: int, quantiles: tuple[float, ...]) -> np.ndarray:
    """Threshold at each row from values in [ts - window, ts). The current row is excluded.

    The first rows, before a full window of time has passed, are NaN.
    Quantiles use the linear method: position (n - 1) * q inside the ordered window.
    """
    n = int(len(ts))
    out = np.full((n, len(quantiles)), np.nan, dtype=float)
    if n == 0:
        return out
    _unique, ranks = np.unique(values, return_inverse=True)
    ranks = ranks.astype(np.int32) + 1
    tree = Fenwick(int(_unique.size))
    alive = 0
    left = 0
    first = int(ts[0])
    ordered = _unique
    for i in range(n):
        now = int(ts[i])
        cutoff = now - int(window_ms)
        while left < i and int(ts[left]) < cutoff:
            tree.add(int(ranks[left]), -1)
            alive -= 1
            left += 1
        if alive > 0 and now - first >= int(window_ms):
            pos_base = alive - 1
            for q_i, q in enumerate(quantiles):
                pos = pos_base * float(q)
                lo = int(math.floor(pos))
                hi = int(math.ceil(pos))
                vlo = float(ordered[tree.kth(lo + 1) - 1])
                vhi = float(ordered[tree.kth(hi + 1) - 1])
                out[i, q_i] = vlo * (1.0 - (pos - lo)) + vhi * (pos - lo)
        tree.add(int(ranks[i]), 1)
        alive += 1
    return out


def guard_months(start_month: str, end_month: str, allow_2025: bool) -> None:
    if not allow_2025 and (start_month >= FORBIDDEN_MONTH or end_month >= FORBIDDEN_MONTH):
        raise RuntimeError("2025-01 onward is reserved and was not loaded")


def load_klines(root: Path, market: str, start_month: str, end_month: str, lo: int, hi: int, allow_2025: bool) -> tuple[list[dict], list[str]]:
    guard_months(start_month, end_month, allow_2025)
    folder = root / ("futures" if market == "futures" else "spot") / "BTCUSDT"
    source = "BINANCE_UM" if market == "futures" else "BINANCE_SPOT"
    candles: list[dict] = []
    missing = []
    for month in month_iter(start_month, end_month):
        if not allow_2025 and month >= FORBIDDEN_MONTH:
            raise RuntimeError(month)
        path = folder / f"BTCUSDT-1m-{month}.zip"
        if not path.exists() or path.stat().st_size <= 0:
            missing.append(month)
            continue
        candles.extend(read_klines_zip(path, "BTCUSDT", source))
    kept = []
    for candle in candles:
        ts = int(candle["timestamp"])
        if ts < lo or ts >= hi:
            continue
        if not allow_2025 and ts >= _ms(FORBIDDEN_DAY):
            raise RuntimeError("a 2025 timestamp was read during the closed period")
        kept.append(candle)
    kept.sort(key=lambda c: int(c["timestamp"]))
    deduped = []
    seen = None
    for candle in kept:
        ts = int(candle["timestamp"])
        if ts == seen:
            deduped[-1] = candle
        else:
            deduped.append(candle)
            seen = ts
    return deduped, missing


def load_funding_range(root: Path, start_month: str, end_month: str, lo: int, hi: int, allow_2025: bool) -> tuple[np.ndarray, np.ndarray, list[str]]:
    guard_months(start_month, end_month, allow_2025)
    folder = root / "funding" / "BTCUSDT"
    missing = []
    for month in month_iter(start_month, end_month):
        if not allow_2025 and month >= FORBIDDEN_MONTH:
            raise RuntimeError(month)
        path = folder / f"BTCUSDT-fundingRate-{month}.zip"
        if not path.exists() or path.stat().st_size <= 0:
            missing.append(month)
    rows = [(int(ts), float(rate)) for ts, rate in load_funding(root, "BTCUSDT", start_month, end_month) if lo <= int(ts) < hi]
    if not allow_2025:
        for ts, _rate in rows:
            if ts >= _ms(FORBIDDEN_DAY):
                raise RuntimeError("funding from 2025 was read during the closed period")
    rows.sort()
    if not rows:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=float), missing
    return np.asarray([r[0] for r in rows], dtype=np.int64), np.asarray([r[1] for r in rows], dtype=float), missing


def align_gaps(futures: list[dict], spot: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    spot_close = {int(c["timestamp"]): float(c["close"]) for c in spot}
    ts = []
    gap = []
    for candle in futures:
        stamp = int(candle["timestamp"])
        other = spot_close.get(stamp)
        if other is None or other == 0.0 or float(candle["close"]) == 0.0:
            continue
        ts.append(stamp)
        gap.append(float(candle["close"]) / other - 1.0)
    return np.asarray(ts, dtype=np.int64), np.asarray(gap, dtype=float)


def opens_of(candles: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    return (
        np.asarray([int(c["timestamp"]) for c in candles], dtype=np.int64),
        np.asarray([float(c["open"]) for c in candles], dtype=float),
    )


def lookup(ts: np.ndarray, px: np.ndarray, query: np.ndarray) -> np.ndarray:
    out = np.full(len(query), np.nan, dtype=float)
    if len(query) == 0 or len(ts) == 0:
        return out
    idx = np.searchsorted(ts, query)
    valid = idx < len(ts)
    idx2 = np.where(valid, idx, 0)
    match = valid & (ts[idx2] == query)
    out[match] = px[idx2[match]]
    return out


def funding_between(fund_ts: np.ndarray, fund_rate: np.ndarray, entry: np.ndarray, exit_: np.ndarray) -> np.ndarray:
    """Long funding. A positive rate is paid. Events in (entry, exit] count."""
    out = np.zeros(len(entry), dtype=float)
    if len(fund_ts) == 0 or len(entry) == 0:
        return out
    prefix = np.zeros(len(fund_rate) + 1, dtype=float)
    prefix[1:] = np.cumsum(fund_rate)
    right = np.searchsorted(fund_ts, exit_, side="right")
    left = np.searchsorted(fund_ts, entry, side="right")
    return prefix[right] - prefix[left]


def position_entries(signal_ts: np.ndarray, hold_ms: int, open_ts: np.ndarray) -> tuple[list[tuple[int, int, int]], int]:
    """One position. Entry is the next 1m open. A missing entry open is skipped and does not block."""
    opens = set(int(t) for t in open_ts.tolist())
    next_free = 0
    rows: list[tuple[int, int, int]] = []
    skipped = 0
    for sig in signal_ts.tolist():
        entry = int(sig) + MINUTE_MS
        if entry < next_free:
            continue
        if entry not in opens:
            skipped += 1
            continue
        exit_ = entry + int(hold_ms)
        rows.append((int(sig), entry, exit_))
        next_free = exit_
    return rows, skipped


def score_entries(
    entries: list[tuple[int, int, int]],
    fut_ts: np.ndarray,
    fut_open: np.ndarray,
    spot_ts: np.ndarray,
    spot_open: np.ndarray,
    fund_ts: np.ndarray,
    fund_rate: np.ndarray,
    eval_start: int,
    eval_end: int,
) -> list[dict]:
    if not entries:
        return []
    signal = np.asarray([e[0] for e in entries], dtype=np.int64)
    entry = np.asarray([e[1] for e in entries], dtype=np.int64)
    exit_ = np.asarray([e[2] for e in entries], dtype=np.int64)
    fe = lookup(fut_ts, fut_open, entry)
    fx = lookup(fut_ts, fut_open, exit_)
    se = lookup(spot_ts, spot_open, entry)
    sx = lookup(spot_ts, spot_open, exit_)
    paid = funding_between(fund_ts, fund_rate, entry, exit_)
    gross = np.where((fe > 0) & np.isfinite(fx), fx / fe - 1.0, np.nan)
    spot_gross = np.where((se > 0) & np.isfinite(sx), sx / se - 1.0, np.nan)
    in_window = (entry >= eval_start) & (entry < eval_end) & (exit_ < eval_end)
    scored = in_window & np.isfinite(gross)
    rows = []
    for i in range(len(entries)):
        if not bool(scored[i]):
            continue
        g = float(gross[i])
        f = float(paid[i])
        rows.append(
            {
                "signal_ts": int(signal[i]),
                "entry_ts": int(entry[i]),
                "exit_ts": int(exit_[i]),
                "day": _day(int(entry[i])),
                "month": _month(int(entry[i])),
                "gross": g,
                "spot_gross": None if not np.isfinite(spot_gross[i]) else float(spot_gross[i]),
                "funding": f,
                "net": g - COST - f,
                "net_x2": g - COST_X2 - f,
                "net_x3": g - COST_X3 - f,
                "cost": COST,
            }
        )
    return rows


def signals_for(ts: np.ndarray, gap: np.ndarray, window_ms: int = WINDOW_MS) -> dict[int, np.ndarray]:
    quantiles = tuple(p / 100.0 for p in PERCENTILES)
    thresholds = rolling_thresholds(ts, gap, window_ms, quantiles)
    out = {}
    for i, p in enumerate(PERCENTILES):
        below = np.isfinite(thresholds[:, i]) & (gap < thresholds[:, i])
        out[p] = ts[below]
    return out


def run_variant(
    signal_ts: np.ndarray,
    hold_name: str,
    fut_ts: np.ndarray,
    fut_open: np.ndarray,
    spot_ts: np.ndarray,
    spot_open: np.ndarray,
    fund_ts: np.ndarray,
    fund_rate: np.ndarray,
    eval_start: int,
    eval_end: int,
) -> dict:
    entries, skipped_entry = position_entries(signal_ts, HOLD_MS[hold_name], fut_ts)
    trades = score_entries(entries, fut_ts, fut_open, spot_ts, spot_open, fund_ts, fund_rate, eval_start, eval_end)
    return {"trades": trades, "decisions": entries, "skipped_missing_entry": skipped_entry}


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return float(sum(values) / len(values))


def losing_streak(nets: list[float]) -> int:
    best = current = 0
    for net in nets:
        if net < 0:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def summarize_variant(name: str, trades: list[dict], days: list[str], months: list[str], z: float | None) -> dict:
    nets = [t["net"] for t in trades]
    grosses = [t["gross"] for t in trades]
    net_x2 = [t["net_x2"] for t in trades]
    net_x3 = [t["net_x3"] for t in trades]
    spots = [t["spot_gross"] for t in trades if t["spot_gross"] is not None]
    by_month = {m: 0.0 for m in months}
    daily = {d: 0.0 for d in days}
    for trade in trades:
        by_month[trade["month"]] = by_month.get(trade["month"], 0.0) + trade["net"]
        daily[trade["day"]] = daily.get(trade["day"], 0.0) + trade["net"]
    positive = sum(1 for m in months if by_month.get(m, 0.0) > 0)
    totals = [daily[d] for d in days]
    hits = [g > 0 for g in grosses]
    return {
        "variant": name,
        "trades": len(trades),
        "days_with_trades": len({t["day"] for t in trades}),
        "gross_mean": _mean(grosses),
        "net_mean": _mean(nets),
        "net_mean_x2": _mean(net_x2),
        "net_mean_x3": _mean(net_x3),
        "spot_mean": _mean(spots),
        "spot_n": len(spots),
        "positive_month_share": (positive / len(months)) if months else None,
        "positive_months": positive,
        "months": len(months),
        "worst_trade": min(nets) if nets else None,
        "best_trade": max(nets) if nets else None,
        "net_by_month": by_month,
        "daily_totals": totals,
        "days": days,
        "net_lb": daily_net_lower_bound(totals, z) if z is not None and totals else None,
        "cumulative_net": float(sum(nets)) if nets else 0.0,
        "max_dd_net": cumulative_net_drawdown(nets) if nets else 0.0,
        "losing_streak": losing_streak(nets) if nets else 0,
        "wins": sum(1 for h in hits if h),
        "losses": sum(1 for h in hits if not h),
        "hit_rate": (sum(hits) / len(hits)) if hits else None,
        "funding_mean": _mean([t["funding"] for t in trades]),
        "kept": False,
    }


def keep_winner(rows: list[dict]) -> dict:
    """Highest net mean at cost x2. Ties break toward more trades, then the stricter percentile, then the shorter hold."""

    def key(row: dict):
        net = row["net_mean_x2"]
        p = int(row["variant"].split()[0][1:])
        hold = 0 if row["variant"].endswith("1h") else 1
        return (net if net is not None else -1e9, row["trades"], -p, -hold)

    winner = max(rows, key=key)
    for row in rows:
        row["kept"] = row["variant"] == winner["variant"]
    return winner


def gate_passes(winner: dict) -> bool:
    net = winner.get("net_mean_x2")
    return bool(net is not None and net > 0 and int(winner["trades"]) >= 100)


def month_counts(trades: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for trade in trades:
        counts[trade["month"]] = counts.get(trade["month"], 0) + 1
    return counts


def scorable_entries(fut_ts: np.ndarray, hold_ms: int, eval_start: int, eval_end: int) -> dict[str, list[int]]:
    opens = set(int(t) for t in fut_ts.tolist())
    by_month: dict[str, list[int]] = {}
    for ts in fut_ts.tolist():
        entry = int(ts)
        if entry < eval_start or entry >= eval_end:
            continue
        exit_ = entry + hold_ms
        if exit_ >= eval_end or exit_ not in opens:
            continue
        by_month.setdefault(_month(entry), []).append(entry)
    return by_month


def _overlaps_sorted(entry: int, hold_ms: int, accepted: list[int]) -> bool:
    """`accepted` is sorted entry times. Each trade occupies [entry, entry + hold)."""
    i = bisect.bisect_right(accepted, entry)
    if i > 0 and accepted[i - 1] + hold_ms > entry:
        return True
    if i < len(accepted) and entry + hold_ms > accepted[i]:
        return True
    return False


def _place_random(by_month: dict[str, list[int]], counts: dict[str, int], hold_ms: int, seed: int) -> tuple[list[int], dict]:
    """Same count per month, at random minutes, with no two holds overlapping.

    A shuffle then a greedy accept. Trades may sit anywhere in the month, and a
    hold that runs past midnight still blocks the next month.
    """
    rng = np.random.default_rng(seed)
    accepted: list[int] = []
    chosen = []
    short = {}
    for month in sorted(counts):
        need = int(counts[month])
        cands = [t for t in by_month.get(month, []) if not _overlaps_sorted(t, hold_ms, accepted)]
        rng.shuffle(cands)
        got = 0
        for entry in cands:
            if got >= need:
                break
            if _overlaps_sorted(entry, hold_ms, accepted):
                continue
            bisect.insort(accepted, entry)
            chosen.append(entry)
            got += 1
        if got < need:
            short[month] = {"needed": need, "placed": got}
    return chosen, short


def random_long_entries(by_month: dict[str, list[int]], counts: dict[str, int], hold_ms: int, seed: int = RANDOM_SEED) -> dict:
    best: tuple[list[int], dict, int] | None = None
    for offset in range(20):
        chosen, short = _place_random(by_month, counts, hold_ms, seed + offset)
        if best is None or len(chosen) > len(best[0]):
            best = (chosen, short, seed + offset)
        if not short:
            best = (chosen, short, seed + offset)
            break
    assert best is not None
    entries = [(entry - MINUTE_MS, entry, entry + hold_ms) for entry in best[0]]
    return {"entries": entries, "short": best[1], "seed": best[2], "placed": len(entries), "requested": int(sum(counts.values()))}


def peek_entries(fut_ts: np.ndarray, fut_open: np.ndarray, hold_ms: int, eval_start: int, eval_end: int) -> list[tuple[int, int, int]]:
    """Long only when the hold's rise, known here on purpose, is larger than the round-trip cost."""
    opens = {int(t): float(px) for t, px in zip(fut_ts.tolist(), fut_open.tolist())}
    next_free = 0
    rows = []
    for entry in fut_ts.tolist():
        entry = int(entry)
        if entry < next_free or entry < eval_start or entry >= eval_end:
            continue
        exit_ = entry + hold_ms
        if exit_ >= eval_end or exit_ not in opens:
            continue
        fe = opens[entry]
        fx = opens[exit_]
        if fe <= 0:
            continue
        gross = fx / fe - 1.0
        if gross <= COST:
            continue
        rows.append((entry - MINUTE_MS, entry, exit_))
        next_free = exit_
    return rows


def data_gaps(fut_ts: np.ndarray, spot_ts: np.ndarray, eval_start: int, eval_end: int) -> dict:
    expected = int((eval_end - eval_start) // MINUTE_MS)
    fut_eval = fut_ts[(fut_ts >= eval_start) & (fut_ts < eval_end)]
    missing_fut = int(expected - len(fut_eval))
    without_spot = 0
    if len(fut_eval) and len(spot_ts):
        idx = np.searchsorted(spot_ts, fut_eval)
        valid = idx < len(spot_ts)
        idx2 = np.where(valid, idx, 0)
        without_spot = int(np.sum(~(valid & (spot_ts[idx2] == fut_eval))))
    elif len(fut_eval):
        without_spot = int(len(fut_eval))
    return {
        "expected_minutes": expected,
        "present_futures_minutes": int(len(fut_eval)),
        "missing_futures_minutes": missing_fut,
        "missing_futures_share": (missing_fut / expected) if expected else None,
        "futures_minutes_without_spot": without_spot,
    }


def decisions_before(entries: list[tuple[int, int, int]], cut: int) -> list[tuple[int, int, int]]:
    return [row for row in entries if row[1] < cut]


def truncation_ok(full: list[tuple[int, int, int]], truncated: list[tuple[int, int, int]], cut: int) -> bool:
    return decisions_before(full, cut) == decisions_before(truncated, cut)


def profit_spread_ok(net_by_month: dict[str, float]) -> bool:
    positive = [v for v in net_by_month.values() if v > 0]
    if not positive:
        return True
    return max(positive) <= 0.5 * sum(positive)


def clearly_better(rule_daily: list[float], random_daily: list[float], rule_net: float | None, random_net: float | None, matched: bool) -> dict:
    diff = [a - b for a, b in zip(rule_daily, random_daily)]
    lb = daily_net_lower_bound(diff, Z) if diff else None
    higher = rule_net is not None and random_net is not None and rule_net > random_net
    clear = bool(matched and higher and lb is not None and lb > 0)
    return {"difference_net_lb": lb, "rule_higher": higher, "matched_count": matched, "clearly_better": clear}


def step3_flags(summary: dict, train_net: float | None, holdout: bool) -> list[str]:
    flags = []
    hit = summary.get("hit_rate")
    if hit is not None and hit > 0.60:
        flags.append(f"hit rate {hit:.3f} is above 60%")
    net = summary.get("net_mean")
    if net is not None and net > COST:
        flags.append("net mean per trade is larger than the 0.0012 cost")
    if holdout and train_net is not None and net is not None and summary["trades"] >= 300 and net > train_net:
        flags.append("holdout net mean is better than the seen period")
    if summary["trades"] >= 300 and summary["cumulative_net"] > 0 and summary["max_dd_net"] < 0.05 * summary["cumulative_net"]:
        flags.append("the cumulative path gives back less than 5% of its gain")
    if not profit_spread_ok(summary["net_by_month"]):
        flags.append("more than half the positive net sits in one month")
    return flags


def step4_verdict(summary: dict, controls: dict, flags: list[str]) -> str:
    """Checklist Step 4, plus the operator's random-long bar for CONTINUE."""
    gaps = controls["gaps"]["missing_futures_share"]
    if controls["truncation"] != "identical: yes":
        return "RERUN"
    if controls["peek_net_mean"] is None or controls["peek_net_mean"] <= 0:
        return "RERUN"
    if gaps is None or gaps >= 0.01:
        return "RERUN"
    if summary["trades"] < 300 or summary["days_with_trades"] < 60:
        return "TOO EARLY"
    gross = summary["gross_mean"]
    net = summary["net_mean"]
    if gross is None or gross <= 0:
        return "STOP this track"
    if net is None or net <= 0:
        return "STOP as built"
    if summary["net_lb"] is None or summary["net_lb"] <= 0:
        return "NOT PROVEN"
    if summary["net_mean_x2"] is None or summary["net_mean_x2"] <= 0 or flags:
        return "NOT PROVEN"
    if not controls["random"]["clearly_better"]:
        return "NOT PROVEN"
    return "CONTINUE"


def prepare_series(root: Path, start_month: str, end_month: str, lo: int, hi: int, allow_2025: bool) -> dict:
    futures, fut_missing = load_klines(root, "futures", start_month, end_month, lo, hi, allow_2025)
    spot, spot_missing = load_klines(root, "spot", start_month, end_month, lo, hi, allow_2025)
    fund_ts, fund_rate, fund_missing = load_funding_range(root, start_month, end_month, lo, hi, allow_2025)
    gap_ts, gap = align_gaps(futures, spot)
    fut_ts, fut_open = opens_of(futures)
    spot_ts, spot_open = opens_of(spot)
    return {
        "gap_ts": gap_ts,
        "gap": gap,
        "fut_ts": fut_ts,
        "fut_open": fut_open,
        "spot_ts": spot_ts,
        "spot_open": spot_open,
        "fund_ts": fund_ts,
        "fund_rate": fund_rate,
        "missing_futures_months": fut_missing,
        "missing_spot_months": spot_missing,
        "missing_funding_months": fund_missing,
    }


def evaluate_period(series: dict, eval_start: int, eval_end: int, days: list[str], months: list[str], z: float | None) -> list[dict]:
    print("  rolling 30-day thresholds", flush=True)
    found = signals_for(series["gap_ts"], series["gap"])
    rows = []
    for p in PERCENTILES:
        for hold in HOLDS:
            name = f"P{p} {hold}"
            print(f"  variant {name}", flush=True)
            ran = run_variant(
                found[p],
                hold,
                series["fut_ts"],
                series["fut_open"],
                series["spot_ts"],
                series["spot_open"],
                series["fund_ts"],
                series["fund_rate"],
                eval_start,
                eval_end,
            )
            summary = summarize_variant(name, ran["trades"], days, months, z)
            summary["percentile"] = p
            summary["hold"] = hold
            summary["skipped_missing_entry"] = ran["skipped_missing_entry"]
            summary["trade_rows"] = ran["trades"]
            summary["decisions"] = ran["decisions"]
            rows.append(summary)
    return rows


def _decisions(series: dict, percentile: int, hold: str, eval_start: int, eval_end: int) -> list[tuple[int, int, int]]:
    found = signals_for(series["gap_ts"], series["gap"])
    ran = run_variant(
        found[percentile],
        hold,
        series["fut_ts"],
        series["fut_open"],
        series["spot_ts"],
        series["spot_open"],
        series["fund_ts"],
        series["fund_rate"],
        eval_start,
        eval_end,
    )
    return ran["decisions"]


def truncation_status(series: dict, winner: dict, eval_start: int, eval_end: int, cut: int) -> str:
    """Calls before `cut` must match when the tape stops at cut and when it stops one day later."""
    early = slice_series(series, cut)
    later = slice_series(series, cut + 24 * 60 * MINUTE_MS)
    early_rows = _decisions(early, winner["percentile"], winner["hold"], eval_start, eval_end)
    later_rows = _decisions(later, winner["percentile"], winner["hold"], eval_start, eval_end)
    same = truncation_ok(later_rows, early_rows, cut)
    return "identical: yes" if same else "identical: no"


def controls_for(series: dict, winner: dict, eval_start: int, eval_end: int, days: list[str], cut: int) -> dict:
    hold = winner["hold"]
    hold_ms = HOLD_MS[hold]
    counts = month_counts(winner["trade_rows"])
    by_month = scorable_entries(series["fut_ts"], hold_ms, eval_start, eval_end)
    drawn = random_long_entries(by_month, counts, hold_ms)
    random_trades = score_entries(
        drawn["entries"],
        series["fut_ts"],
        series["fut_open"],
        series["spot_ts"],
        series["spot_open"],
        series["fund_ts"],
        series["fund_rate"],
        eval_start,
        eval_end,
    )
    months = calendar_months(_day(eval_start), _day(eval_end - MINUTE_MS))
    random_summary = summarize_variant("RANDOM LONG", random_trades, days, months, Z)
    matched = drawn["placed"] == drawn["requested"] and not drawn["short"]
    comparison = clearly_better(winner["daily_totals"], random_summary["daily_totals"], winner["net_mean"], random_summary["net_mean"], matched)
    comparison["placed"] = drawn["placed"]
    comparison["requested"] = drawn["requested"]
    comparison["seed"] = drawn["seed"]
    comparison["short"] = drawn["short"]
    comparison["net_mean"] = random_summary["net_mean"]
    comparison["gross_mean"] = random_summary["gross_mean"]
    comparison["trades"] = random_summary["trades"]
    peek = peek_entries(series["fut_ts"], series["fut_open"], hold_ms, eval_start, eval_end)
    peek_trades = score_entries(
        peek,
        series["fut_ts"],
        series["fut_open"],
        series["spot_ts"],
        series["spot_open"],
        series["fund_ts"],
        series["fund_rate"],
        eval_start,
        eval_end,
    )
    return {
        "random": comparison,
        "peek_trades": len(peek_trades),
        "peek_net_mean": _mean([t["net"] for t in peek_trades]),
        "peek_gross_mean": _mean([t["gross"] for t in peek_trades]),
        "truncation": truncation_status(series, winner, eval_start, eval_end, cut),
        "gaps": data_gaps(series["fut_ts"], series["spot_ts"], eval_start, eval_end),
    }


def slice_series(series: dict, hi: int) -> dict:
    def cut_ts(ts, *arrays):
        keep = ts < hi
        return (ts[keep],) + tuple(arr[keep] for arr in arrays)

    gap_ts, gap = cut_ts(series["gap_ts"], series["gap"])
    fut_ts, fut_open = cut_ts(series["fut_ts"], series["fut_open"])
    spot_ts, spot_open = cut_ts(series["spot_ts"], series["spot_open"])
    fund_ts, fund_rate = cut_ts(series["fund_ts"], series["fund_rate"])
    return {
        "gap_ts": gap_ts,
        "gap": gap,
        "fut_ts": fut_ts,
        "fut_open": fut_open,
        "spot_ts": spot_ts,
        "spot_open": spot_open,
        "fund_ts": fund_ts,
        "fund_rate": fund_rate,
    }


def frozen_payload(winner: dict) -> dict:
    return {
        "name": "CHEAP FUTURES",
        "symbol": "BTCUSDT",
        "market": "USD-M perpetual",
        "rule_sets_tried": 4,
        "K": 1,
        "variants_chosen_from": 6,
        "z": Z,
        "percentile": winner["percentile"],
        "hold": winner["hold"],
        "hold_ms": HOLD_MS[winner["hold"]],
        "lookback": "previous 30 days, rolling, current minute excluded",
        "gap": "perpetual close / spot close - 1",
        "entry": "next 1m open",
        "exit": "1m open after the hold",
        "stop": False,
        "one_position_at_a_time": True,
        "side": "long",
        "cost": COST,
        "cost_x2": COST_X2,
        "cost_x3": COST_X3,
        "cost_parts": {"taker_in": 0.0005, "taker_out": 0.0005, "spread": 0.0001, "slippage": 0.0001},
        "spread_assumed": True,
        "funding": "applied, long pays a positive rate",
        "train_warmup": TRAIN_WARMUP,
        "train_start": TRAIN_START,
        "train_end": TRAIN_END,
        "holdout_warmup": HOLDOUT_WARMUP,
        "holdout_start": HOLDOUT_START,
        "holdout_end": HOLDOUT_END,
        "closed_candles_only": True,
        "train_net_mean_x2": winner["net_mean_x2"],
        "train_trades": winner["trades"],
    }


def _fmt(value, digits=6) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}g}"
    return str(value)


def _plain(result: dict) -> list[str]:
    winner = result["winner"]
    if result.get("ledger_refused"):
        return [
            "The seen-period gate passed, so one setting was ready to freeze.",
            "The holdout ledger refused 2025-01-01 to 2026-10-31 because that window overlaps an earlier holdout.",
            "No 2025 or 2026 prices were loaded, and the frozen file was put back.",
            f"The setting that would have been frozen was {winner['variant']}.",
            "Holdout untouched. rule_sets_tried stays 3.",
            "No further variants.",
        ]
    if not result["gate_passed"]:
        lines = [
            "This stopped on the years already seen. The 2025 and 2026 holdout was not opened.",
            f"Of the six settings, {winner['variant']} had the highest result after a doubled fee.",
        ]
        net = winner["net_mean_x2"]
        if net is None or net <= 0:
            lines.append("Even that best setting loses money once the fee is doubled, so the gate stopped the test.")
        elif winner["trades"] < 100:
            lines.append("The doubled fee was still positive, but there were fewer than 100 trades, so the gate stopped the test.")
        spot = winner.get("spot_mean")
        gross = winner.get("gross_mean")
        if spot is not None and gross is not None and gross > 0 and spot > 0.5 * gross:
            lines.append(
                f"On those same holds the futures price rose about {_fmt(gross)} and the spot price rose about {_fmt(spot)}, so most of that rise was the price itself."
            )
        elif spot is not None and gross is not None:
            lines.append(f"On those same holds the futures price moved about {_fmt(gross)} and the spot price moved about {_fmt(spot)}.")
        random_net = result["train_controls"]["random"]["net_mean"]
        lines.append(f"Buying the same number of times at random minutes made about {_fmt(random_net)} after costs.")
        lines.append("No further variants. rule_sets_tried stays 3.")
        return lines[:6]
    verdict = result["verdict"]
    holdout = result["holdout"]
    lines = [
        f"The setting kept from the seen years was {winner['variant']}. One frozen rule was then run once on 2025-01-01 to 2026-10-31.",
        f"On the holdout it made about {_fmt(holdout['net_mean'])} per trade after costs, before the luck bound.",
    ]
    spot = holdout.get("spot_mean")
    lines.append(
        f"Over those same holds, futures moved about {_fmt(holdout['gross_mean'])} and spot moved about {_fmt(spot)}."
    )
    random_net = result["holdout_controls"]["random"]["net_mean"]
    if result["holdout_controls"]["random"]["clearly_better"]:
        lines.append(f"It was clearly better than buying at random minutes, which made about {_fmt(random_net)}.")
    else:
        lines.append(f"It was not clearly better than buying at random minutes, which made about {_fmt(random_net)}.")
    if verdict == "CONTINUE":
        lines.append("Decision: CONTINUE. That means paper tracking only. Nothing else is unlocked.")
    else:
        lines.append(f"Decision: {verdict}.")
    lines.append("No further variants.")
    return lines[:6]


def write_report(result: dict, md_path: Path, json_path: Path) -> None:
    lines = _plain(result)
    header = [
        "variant",
        "trades",
        "days with trades",
        "gross mean",
        "net mean",
        "net mean at cost x2",
        "share of months with positive net",
        "worst single trade",
        "kept",
    ]
    table = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * len(header)) + " |"]
    for row in result["train"]:
        cells = [
            row["variant"],
            str(row["trades"]),
            str(row["days_with_trades"]),
            _fmt(row["gross_mean"]),
            _fmt(row["net_mean"]),
            _fmt(row["net_mean_x2"]),
            _fmt(row["positive_month_share"], 3),
            _fmt(row["worst_trade"]),
            "yes" if row["kept"] else "",
        ]
        table.append("| " + " | ".join(cells) + " |")
    body = list(lines)
    body.append("")
    body.append(f"Kept variant: {result['winner']['variant']}.")
    if result.get("ledger_refused"):
        body.append("The gate passed, but the holdout ledger refused the window. Holdout untouched.")
        body.append(result["ledger_refused"])
    elif result["gate_passed"]:
        body.append("The gate passed: net mean at cost x2 was above zero and there were at least 100 trades.")
    else:
        body.append("STOPPED AT STEP 1 - holdout untouched")
    body.append("")
    body.append("Step 1. Seen period 2020-12-01 to 2022-10-31. November 2020 is warm-up for the 30-day window only.")
    body.append("")
    body.extend(table)
    body.append("")
    train_controls = result["train_controls"]
    body.append(
        f"Train controls for {result['winner']['variant']}: "
        f"truncation {train_controls['truncation']}; "
        f"RANDOM LONG net {_fmt(train_controls['random']['net_mean'])} "
        f"on {train_controls['random']['placed']} of {train_controls['random']['requested']} trades "
        f"(seed {train_controls['random']['seed']}); "
        f"spot mean over the same holds {_fmt(result['winner']['spot_mean'])}; "
        f"PEEK net {_fmt(train_controls['peek_net_mean'])} on {train_controls['peek_trades']} trades; "
        f"missing futures minutes {train_controls['gaps']['missing_futures_minutes']} "
        f"of {train_controls['gaps']['expected_minutes']}."
    )
    body.append("Cost is 0.0012 per trade (taker in, taker out, spread 0.0001, slippage 0.0001). Funding is applied on top and is not doubled when the cost is doubled. Cost x2 is 0.0024.")
    body.append("Share of months uses every calendar month in the seen window. A month with no trades counts as not positive.")
    if result.get("holdout"):
        holdout = result["holdout"]
        controls = result["holdout_controls"]
        body.append("")
        body.append("Step 2. Holdout 2025-01-01 to 2026-10-31. December 2024 is warm-up only. K = 1 track chosen from 6, so z = 2.88. rule_sets_tried = 4.")
        body.append(f"Counted trades: {holdout['trades']}")
        body.append(f"Days with trades: {holdout['days_with_trades']} of {len(holdout['days'])} calendar days")
        body.append(f"Gross mean: {_fmt(holdout['gross_mean'])}")
        body.append(f"Net mean: {_fmt(holdout['net_mean'])}")
        body.append(f"net_lb on daily totals: {_fmt(holdout['net_lb'])}")
        body.append(f"Net mean at cost x2: {_fmt(holdout['net_mean_x2'])}")
        body.append(f"Net mean at cost x3: {_fmt(holdout['net_mean_x3'])}")
        body.append(
            f"RANDOM LONG net: {_fmt(controls['random']['net_mean'])} "
            f"({controls['random']['placed']} of {controls['random']['requested']} trades, seed {controls['random']['seed']})"
        )
        body.append(f"Spot mean over the same holds: {_fmt(holdout['spot_mean'])}")
        body.append(f"Cumulative net percent: {_fmt(holdout['cumulative_net'] * 100)}")
        body.append(f"Worst trade: {_fmt(holdout['worst_trade'])}")
        body.append(f"Longest losing streak (consecutive trades with net below zero): {holdout['losing_streak']}")
        body.append(f"Max drawdown of cumulative net, percent: {_fmt(holdout['max_dd_net'] * 100)}")
        body.append(f"Wins / losses / timeouts / blocked-by-cost / NOT_FILLED: {holdout['wins']} / {holdout['losses']} / 0 / 0 / 0")
        body.append(f"Hit rate: {_fmt(holdout['hit_rate'], 4)}")
        body.append("Same-candle cases: 0. There is no stop. The exit is a later open.")
        body.append(f"spread_assumed share: 1. funding_ignored share: {_fmt(result.get('funding_ignored_share'), 3)}")
        body.append(f"Truncation: {controls['truncation']}. PEEK net: {_fmt(controls['peek_net_mean'])}.")
        body.append(
            f"Missing futures minutes: {controls['gaps']['missing_futures_minutes']} "
            f"of {controls['gaps']['expected_minutes']}."
        )
        body.append("Net by month:")
        for month, value in holdout["net_by_month"].items():
            body.append(f"- {month}: {_fmt(value)}")
        body.append("")
        body.append(f"DECISION: {result['verdict']}")
        if result["verdict"] == "CONTINUE":
            body.append("CONTINUE means paper tracking only. Nothing else is unlocked.")
        if result["flags"]:
            body.append("Step 3 flags: " + "; ".join(result["flags"]))
        else:
            body.append("Step 3 flags: none.")
    else:
        body.append("")
        if result.get("ledger_refused"):
            body.append(f"DECISION: {result['verdict']}")
            body.append("Checklist Step 4 was not applied. The holdout was not loaded.")
        else:
            body.append("DECISION: STOPPED AT STEP 1 - holdout untouched")
            body.append("Checklist Step 4 was not applied. Only a holdout can decide CONTINUE, and this holdout was not loaded.")
    body.append("")
    body.append("No further variants. Stop.")
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(body) + "\n")
    payload = _public_result(result)
    payload["plain"] = lines
    json_path.write_text(json.dumps(payload, indent=2) + "\n")


def _public_row(row: dict) -> dict:
    skip = {"trade_rows", "decisions", "daily_totals", "days"}
    return {key: value for key, value in row.items() if key not in skip}


def _public_result(result: dict) -> dict:
    out = {
        "period_train": f"{TRAIN_START} to {TRAIN_END}",
        "warmup_train": TRAIN_WARMUP,
        "cost": COST,
        "cost_x2": COST_X2,
        "gate_passed": result["gate_passed"],
        "winner": result["winner"]["variant"],
        "rule_sets_tried": 4 if result.get("holdout") else 3,
        "train": [_public_row(row) for row in result["train"]],
        "train_controls": result["train_controls"],
        "verdict": result["verdict"],
    }
    if result["gate_passed"]:
        out["holdout"] = _public_row(result["holdout"])
        out["holdout_controls"] = result["holdout_controls"]
        out["flags"] = result["flags"]
        out["K"] = 1
        out["z"] = Z
        out["ledger"] = result.get("ledger")
    return out


def run_train(root: Path) -> tuple[dict, list[dict], dict]:
    lo = _ms(TRAIN_WARMUP)
    hi = _exclusive_end(TRAIN_END)
    print("load train 2020-11 to 2022-10", flush=True)
    series = prepare_series(root, "2020-11", "2022-10", lo, hi, allow_2025=False)
    days = calendar_days(TRAIN_START, TRAIN_END)
    months = calendar_months(TRAIN_START, TRAIN_END)
    rows = evaluate_period(series, _ms(TRAIN_START), hi, days, months, z=None)
    winner = keep_winner(rows)
    print("truncation cut at 2022-10-30", flush=True)
    controls = controls_for(series, winner, _ms(TRAIN_START), hi, days, _ms("2022-10-30"))
    controls["missing_futures_months"] = series["missing_futures_months"]
    controls["missing_spot_months"] = series["missing_spot_months"]
    controls["missing_funding_months"] = series["missing_funding_months"]
    return series, rows, controls


def main() -> None:
    if abs(COST - 0.0012) > 1e-15:
        raise RuntimeError(f"round trip cost is {COST}, expected 0.0012")
    root = Path(__file__).resolve().parents[2] / "data" / "history"
    package = Path(__file__).resolve().parents[2]
    _series, rows, controls = run_train(root)
    winner = keep_winner(rows)
    passed = gate_passes(winner)
    result = {
        "train": rows,
        "winner": winner,
        "gate_passed": passed,
        "train_controls": controls,
        "verdict": "STOPPED AT STEP 1 - holdout untouched",
    }
    reports = package / "reports"
    if not passed:
        write_report(result, reports / "cheap_futures_2026-11-13.md", reports / "cheap_futures_2026-11-13.json")
        print("STOPPED AT STEP 1", flush=True)
        return
    rules_path = package / "backtest" / "frozen_rules.json"
    ledger_path = package / "backtest" / "holdout_ledger.json"
    previous = rules_path.read_text() if rules_path.exists() else None
    rules_path.write_text(json.dumps(frozen_payload(winner), indent=2) + "\n")
    try:
        record = register_holdout(ledger_path, rules_path, HOLDOUT_START, HOLDOUT_END, ["BTCUSDT"])
    except HoldoutRefused as exc:
        if previous is not None:
            rules_path.write_text(previous)
        result["verdict"] = "HOLDOUT NOT LOADED - ledger refused an overlapping window"
        result["ledger_refused"] = str(exc)
        write_report(result, reports / "cheap_futures_2026-11-13.md", reports / "cheap_futures_2026-11-13.json")
        print(f"ledger refused: {exc}", flush=True)
        return
    print("holdout ledger written; loading 2024-12 warm-up and 2025-01 to 2026-10", flush=True)
    ensure_klines(root, "BTCUSDT", "futures", "2024-12", "2026-10")
    ensure_klines(root, "BTCUSDT", "spot", "2024-12", "2026-10")
    ensure_funding(root, "BTCUSDT", "2024-12", "2026-10")
    lo = _ms(HOLDOUT_WARMUP)
    hi = _exclusive_end(HOLDOUT_END)
    series = prepare_series(root, "2024-12", "2026-10", lo, hi, allow_2025=True)
    days = calendar_days(HOLDOUT_START, HOLDOUT_END)
    months = calendar_months(HOLDOUT_START, HOLDOUT_END)
    found = signals_for(series["gap_ts"], series["gap"])
    ran = run_variant(
        found[winner["percentile"]],
        winner["hold"],
        series["fut_ts"],
        series["fut_open"],
        series["spot_ts"],
        series["spot_open"],
        series["fund_ts"],
        series["fund_rate"],
        _ms(HOLDOUT_START),
        hi,
    )
    holdout = summarize_variant(winner["variant"], ran["trades"], days, months, Z)
    holdout["percentile"] = winner["percentile"]
    holdout["hold"] = winner["hold"]
    holdout["trade_rows"] = ran["trades"]
    holdout["decisions"] = ran["decisions"]
    cut = _ms("2026-10-30")
    holdout_controls = controls_for(series, holdout, _ms(HOLDOUT_START), hi, days, cut)
    flags = step3_flags(holdout, winner["net_mean"], holdout=True)
    verdict = step4_verdict(holdout, holdout_controls, flags)
    result.update(
        {
            "holdout": holdout,
            "holdout_controls": holdout_controls,
            "flags": flags,
            "verdict": verdict,
            "ledger": record,
            "funding_ignored_share": 0.0 if not series["missing_funding_months"] else 1.0,
        }
    )
    write_report(result, reports / "cheap_futures_2026-11-13.md", reports / "cheap_futures_2026-11-13.json")
    print(f"verdict {verdict}", flush=True)


if __name__ == "__main__":
    main()
