"""A few checks for the limit fill and for holds that must not cross a close."""

import zipfile
from pathlib import Path

import numpy as np

from src.backtest.fee_limits import (
    apply_trades_python,
    exit_open_ts,
    minute_opens_live,
    scan_limit_fills,
    traded_through,
    walk_attempts,
    window_covers,
)
from src.backtest.other_markets import contiguous, hold_crosses_weekend


def _contains(ts: int, minute: int) -> bool:
    first, last = minute_opens_live(ts)
    return first <= minute <= last


def test_limit_fills_only_on_a_through_inside_three_minutes():
    minute = (1_700_000_000_000 // 60_000) * 60_000
    close = minute + 60_000
    assert not _contains(close, minute)
    assert not window_covers(minute, close)
    assert _contains(close + 1, minute)
    assert window_covers(minute, close + 180_000)
    assert _contains(close + 180_000, minute)
    assert not _contains(close + 180_001, minute)
    assert not window_covers(minute, close + 180_001)
    assert traded_through(99.90, 100.0, 0.10)
    assert not traded_through(99.91, 100.0, 0.10)

    base = minute // 60_000
    close_at = np.full(4, np.nan)
    close_at[0] = 100.0
    fill = np.zeros(4, dtype=np.int64)
    apply_trades_python(
        np.asarray([close, close + 1_000, close + 180_000], dtype=np.int64),
        np.asarray([99.80, 99.95, 99.90], dtype=float),
        base,
        close_at,
        fill,
    )
    # The print at the close is ignored. The next print does not go through.
    # The print at the end of the third minute does.
    assert int(fill[0]) == close + 180_000


def test_one_position_and_the_exit_open():
    start = (1_700_000_000_000 // 60_000) * 60_000
    n = 40
    base = start // 60_000
    opens = np.full(n, 100.0)
    closes = np.full(n, 100.0)
    fill = np.zeros(n, dtype=np.int64)
    fill[0] = start + 60_000 + 1_000
    hold = 5 * 60_000
    empty = np.zeros(0, dtype=np.int64)
    rows = walk_attempts(
        np.asarray([start, start + 60_000]),
        base,
        closes,
        opens,
        fill,
        empty,
        np.zeros(0, dtype=float),
        hold,
        start,
        start + n * 60_000,
    )
    assert len(rows) == 1
    assert rows[0]["status"] == "filled"
    assert rows[0]["exit_ts"] == exit_open_ts(fill[0], hold)
    assert rows[0]["gross"] == 0.0
    # The second signal arrives while the first position is still open.
    assert rows[0]["exit_ts"] > start + 2 * 60_000

    unfilled = np.zeros(n, dtype=np.int64)
    skipped = walk_attempts(
        np.asarray([start, start + 60_000]),
        base,
        closes,
        opens,
        unfilled,
        empty,
        np.zeros(0, dtype=float),
        hold,
        start,
        start + n * 60_000,
    )
    assert len(skipped) == 1
    assert skipped[0]["status"] == "not_filled"


def test_a_hold_across_a_gap_or_the_weekend_is_dropped():
    friday = 1_669_334_400_000  # 2022-11-25 00:00 UTC, a Friday
    assert friday == (friday // 60_000) * 60_000
    assert not hold_crosses_weekend(friday + 20 * 60 * 60_000, friday + 21 * 60 * 60_000)
    assert hold_crosses_weekend(friday + 21 * 60 * 60_000, friday + 23 * 60 * 60_000)
    present = np.ones(10, dtype=np.int8)
    present[4] = 0
    base = friday // 60_000
    assert contiguous(present, base, friday, friday + 3 * 60_000)
    assert not contiguous(present, base, friday, friday + 6 * 60_000)


def test_scanner_matches_the_python_rule(tmp_path: Path):
    minute = (1_700_000_000_000 // 60_000) * 60_000
    close = minute + 60_000
    lines = [
        f"1,99.80,1,1,1,{close},true",
        f"2,99.95,1,1,1,{close + 1000},true",
        f"3,99.90,1,1,1,{close + 180000},true",
        f"4,99.00,1,1,1,{close + 180001},true",
    ]
    path = tmp_path / "BTCUSDT-aggTrades-2020-11.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("trades.csv", "\n".join(lines) + "\n")
    opens = np.asarray([minute], dtype=np.int64)
    prices = np.asarray([100.0], dtype=float)
    _base, fill, _close = scan_limit_fills([path], opens, prices)
    assert int(fill[0]) == close + 180_000
