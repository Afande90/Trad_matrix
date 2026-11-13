"""Cheap-futures limit entry on the seen period. Three fee schedules, no holdout.

A buy limit sits at the signal minute's close. It fills only when a later
aggTrade prints at least one tick through that price, inside three minutes.
The exit is a market sell at the first 1m open at or after the fill plus the hold.
"""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import numpy as np

from src.backtest.cheap_futures import MINUTE_MS, _day, _month, funding_between
from src.backtest.loader import month_iter

TICK = 0.10
WINDOW_FILL_MS = 3 * MINUTE_MS
SPREAD = 0.0001
SLIPPAGE = 0.0001
FEES = {
    "F1": 0.0002 + 0.0005 + SPREAD + SLIPPAGE,
    "F2": 0.0000 + 0.0004 + SPREAD + SLIPPAGE,
    "F3": 0.0000 + 0.0002 + SPREAD + SLIPPAGE,
}
FEE_NOTE = {
    "F1": "limit 0.0002, market 0.0005, spread 0.0001, slippage 0.0001",
    "F2": "limit 0, market 0.0004, spread 0.0001, slippage 0.0001",
    "F3": "limit 0, market 0.0002, spread 0.0001, slippage 0.0001",
}


def minute_opens_live(ts: int) -> tuple[int, int]:
    """First and last minute opens whose post-close 3-minute window contains `ts`.

    The window is (close, close + 3 minutes]. The close itself is not inside it.
    Returns (first, last) inclusive, or (1, 0) when nothing is live.
    """
    if ts <= MINUTE_MS:
        return 1, 0
    last = ((ts - MINUTE_MS - 1) // MINUTE_MS) * MINUTE_MS
    raw = ts - 4 * MINUTE_MS
    if raw <= 0:
        first = 0
    elif raw % MINUTE_MS == 0:
        first = int(raw)
    else:
        first = int(raw + (MINUTE_MS - raw % MINUTE_MS))
    if first > last:
        return 1, 0
    return int(first), int(last)


def window_covers(minute_open: int, ts: int) -> bool:
    close = int(minute_open) + MINUTE_MS
    return close < int(ts) <= close + WINDOW_FILL_MS


def traded_through(price: float, limit: float, tick: float = TICK) -> bool:
    """A buy limit fills only when a print is at least one tick below the limit."""
    return float(price) <= float(limit) - float(tick)


def exit_open_ts(fill_ts: int, hold_ms: int) -> int:
    """First 1m open at or after the fill plus the hold."""
    target = int(fill_ts) + int(hold_ms)
    rem = target % MINUTE_MS
    if rem == 0:
        return target
    return target + (MINUTE_MS - rem)


def slot_closes(open_ts: np.ndarray, close_px: np.ndarray) -> tuple[int, np.ndarray]:
    """One close per minute. Missing minutes stay NaN. Slot 0 is the first minute."""
    if len(open_ts) == 0:
        return 0, np.zeros(0, dtype=float)
    base = int(open_ts[0] // MINUTE_MS)
    n = int(open_ts[-1] // MINUTE_MS) - base + 1
    close_at = np.full(n, np.nan)
    slots = (open_ts // MINUTE_MS - base).astype(np.int64)
    close_at[slots] = close_px
    return base, close_at


def slot_opens(open_ts: np.ndarray, open_px: np.ndarray, base: int, n: int) -> np.ndarray:
    opens = np.full(n, np.nan)
    slots = (open_ts // MINUTE_MS - base).astype(np.int64)
    keep = (slots >= 0) & (slots < n)
    opens[slots[keep]] = open_px[keep]
    return opens


def apply_trades_python(ts: np.ndarray, price: np.ndarray, base: int, close_at: np.ndarray, fill: np.ndarray, stop_ts: int | None = None) -> None:
    """Same fill rule as the scanner. Used by the tests and as the reference."""
    n = len(fill)
    for i in range(len(ts)):
        stamp = int(ts[i])
        if stop_ts is not None and stamp >= stop_ts:
            continue
        px = float(price[i])
        first, last_open = minute_opens_live(stamp)
        if first > last_open:
            continue
        slot = first // MINUTE_MS - base
        last_slot = last_open // MINUTE_MS - base
        while slot <= last_slot:
            if 0 <= slot < n and fill[slot] == 0:
                limit = float(close_at[slot])
                if limit == limit and traded_through(px, limit):
                    fill[slot] = stamp
            slot += 1


def scanner_binary() -> Path:
    root = Path(__file__).resolve().parent
    source = root / "scan_fills.c"
    binary = Path("/tmp/scan_fills")
    if not binary.exists() or binary.stat().st_mtime < source.stat().st_mtime:
        subprocess.run(["gcc", "-O3", "-o", str(binary), str(source)], check=True)
    return binary


def scan_limit_fills(paths: list[Path], open_ts: np.ndarray, close_px: np.ndarray, stop_ts: int | None = None) -> tuple[int, np.ndarray, np.ndarray]:
    """First aggTrade at least one tick through each minute's close, inside the next 3 minutes.

    `fill[slot] == 0` means that minute's limit was not filled. Slot 0 is `open_ts[0]`'s minute.
    """
    base, close_at = slot_closes(open_ts, close_px)
    fill = np.zeros(len(close_at), dtype=np.int64)
    if len(close_at) == 0:
        return base, fill, close_at
    binary = scanner_binary()
    close_path = Path("/tmp/scan_fills_close.bin")
    fill_in = Path("/tmp/scan_fills_in.bin")
    fill_out = Path("/tmp/scan_fills_out.bin")
    close_at.astype(np.float64).tofile(close_path)
    stop = 0 if stop_ts is None else int(stop_ts)
    for path in paths:
        print(f"  agg {path.name}", flush=True)
        fill.astype(np.int64).tofile(fill_in)
        with zipfile.ZipFile(path) as zf, fill_out.open("wb") as out, subprocess.Popen(
            [str(binary), str(base), str(len(fill)), str(close_path), str(fill_in), str(stop)],
            stdin=subprocess.PIPE,
            stdout=out,
        ) as proc:
            assert proc.stdin is not None
            try:
                with zf.open(zf.namelist()[0]) as fh:
                    while True:
                        chunk = fh.read(1 << 20)
                        if not chunk:
                            break
                        proc.stdin.write(chunk)
                proc.stdin.close()
            except BrokenPipeError:
                proc.stdin.close()
            code = proc.wait()
        if code != 0:
            raise RuntimeError(f"fill scanner failed on {path.name} with code {code}")
        fill = np.fromfile(fill_out, dtype=np.int64)
        print(f"    filled {int(np.sum(fill > 0))}", flush=True)
        if fill.shape[0] != close_at.shape[0]:
            raise RuntimeError("fill scanner wrote an unexpected length")
    return base, fill, close_at


def agg_paths(root: Path, start: str, end: str) -> list[Path]:
    folder = root / "aggTrades" / "BTCUSDT"
    paths = []
    for month in month_iter(start, end):
        if month >= "2025-01":
            raise RuntimeError("2025-01 onward is reserved and was not loaded")
        path = folder / f"BTCUSDT-aggTrades-{month}.zip"
        if not path.exists() or path.stat().st_size <= 0:
            raise FileNotFoundError(path)
        paths.append(path)
    return paths


def _price_at(base: int, opens: np.ndarray, ts: int) -> float | None:
    slot = int(ts // MINUTE_MS) - base
    if slot < 0 or slot >= len(opens):
        return None
    px = float(opens[slot])
    if px != px or px <= 0.0:
        return None
    return px


def walk_attempts(
    signal_open_ts: np.ndarray,
    base: int,
    close_at: np.ndarray,
    open_at: np.ndarray,
    fill: np.ndarray,
    fund_ts: np.ndarray,
    fund_rate: np.ndarray,
    hold_ms: int,
    eval_start: int,
    eval_end: int,
) -> list[dict]:
    """One working order at a time. An unfilled limit expires after 3 minutes."""
    next_free = 0
    rows = []
    n = len(fill)
    for open_ts in signal_open_ts.tolist():
        close_ts = int(open_ts) + MINUTE_MS
        if close_ts < next_free:
            continue
        minute_open = close_ts - MINUTE_MS
        slot = minute_open // MINUTE_MS - base
        if slot < 0 or slot >= n:
            continue
        limit = float(close_at[slot])
        if limit != limit or limit <= 0.0:
            continue
        filled_at = int(fill[slot])
        in_sample = eval_start <= close_ts < eval_end
        would_exit = close_ts + hold_ms
        would_px = _price_at(base, open_at, would_exit) if would_exit < eval_end else None
        would_gross = None if would_px is None else would_px / limit - 1.0
        if filled_at == 0:
            if in_sample:
                rows.append(
                    {
                        "close_ts": close_ts,
                        "status": "not_filled",
                        "fill_ts": None,
                        "exit_ts": None,
                        "limit": limit,
                        "gross": None,
                        "would_gross": would_gross,
                        "funding": 0.0,
                        "day": _day(close_ts),
                        "month": _month(close_ts),
                    }
                )
            next_free = close_ts + WINDOW_FILL_MS
            continue
        exit_ts = exit_open_ts(filled_at, hold_ms)
        gross = None
        funding = 0.0
        if in_sample and exit_ts < eval_end:
            px = _price_at(base, open_at, exit_ts)
            if px is not None:
                gross = px / limit - 1.0
                funding = float(funding_between(fund_ts, fund_rate, np.asarray([filled_at]), np.asarray([exit_ts]))[0])
        if in_sample:
            rows.append(
                {
                    "close_ts": close_ts,
                    "status": "filled" if gross is not None else "unscored",
                    "fill_ts": filled_at,
                    "exit_ts": exit_ts,
                    "limit": limit,
                    "gross": gross,
                    "would_gross": would_gross,
                    "funding": funding,
                    "day": _day(close_ts),
                    "month": _month(close_ts),
                }
            )
        next_free = exit_ts
    return rows


def fill_rates(rows: list[dict]) -> dict[str, float | None]:
    def rate(winners: bool) -> float | None:
        group = []
        for row in rows:
            gross = row["would_gross"]
            if gross is None:
                continue
            if winners and gross > 0:
                group.append(row)
            elif not winners and gross <= 0:
                group.append(row)
        if not group:
            return None
        return sum(1 for row in group if row["status"] == "filled") / len(group)

    return {"winners": rate(True), "losers": rate(False)}


def summarize_fee(rows: list[dict], fee: float, months: list[str]) -> dict:
    counted = [row for row in rows if row["status"] == "filled" and row["gross"] is not None]
    not_filled = sum(1 for row in rows if row["status"] == "not_filled")
    nets = []
    nets_x2 = []
    grosses = []
    by_month = {month: 0.0 for month in months}
    for row in counted:
        gross = float(row["gross"])
        funding = float(row["funding"])
        net = gross - fee - funding
        grosses.append(gross)
        nets.append(net)
        nets_x2.append(gross - 2.0 * fee - funding)
        by_month[row["month"]] = by_month.get(row["month"], 0.0) + net
    positive = sum(1 for month in months if by_month.get(month, 0.0) > 0)
    trades = len(counted)
    net_x2 = float(sum(nets_x2) / trades) if trades else None
    return {
        "trades": trades,
        "not_filled": not_filled,
        "fill_rate_winners": fill_rates(rows)["winners"],
        "fill_rate_losers": fill_rates(rows)["losers"],
        "gross_mean": float(sum(grosses) / trades) if trades else None,
        "net_mean": float(sum(nets) / trades) if trades else None,
        "net_mean_x2": net_x2,
        "positive_month_share": (positive / len(months)) if months else None,
        "worst_trade": min(nets) if nets else None,
        "clears": bool(net_x2 is not None and net_x2 > 0 and trades >= 100),
        "fee": fee,
        "unscored": sum(1 for row in rows if row["status"] == "unscored"),
    }


def month_fill_counts(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        if row["status"] == "filled" and row["gross"] is not None:
            counts[row["month"]] = counts.get(row["month"], 0) + 1
    return counts


def random_filled_orders(by_month: dict[str, list[tuple[int, int]]], counts: dict[str, int], seed: int) -> tuple[list[int], dict]:
    """Same number of filled orders per month, at random minutes, holds not overlapping.

    Each candidate is (order close time, exit time). A candidate is usable only
    when a limit at that minute's close did trade through.
    """
    import bisect

    rng = np.random.default_rng(seed)
    accepted: list[tuple[int, int]] = []
    chosen: list[int] = []
    short = {}
    for month in sorted(counts):
        need = int(counts[month])
        cands = list(by_month.get(month, []))
        rng.shuffle(cands)
        got = 0
        for close_ts, exit_ts in cands:
            if got >= need:
                break
            if _overlaps_order(accepted, close_ts, exit_ts):
                continue
            bisect.insort(accepted, (close_ts, exit_ts))
            chosen.append(int(close_ts))
            got += 1
        if got < need:
            short[month] = {"needed": need, "placed": got}
    return chosen, short


def _overlaps_order(accepted: list[tuple[int, int]], close_ts: int, exit_ts: int) -> bool:
    for start, end in accepted:
        if close_ts < end and start < exit_ts:
            return True
    return False
