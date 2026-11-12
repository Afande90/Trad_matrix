import json
from pathlib import Path

import numpy as np
import pytest

from src.backtest.ledger import HoldoutRefused, register_holdout
from src.backtest.loader import month_iter, to_ms
from src.backtest.replay import TrendReplay, candles_visible_at, replay_candles
from src.backtest.report import render_report, step4_verdict
from src.backtest.runner import frozen_rules, peek_control, random_control, truncation_identical, write_frozen
from src.verification.graduation import daily_net_lower_bound


def _aligned_start(start: int) -> int:
    """First open whose close lands on a 15-minute boundary (xx:14/29/44/59)."""
    close = start + 60_000
    rem = close % (15 * 60_000)
    if rem:
        close += 15 * 60_000 - rem
    return close - 60_000


def _series(n, start=1_700_000_000_000, drift=0.0, scale=0.002, seed=0, gap_at=None):
    rng = np.random.default_rng(seed)
    start = _aligned_start(start)
    price = 100.0
    candles = []
    ts = start
    for i in range(n):
        if gap_at is not None and i == gap_at:
            ts += 5 * 60_000
        shock = float(rng.normal(drift, scale))
        o = price
        c = price * (1 + shock)
        h = max(o, c) * (1 + abs(shock) * 0.2)
        l = min(o, c) * (1 - abs(shock) * 0.2)
        candles.append(
            {
                "symbol": "BTCUSDT",
                "timestamp": ts,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": 1.0,
                "source": "TEST",
            }
        )
        price = c
        ts += 60_000
    return candles


def _engine_kwargs():
    return dict(
        symbol="BTCUSDT",
        asset_class="CRYPTO",
        venue="spot",
        fee_mode="taker",
        spread_pct=0.0001,
        spread_assumed=True,
        track="CRYPTO",
        weight_every=5,
    )


def test_closed_candle_only():
    candles = _series(10)
    t = candles[4]["timestamp"] + 60_000
    visible = candles_visible_at(candles, t)
    assert all(c["timestamp"] + 60_000 <= t for c in visible)
    assert len(visible) == 5


def test_no_lookahead_lens_sees_only_past():
    base = _series(800, seed=1)
    alt = [dict(c) for c in base]
    for candle in alt[600:]:
        candle["close"] *= 3
        candle["open"] *= 3
        candle["high"] *= 3
        candle["low"] *= 3
    a = replay_candles(base, **_engine_kwargs())
    b = replay_candles(alt, **_engine_kwargs())
    t = base[600]["timestamp"]

    def directions(engine):
        return [(r["signal_time"], r["prediction_direction"]) for r in engine.records if r["signal_time"] < t]

    assert directions(a) == directions(b)


def test_truncation_identical_calls():
    candles = _series(2500, seed=2)
    assert truncation_identical(candles, _engine_kwargs())


def test_entry_at_next_open():
    candles = _series(400, seed=3)
    # Force the next open away from the previous close.
    for i in range(1, len(candles)):
        candles[i]["open"] = candles[i - 1]["close"] * 1.001
    engine = replay_candles(candles, **_engine_kwargs())
    counted = [r for r in engine.records if r["prediction_direction"] in ("UP", "DOWN", "SIDEWAYS", "ABSTAIN") and "price_at_prediction" in r]
    assert counted
    for record in counted:
        assert record["entry_time"] == record["signal_time"]
        assert record["price_at_prediction"] == pytest.approx(record["entry_open"])
        assert record["price_at_prediction"] != pytest.approx(record["signal_close"])


def test_split_is_time_ordered():
    from src.backtest.runner import split_bounds, which_split

    bounds = split_bounds("2024-11", "2026-10")
    assert bounds["train_end"] < bounds["valid_end"] < bounds["end"]
    train_ts = int(bounds["start"].timestamp() * 1000) + 1000
    hold_ts = int(bounds["valid_end"].timestamp() * 1000) + 1000
    assert which_split(train_ts, bounds) == "train"
    assert which_split(hold_ts, bounds) == "holdout"


def test_holdout_requires_frozen_rules(tmp_path):
    with pytest.raises(HoldoutRefused):
        register_holdout(tmp_path / "ledger.json", tmp_path / "missing.json", "2026-06-01", "2026-10-31", ["BTCUSDT"])


def test_holdout_ledger_refuses_second_run(tmp_path):
    rules = tmp_path / "frozen_rules.json"
    rules.write_text(json.dumps({"a": 1}))
    ledger = tmp_path / "ledger.json"
    register_holdout(ledger, rules, "2026-06-01", "2026-10-31", ["BTCUSDT"])
    rules.write_text(json.dumps({"a": 2}))
    with pytest.raises(HoldoutRefused):
        register_holdout(ledger, rules, "2026-07-01", "2026-10-31", ["BTCUSDT"])


def test_backtest_never_writes_supabase():
    import inspect

    import src.backtest.replay as replay
    import src.backtest.runner as runner

    text = inspect.getsource(replay) + inspect.getsource(runner)
    assert "supabase" not in text.lower()
    assert "get_db" not in text


def test_costs_match_live_cost_function():
    from config.costs import round_trip_cost

    engine = TrendReplay(**_engine_kwargs())
    assert engine.base_cost == pytest.approx(round_trip_cost("CRYPTO", "spot", "taker", 0.0001))


def test_report_has_plain_verdict_first():
    text = render_report(
        {
            "K": 5,
            "n_tracks": 5,
            "rule_sets_tried": 1,
            "z": 2.88,
            "step1_ok": True,
            "step1": [{"check": "RANDOM control", "result": "loses the cost"}],
            "peek_net": -0.001,
            "tracks": [
                {
                    "label": "BTC quick scalps",
                    "counted": 0,
                    "days_with_calls": 0,
                    "gross_mean": None,
                    "net_mean": None,
                    "net_lb": None,
                    "net_mean_x2": None,
                    "random_net": None,
                    "holdout_dates": "2026-06-07 → 2026-11-01",
                }
            ],
            "scope": ["AI/visual lenses excluded"],
        }
    )
    first = text.splitlines()[0]
    assert not first.startswith("#")
    assert "Stop building trading features" in first or "not judged" in first or "CONTINUE" in first


def test_streams_month_by_month():
    engine = TrendReplay(**_engine_kwargs())
    for _ in range(3):
        for candle in _series(500, seed=9):
            engine.push(candle)
        assert engine.retained <= 80


def test_spread_assumed_tag():
    engine = replay_candles(_series(400, seed=4), **_engine_kwargs())
    assert engine.records
    assert all(r["spread_assumed"] is True for r in engine.records)


def test_daily_clustered_lower_bound():
    spread = daily_net_lower_bound([1.0] * 10, 2.33)
    clustered = daily_net_lower_bound([10.0] + [0.0] * 9, 2.33)
    assert spread == pytest.approx(1.0)
    assert clustered < spread


def test_min_evidence_verdict_too_early():
    track = {"counted": 299, "days_with_calls": 80, "gross_mean": 0.01, "net_mean": 0.01, "net_lb": 0.01, "net_mean_x2": 0.01, "beats_baselines": True, "unexplained_flags": [], "profit_spread_over_months": True}
    assert step4_verdict(track, True) == "TOO EARLY"
    track["counted"] = 300
    track["days_with_calls"] = 59
    assert step4_verdict(track, True) == "TOO EARLY"


def test_step4_table():
    base = {"counted": 400, "days_with_calls": 80, "beats_baselines": True, "unexplained_flags": [], "profit_spread_over_months": True, "net_mean_x2": 0.01, "net_lb": 0.01}
    assert step4_verdict({**base, "gross_mean": -0.01, "net_mean": -0.02}, True) == "STOP this track"
    assert step4_verdict({**base, "gross_mean": 0.02, "net_mean": -0.001}, True) == "STOP as built"
    assert step4_verdict({**base, "gross_mean": 0.02, "net_mean": 0.01, "net_lb": -0.001}, True) == "NOT PROVEN"
    assert step4_verdict({**base, "gross_mean": 0.02, "net_mean": 0.01, "net_lb": 0.001, "net_mean_x2": -0.001}, True) == "NOT PROVEN"
    assert step4_verdict({**base, "gross_mean": 0.02, "net_mean": 0.01, "net_lb": 0.001}, True) == "CONTINUE"
    assert step4_verdict(base, False) == "RERUN"


def test_random_control_loses_cost():
    rng = np.random.default_rng(5)
    slots = []
    price = 100.0
    for i in range(4000):
        nxt = price * (1 + float(rng.normal(0, 0.01)))
        slots.append({"entry": price, "entry_close": price, "verify": nxt, "cost": 0.002})
        price = nxt
    ctrl = random_control(slots, n=2000, seed=5)
    assert abs(ctrl["net_mean"] - ctrl["target"]) <= 2 * ctrl["se"]


def test_peek_control_wins():
    # Each 15-minute block is a monotonic move larger than the cost, and the
    # first minute (the entry candle) points the same way.
    slots = []
    price = 100.0
    for i in range(200):
        direction = 1 if i % 2 == 0 else -1
        entry = price
        entry_close = price * (1 + direction * 0.01)
        verify = price * (1 + direction * 0.02)
        slots.append({"entry": entry, "entry_close": entry_close, "verify": verify, "cost": 0.002})
        price = verify
    ctrl = peek_control(slots)
    assert ctrl["hit_rate"] > 0.9
    assert ctrl["net_mean"] > 0.005


def test_weights_carry_into_holdout():
    candles = _series(1200, seed=6, drift=0.0004)
    engine = replay_candles(candles, **_engine_kwargs())
    assert engine.records
    midpoint = candles[len(candles) // 2]["timestamp"]
    before = [r for r in engine.records if r["signal_time"] < midpoint]
    after = [r for r in engine.records if r["signal_time"] >= midpoint]
    assert before and after
    # Decisions before the fifth verification still carry the opening book.
    # Nothing rebuilds the book when the clock crosses the midpoint.
    early = [r for r in engine.records if r["prediction_direction"] != "ABSTAIN"][:4]
    assert early
    assert all(r["weights"] == early[0]["weights"] for r in early)
    assert early[0]["weights"]["entropy"] == pytest.approx(0.25)
    assert after[0]["signal_time"] > before[-1]["signal_time"]


def test_to_ms_and_months():
    assert to_ms(1730419200000) == 1730419200000
    assert to_ms(1748736000000000) == 1748736000000
    months = list(month_iter("2024-11", "2025-01"))
    assert months == ["2024-11", "2024-12", "2025-01"]


def test_frozen_rules_round_trip(tmp_path):
    payload = frozen_rules("2024-11", "2026-10", ["BTCUSDT", "XAUUSDT"])
    path = tmp_path / "frozen_rules.json"
    write_frozen(path, payload)
    assert json.loads(path.read_text())["entry"] == "next candle open"
    assert payload["rule_sets_tried"] == 1
