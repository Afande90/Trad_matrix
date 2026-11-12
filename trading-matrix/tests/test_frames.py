"""Frame check: bar builder and the quarter-hour window. No strategy."""

from src.backtest.frames import QUARTER_MS, accumulate_boundary_windows, build_volume_bars


def _candle(ts, open_, high, low, close, volume):
    return {
        "timestamp": ts,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def test_volume_bars_close_only_after_the_amount_is_reached():
    start = 1_600_000_000_000
    candles = [
        _candle(start, 10, 12, 9, 11, 2),
        _candle(start + 60_000, 11, 14, 8, 13, 2),
        _candle(start + 120_000, 13, 15, 7, 12, 2),
        _candle(start + 180_000, 12, 12, 11, 11.5, 1),
    ]
    bars = build_volume_bars(candles, 5)
    assert len(bars) == 1
    bar = bars[0]
    assert bar["timestamp"] == start
    assert bar["open"] == 10
    assert bar["high"] == 15
    assert bar["low"] == 7
    assert bar["close"] == 12
    assert bar["volume"] == 6
    assert bar["minutes"] == 3
    assert bar["close_time"] == start + 180_000
    # The last minute has not reached another full bar, so it is not usable.
    assert build_volume_bars(candles[:2], 5) == []
    exact = build_volume_bars(
        [_candle(start, 1, 2, 1, 2, 5), _candle(start + 60_000, 2, 3, 1, 2.5, 4)],
        5,
    )
    assert len(exact) == 1
    assert exact[0]["minutes"] == 1
    assert exact[0]["close"] == 2


def test_boundary_window_keeps_only_the_first_ten_seconds():
    boundary = 1_600_000_000_000 - (1_600_000_000_000 % QUARTER_MS)
    trades = [
        (boundary - 1, 9.0, False),
        (boundary + 1_000, 3.0, False),
        (boundary + 9_000, 1.0, True),
        (boundary + 10_000, 100.0, False),
        (boundary + 60_000, 50.0, False),
        (boundary + QUARTER_MS + 2_000, 4.0, True),
        (boundary + QUARTER_MS + 5 * 60_000, 8.0, False),
    ]
    rows = accumulate_boundary_windows(trades)
    assert [row["boundary"] for row in rows] == [boundary, boundary + QUARTER_MS]
    assert rows[0]["buy"] == 3.0
    assert rows[0]["sell"] == 1.0
    assert rows[0]["share"] == 0.75
    assert rows[1]["buy"] == 0.0
    assert rows[1]["sell"] == 4.0
    assert rows[1]["share"] == 0.0
