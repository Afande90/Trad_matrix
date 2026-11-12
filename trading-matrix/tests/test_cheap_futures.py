"""Cheap futures: the rolling window, the fill, and the one-day cut."""

import numpy as np
import pytest

from src.backtest.cheap_futures import (
    COST,
    MINUTE_MS,
    Fenwick,
    _place_random,
    guard_months,
    position_entries,
    rolling_thresholds,
    score_entries,
)


def _minutes(n, start=1_700_000_000_000):
    return start + np.arange(n, dtype=np.int64) * MINUTE_MS


def test_threshold_uses_only_the_previous_window():
    tree = Fenwick(3)
    tree.add(1, 2)
    tree.add(3, 1)
    assert tree.kth(1) == 1
    assert tree.kth(2) == 1
    assert tree.kth(3) == 3

    ts = _minutes(80)
    values = np.linspace(0.0, 1.0, 80)
    window = 10 * MINUTE_MS
    got = rolling_thresholds(ts, values, window, (0.10, 0.50))
    assert np.isnan(got[:10]).all()
    for i in (10, 25, 79):
        window_values = values[i - 10 : i]
        expect = np.quantile(window_values, [0.10, 0.50], method="linear")
        assert got[i] == pytest.approx(expect)

    spiked = values.copy()
    spiked[-1] = 100.0
    full = rolling_thresholds(ts, spiked, window, (0.10,))
    cut = rolling_thresholds(ts[:-5], spiked[:-5], window, (0.10,))
    assert full[:-5] == pytest.approx(cut, nan_ok=True)
    # The current point is not part of its own threshold, so a very low print still qualifies.
    cheap = np.zeros(40)
    cheap[20] = -1.0
    marks = rolling_thresholds(ts[:40], cheap, window, (0.10,))
    assert marks[20, 0] == pytest.approx(0.0)
    assert cheap[20] < marks[20, 0]


def test_entry_is_the_next_open_and_one_position_does_not_overlap():
    assert COST == pytest.approx(0.0012)
    ts = _minutes(20)
    opens = np.concatenate([ts[:3], ts[4:]])
    entries, skipped = position_entries(np.asarray([ts[2], ts[3]]), 5 * MINUTE_MS, opens)
    assert skipped == 1
    assert entries == [(int(ts[3]), int(ts[4]), int(ts[9]))]

    every, skipped_every = position_entries(ts, 5 * MINUTE_MS, ts)
    assert skipped_every == 0
    assert [row[1] for row in every] == [int(ts[1] + 5 * MINUTE_MS * i) for i in range(4)]
    assert every[0][2] == every[1][1]

    fund_ts = np.asarray([int(ts[3])], dtype=np.int64)
    fund_rate = np.asarray([0.0002])
    fut_open = np.full(len(ts), 100.0)
    fut_open[6] = 101.0
    scored = score_entries(
        [(int(ts[0]), int(ts[1]), int(ts[6]))],
        ts,
        fut_open,
        ts,
        np.full(len(ts), 50.0),
        fund_ts,
        fund_rate,
        int(ts[0]),
        int(ts[10]),
    )
    assert len(scored) == 1
    assert scored[0]["gross"] == pytest.approx(0.01)
    assert scored[0]["funding"] == pytest.approx(0.0002)
    assert scored[0]["net"] == pytest.approx(0.01 - 0.0012 - 0.0002)
    assert scored[0]["net_x2"] == pytest.approx(0.01 - 0.0024 - 0.0002)


def test_random_long_can_place_the_same_count_without_overlapping():
    start = 1_700_000_000_000
    # Two days in January. One-hour holds. Ten trades fit easily.
    entries = [start + i * MINUTE_MS for i in range(2 * 24 * 60)]
    placed, short = _place_random({"2023-11": entries}, {"2023-11": 10}, 60 * MINUTE_MS, seed=3558)
    assert short == {}
    assert len(placed) == 10
    ordered = sorted(placed)
    assert all(b - a >= 60 * MINUTE_MS for a, b in zip(ordered, ordered[1:]))


def test_calls_do_not_change_when_one_later_day_is_added_and_2025_stays_closed():
    ts = _minutes(50)
    values = np.linspace(-0.01, 0.01, 50)
    window = 15 * MINUTE_MS
    early = rolling_thresholds(ts[:30], values[:30], window, (0.02, 0.10))
    later = rolling_thresholds(ts[:40], values[:40], window, (0.02, 0.10))
    assert early == pytest.approx(later[:30], nan_ok=True)
    with pytest.raises(RuntimeError):
        guard_months("2024-12", "2025-01", allow_2025=False)
