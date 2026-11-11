"""Run 2 backtest rules. Written before the implementation (TDD)."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import numpy as np
import pytest

from src.prediction.schemas import LensResult

RUN1 = Path("reports/backtest_2026-11-11.md")


def _minute(ts, o, h, l, c, volume=1.0):
    return {
        "symbol": "BTCUSDT",
        "timestamp": ts,
        "open": float(o),
        "high": float(h),
        "low": float(l),
        "close": float(c),
        "volume": volume,
        "source": "TEST",
    }


def _flat(n, start=0, price=100.0, step=60_000):
    out = []
    px = price
    for i in range(n):
        out.append(_minute(start + i * step, px, px * 1.001, px * 0.999, px))
    return out


def test_scalp_outcome_cost_and_round_trip_unchanged(monkeypatch):
    monkeypatch.setenv("FEE_FUT_MAKER", "0.0002")
    monkeypatch.setenv("FEE_FUT_TAKER", "0.0005")
    monkeypatch.setenv("SLIPPAGE_PCT", "0.0001")
    from config.costs import round_trip_cost, scalp_outcome_cost

    spread = 0.0001
    assert scalp_outcome_cost("WIN", "futures", spread) == pytest.approx(0.0002 + 0.0002 + spread + 0.0001)
    assert scalp_outcome_cost("LOSS", "futures", spread) == pytest.approx(0.0002 + 0.0005 + spread + 0.0001)
    assert scalp_outcome_cost("TIMEOUT", "futures", spread) == pytest.approx(0.0002 + 0.0005 + spread + 0.0001)
    assert round_trip_cost("CRYPTO", "futures", "taker", spread) == pytest.approx(0.0005 + 0.0005 + spread + 0.0001)
    assert round_trip_cost("CRYPTO", "futures", "maker", spread) == pytest.approx(0.0002 + 0.0002 + spread + 0.0001)


def test_trigger_either_does_not_change_default():
    from src.scalp.trigger import should_trigger

    s2 = LensResult("ensemble", "UP", 0.5, "", {})
    s5 = LensResult("orderflow", "UP", 0.5, "", {})
    assert should_trigger(6, "UP", s2, None, False) is False
    assert should_trigger(6, "UP", None, s5, False) is False
    assert should_trigger(6, "UP", s2, s5, False) is True
    assert should_trigger(6, "UP", s2, None, False, require="either") is True
    assert should_trigger(6, "UP", None, s5, False, require="either") is True
    assert should_trigger(6, "UP", s2, s5, True, require="either") is False
    assert should_trigger(4.4, "UP", s2, s5, False, require="either") is False
    down = LensResult("orderflow", "DOWN", 0.5, "", {})
    assert should_trigger(6, "UP", None, down, False, require="either") is False


def test_delta_only_silent_without_trades_and_no_quarter_gate():
    from src.scalp.orderflow import delta_only_lens, orderflow_lens

    assert delta_only_lens([]) is None
    assert delta_only_lens([(0.0, False)]) is None
    # Buy and sell equal: no direction.
    assert delta_only_lens([(1.0, False), (1.0, True)]) is None
    # Far below the old 0.25 book gate, and there is no book at all.
    slight = delta_only_lens([(1.0, False), (0.9, True)])
    assert slight is not None
    assert slight.direction == "UP"
    assert orderflow_lens([(1.0, False), (0.9, True)], 10.0, 10.0) is None
    heavy_sell = delta_only_lens([(1.0, True)])
    assert heavy_sell is not None and heavy_sell.direction == "DOWN"


def test_resample_drops_forming_bucket():
    from src.backtest.resample import closed_resampled

    bucket = 5 * 60_000
    start = 1_700_000_000_000
    start = start - (start % bucket)
    candles = []
    price = 100.0
    for i in range(7):
        o = price
        c = price + 1 + i
        candles.append(_minute(start + i * 60_000, o, max(o, c) + 0.5, min(o, c) - 0.5, c, volume=i + 1))
        price = c
    bars = closed_resampled(candles, bucket)
    assert len(bars) == 1
    assert bars[0]["timestamp"] == start
    assert bars[0]["open"] == pytest.approx(candles[0]["open"])
    assert bars[0]["close"] == pytest.approx(candles[4]["close"])
    assert bars[0]["high"] == pytest.approx(max(c["high"] for c in candles[:5]))
    assert bars[0]["low"] == pytest.approx(min(c["low"] for c in candles[:5]))
    # Missing the last minute of the bucket: still forming, dropped.
    assert closed_resampled(candles[:4], bucket) == []


def test_decision_cadence_one_hour_and_four_hour():
    from src.backtest.resample import is_decision_close

    hour = 3_600_000
    four = 4 * hour
    assert is_decision_close(hour - 60_000, hour) is True
    assert is_decision_close(hour, hour) is False
    assert is_decision_close(four - 60_000, four) is True
    assert is_decision_close(2 * hour - 60_000, four) is False
    assert is_decision_close(four - 60_000, hour) is True


def test_window_oracle_identity_and_breakeven():
    from src.backtest.oracle import window_oracle

    cost = 0.0012
    out = window_oracle([(100.0, 101.0), (100.0, 99.0), (50.0, 51.0)], cost)
    gross = (0.01 + 0.01 + 0.02) / 3
    assert out["gross"] == pytest.approx(gross)
    assert out["cost"] == pytest.approx(cost)
    assert out["net"] == pytest.approx(gross - cost)
    assert out["wiring_ok"] is True
    assert abs((out["gross"] - out["net"]) - out["cost"]) <= 1e-9
    assert out["breakeven_hit_rate"] == pytest.approx(0.5 + cost / (2 * gross))
    assert "funding" not in out or out.get("funding", 0) == 0


def test_ceiling_stop_as_built_does_not_run_strategy():
    from src.backtest.oracle import run_if_ceiling

    window = 5 * 60_000
    # Entry open is 100 and the window-end close is 100.05, so gross is 0.05%.
    # That is below the 0.2% cost, and the wiring identity still holds.
    candles = [_minute(i * 60_000, 100.0, 100.06, 99.99, 100.05) for i in range(40)]
    calls = {"n": 0}

    def strategy(_candles):
        calls["n"] += 1
        return [{"counted": True}]

    out = run_if_ceiling(candles, window, cost=0.002, strategy=strategy)
    assert out["oracle"]["gross"] > 0
    assert out["oracle"]["wiring_ok"] is True
    assert out["oracle"]["net"] <= 0
    assert out["ran"] is False
    assert calls["n"] == 0


def test_step4_oracle_precedes_too_early_and_rerun():
    from src.backtest.report_run2 import step4_run2

    early = {"counted": 0, "days_with_calls": 0, "oracle_net": -0.001, "gross_mean": None, "net_mean": None}
    assert step4_run2(early, True) == "STOP as built"
    assert step4_run2({**early, "oracle_net": 0.01}, True) == "TOO EARLY"
    proven = {
        "counted": 400,
        "days_with_calls": 80,
        "oracle_net": 0.01,
        "gross_mean": 0.02,
        "net_mean": 0.01,
        "net_lb": 0.001,
        "net_mean_x2": 0.001,
        "beats_baselines": True,
        "unexplained_flags": [],
        "profit_spread_over_months": True,
    }
    assert step4_run2(proven, False) == "RERUN"
    assert step4_run2({**proven, "gross_mean": -0.01, "net_mean": -0.02}, True) == "STOP this track"
    assert step4_run2({**proven, "net_mean": -0.001}, True) == "STOP as built"
    assert step4_run2({**proven, "net_lb": -0.001}, True) == "NOT PROVEN"


def test_headline_from_step4():
    from src.backtest.report_run2 import headline

    too_early = headline(["TOO EARLY"] * 6)
    assert "TOO EARLY" in too_early
    assert "Stop building" not in too_early
    rerun = headline(["RERUN"] * 6)
    assert "RERUN" in rerun
    assert "Stop building" not in rerun
    mixed_early = headline(["TOO EARLY", "RERUN"])
    assert "Stop building" not in mixed_early
    assert "TOO EARLY" in mixed_early and "RERUN" in mixed_early
    stopped = headline(["STOP as built"] * 4 + ["NOT PROVEN", "STOP this track"])
    assert stopped.startswith("Stop building trading features") or "Stop building trading features" in stopped.split(".")[0] or "Stop building trading features" in stopped
    assert "Stop building trading features" in stopped
    mix = headline(["STOP as built", "TOO EARLY", "NOT PROVEN"])
    assert "Stop building" not in mix
    assert "STOP as built" in mix and "TOO EARLY" in mix


def _sample_result(verdicts_ready=True):
    track = {
        "label": "T1 MOMENTUM 1h",
        "track": "T1_MOMENTUM_1H",
        "symbol": "BTCUSDT",
        "counted": 0,
        "days_with_calls": 0,
        "gross_mean": None,
        "net_mean": None,
        "net_lb": 0.0,
        "net_mean_x2": None,
        "net_mean_x3": None,
        "random_net": None,
        "baselines": {"ALWAYS_UP": 0.0, "ALWAYS_DOWN": 0.0, "PERSISTENCE": 0.0, "COIN": 0.5, "baseline_hit": 0.5},
        "hit_rate": None,
        "hit_lb": None,
        "oracle_gross": 0.004,
        "oracle_cost": 0.0012,
        "oracle_net": 0.0028,
        "breakeven_hit_rate": 0.5 + 0.0012 / (2 * 0.004),
        "oracle_wiring_ok": True,
        "ran": True,
        "holdout_dates": "2022-11-01 → 2024-11-01",
        "train_dates": "n/a",
        "validate_dates": "n/a",
        "wins": 0,
        "losses": 0,
        "timeouts": 0,
        "blocked": 0,
        "not_filled": 0,
        "same_candle_trades": 0,
        "same_candle_loss": 0,
        "maker_fill_winners": "n/a",
        "maker_fill_losers": "n/a",
        "max_dd_r": 0.0,
        "losing_streak": 0,
        "level": "Observer",
        "spread_assumed_share": 1.0,
        "funding_ignored_share": 0.0,
        "flags": [],
        "net_by_month": {},
        "validate_net_mean": None,
    }
    return {
        "K": 6,
        "rule_sets_tried": 2,
        "z": 3.09,
        "step1_ok": True,
        "step1": [{"check": "WINDOW ORACLE", "result": "wiring ok", "ok": True}],
        "tracks": [track],
        "seen_tracks": [{**track, "label": "T1 MOMENTUM 1h seen", "net_mean": 0.5, "counted": 9999, "oracle_net": 0.5}],
        "scope": ["AI and visual lenses are excluded."],
        "run1_text": RUN1.read_text() if RUN1.exists() else "",
    }


def test_zero_calls_print_na_not_zero():
    from src.backtest.report_run2 import render_run2

    text = render_run2(_sample_result())
    # The summary row is the line that starts with the track label.
    summary = [ln for ln in text.splitlines() if ln.startswith("T1 MOMENTUM 1h |")][0]
    cells = [c.strip() for c in summary.split("|")]
    # track | counted | days | K | gross | net | net_lb | x2 | RANDOM | verdict
    assert cells[6] == "n/a"
    body = text.split("## T1 MOMENTUM 1h")[1].split("## ")[0]
    assert "ALWAYS_UP=n/a" in body or "Baselines: n/a" in body
    assert "ALWAYS_UP=0.0000" not in body
    assert "net_lb on daily totals: n/a" in body


def test_report_order_decision_seen_and_retired():
    from src.backtest.report_run2 import render_run2

    text = render_run2(_sample_result())
    first = text.splitlines()[0]
    assert not first.startswith("#")
    assert "Stop building" not in first  # one track, oracle net > 0, zero calls → TOO EARLY
    assert "TOO EARLY" in first
    names = [
        "## CEILING",
        "## Step 1",
        "## One-line summary",
        "## T1 MOMENTUM 1h",
        "## Retired tracks",
        "## SEEN PERIOD - not evidence",
        "## Scope",
        "## DECISION",
    ]
    positions = [text.index(name) for name in names]
    assert positions == sorted(positions)
    assert "rule_sets_tried = 2" in text
    assert "K = 6" in text
    assert "3.09" in text
    assert "210160" in text
    assert "-0.000946" in text
    assert "4527" in text
    assert "9489" in text
    decision = text.split("## DECISION")[1]
    assert "live paper" in decision
    assert "Stop building trading features" in decision
    assert "measuring engine" in decision
    # A huge seen-period mean must not become a track verdict.
    verdict_lines = [ln for ln in decision.splitlines() if ln.startswith("- ")]
    assert verdict_lines
    assert all("CONTINUE" not in ln for ln in verdict_lines)
    seen = text.split("## SEEN PERIOD - not evidence")[1].split("## ")[0]
    assert "not evidence" in text.split("## SEEN PERIOD - not evidence")[0][-80:] or "SEEN PERIOD - not evidence" in text


def test_mix_headline_and_decision_diverge():
    from src.backtest.report_run2 import render_run2

    base = _sample_result()
    stopped = {
        **base["tracks"][0],
        "label": "T2 MOMENTUM 4h",
        "track": "T2_MOMENTUM_4H",
        "oracle_net": -0.001,
        "oracle_gross": 0.0004,
        "oracle_cost": 0.0012,
        "ran": False,
    }
    base["tracks"] = [base["tracks"][0], stopped]
    text = render_run2(base)
    assert "Stop building" not in text.splitlines()[0]
    decision = text.split("## DECISION")[1]
    assert "Stop building" not in text.splitlines()[0]
    assert "Stop building trading features" in decision
    assert "stop for good" in decision
    assert "live paper" in decision
    both_stopped = {
        **base,
        "tracks": [
            {**stopped, "label": "T1 MOMENTUM 1h"},
            {**stopped, "label": "T2 MOMENTUM 4h"},
        ],
    }
    stopped_text = render_run2(both_stopped)
    assert "Stop building trading features" in stopped_text.splitlines()[0]
    stopped_decision = stopped_text.split("## DECISION")[1]
    assert "Stop building trading features" in stopped_decision
    assert "measuring engine" in stopped_decision
    assert "Trader School" in stopped_decision


def test_freeze_rules_no_data_root(tmp_path):
    from src.backtest.run2 import freeze_run2_rules
    from src.verification.graduation import z_for_k

    assert "root" not in inspect.signature(freeze_run2_rules).parameters
    assert "data_root" not in inspect.signature(freeze_run2_rules).parameters
    src = inspect.getsource(freeze_run2_rules)
    assert "read_klines" not in src
    assert "ZipFile" not in src
    assert "iter_symbol" not in src
    payload = freeze_run2_rules(tmp_path / "frozen_rules.json", "0.10", "0.01")
    assert payload["rule_sets_tried"] == 2
    assert payload["K"] == 6
    assert payload["z"] == 3.09
    assert payload["z"] == z_for_k(6)
    assert z_for_k(12) != payload["z"]
    assert payload["btc_holdout_start"] == "2022-11-01"
    assert payload["btc_holdout_end"] == "2024-11-01"
    assert payload["tick_size"]["BTCUSDT"] == "0.10"
    assert payload["tick_size"]["XAUUSDT"] == "0.01"
    assert payload["scalp_trigger"] == "either"
    on_disk = json.loads((tmp_path / "frozen_rules.json").read_text())
    assert on_disk["rule_sets_tried"] == 2


def test_ledger_keeps_run1_and_accepts_new_window(tmp_path):
    from src.backtest.ledger import HoldoutRefused, register_holdout
    from src.backtest.run2 import freeze_run2_rules

    rules = tmp_path / "frozen_rules.json"
    freeze_run2_rules(rules, "0.10", "0.01")
    ledger = tmp_path / "holdout_ledger.json"
    ledger.write_text(
        json.dumps(
            {
                "runs": [
                    {
                        "rules_hash": "82f04eba306488055a814360a22969d04aeea971b640cae3126f511ffcacd432",
                        "holdout_start": "2026-06-08",
                        "holdout_end": "2026-11-01",
                        "symbols": ["BTCUSDT", "XAUUSDT"],
                        "written_at": "2026-11-11T15:07:42.997227+00:00",
                    }
                ]
            }
        )
    )
    register_holdout(ledger, rules, "2022-11-01", "2024-11-01", ["BTCUSDT", "XAUUSDT"])
    runs = json.loads(ledger.read_text())["runs"]
    assert len(runs) == 2
    assert runs[0]["rules_hash"].startswith("82f04eba")
    assert runs[1]["holdout_start"] == "2022-11-01"
    rules.write_text(json.dumps({"changed": True}))
    with pytest.raises(HoldoutRefused):
        register_holdout(ledger, rules, "2023-01-01", "2024-01-01", ["BTCUSDT"])


def test_single_voter_sideways_not_counted(monkeypatch):
    from src.backtest.trend_run2 import VoterReplay
    from src.prediction.schemas import LensResult as LR

    monkeypatch.setattr(
        "src.backtest.trend_run2.run_markov",
        lambda closes, window=20: LR("markov", "SIDEWAYS", 0.2, "", {}),
    )
    monkeypatch.setattr(
        "src.backtest.trend_run2.run_technical",
        lambda closes: LR("technical", "UP", 0.9, "", {}),
    )
    window = 5 * 60_000
    candles = []
    for i in range(30):
        px = 100 + i * 0.01
        candles.append(_minute(i * 60_000, px, px + 0.2, px - 0.2, px + 0.05))
    markov = VoterReplay(
        voter="markov", window_ms=window, bucket_ms=60_000, lookback=5, cost=0.0012, symbol="BTCUSDT", track="T1", label="T1"
    )
    tech = VoterReplay(
        voter="technical", window_ms=window, bucket_ms=60_000, lookback=5, cost=0.0012, symbol="BTCUSDT", track="T3", label="T3"
    )
    for candle in candles:
        markov.push(candle)
        tech.push(candle)
    assert markov.records
    assert all(r["prediction_direction"] == "SIDEWAYS" for r in markov.records)
    assert all(r["counts_for_graduation"] is False for r in markov.records)
    assert tech.records
    assert all(r["prediction_direction"] == "UP" for r in tech.records)
    assert any(r["counts_for_graduation"] for r in tech.records)


def test_entry_next_open_and_exit_at_window_end(monkeypatch):
    from src.backtest.trend_run2 import VoterReplay
    from src.prediction.schemas import LensResult as LR

    monkeypatch.setattr(
        "src.backtest.trend_run2.run_markov",
        lambda closes, window=20: LR("markov", "UP", 0.8, "", {}),
    )
    window = 5 * 60_000
    candles = []
    for i in range(20):
        # Signal close and next open are intentionally different.
        close = 100 + i
        nxt_open = close + 10
        candles.append(_minute(i * 60_000, nxt_open if i else 90, close + 1, close - 1, close))
    # Rebuild so candle i open equals previous close + 10, except we set opens explicitly.
    for i in range(1, len(candles)):
        candles[i]["open"] = candles[i - 1]["close"] + 10
        candles[i]["high"] = max(candles[i]["open"], candles[i]["close"]) + 1
        candles[i]["low"] = min(candles[i]["open"], candles[i]["close"]) - 1
    eng = VoterReplay(
        voter="markov", window_ms=window, bucket_ms=60_000, lookback=5, cost=0.0012, symbol="BTCUSDT", track="T1", label="T1"
    )
    for candle in candles:
        eng.push(candle)
    counted = [r for r in eng.records if r["counts_for_graduation"]]
    assert counted
    for record in counted:
        assert record["entry_time"] == record["signal_time"]
        assert record["price_at_prediction"] == pytest.approx(record["entry_open"])
        assert record["price_at_prediction"] != pytest.approx(record["signal_close"])
        assert record["verify_time"] == record["entry_time"] + window
        exit_open = record["verify_time"] - 60_000
        exit_candle = next(c for c in candles if c["timestamp"] == exit_open)
        assert record["price_at_verification"] == pytest.approx(exit_candle["close"])


def test_funding_in_track_net_not_in_oracle(monkeypatch):
    from src.backtest.oracle import window_oracle
    from src.backtest.trend_run2 import VoterReplay
    from src.prediction.schemas import LensResult as LR

    monkeypatch.setattr(
        "src.backtest.trend_run2.run_markov",
        lambda closes, window=20: LR("markov", "UP", 0.8, "", {}),
    )
    window = 5 * 60_000
    candles = []
    for i in range(16):
        close = 100.0
        candles.append(_minute(i * 60_000, 100.0, 101.0, 99.0, close))
    for i in range(1, len(candles)):
        candles[i]["open"] = 100.0
        candles[i]["close"] = 101.0
    # Make one window's move unambiguous: entry open 100, exit close 102.
    # First decision at open ts = 4 min (close at 5 min) once lookback is ready.
    eng = VoterReplay(
        voter="markov",
        window_ms=window,
        bucket_ms=60_000,
        lookback=5,
        cost=0.001,
        symbol="BTCUSDT",
        track="T1",
        label="T1",
        funding=[(5 * 60_000 + 60_000, 0.002)],
    )
    for candle in candles:
        eng.push(candle)
    counted = [r for r in eng.records if r["counts_for_graduation"]]
    assert counted
    record = counted[0]
    gross = record["gross_return_pct"]
    assert record["net_return_pct"] == pytest.approx(gross - record["cost_pct"] - 0.002)
    oracle = window_oracle([(record["price_at_prediction"], record["price_at_verification"])], record["cost_pct"])
    assert oracle["net"] == pytest.approx(oracle["gross"] - record["cost_pct"])
    assert oracle["net"] != pytest.approx(record["net_return_pct"])


def test_truncation_voter(monkeypatch):
    from src.backtest.trend_run2 import truncation_voter
    from src.prediction.schemas import LensResult as LR

    def voter(closes, window=20):
        direction = "UP" if closes[-1] >= closes[0] else "DOWN"
        return LR("markov", direction, 0.5, "", {})

    monkeypatch.setattr("src.backtest.trend_run2.run_markov", voter)
    rng = np.random.default_rng(0)
    price = 100.0
    candles = []
    for i in range(800):
        shock = float(rng.normal(0, 0.001))
        o = price
        c = price * (1 + shock)
        candles.append(_minute(i * 60_000, o, max(o, c) * 1.0001, min(o, c) * 0.9999, c))
        price = c
    assert truncation_voter(
        candles,
        voter="markov",
        window_ms=5 * 60_000,
        bucket_ms=60_000,
        lookback=8,
        cost=0.0012,
    )


def test_lens_sees_only_closed_resampled_bars(monkeypatch):
    from src.backtest.trend_run2 import VoterReplay
    from src.prediction.schemas import LensResult as LR

    seen = {}

    def voter(closes, window=20):
        seen["n"] = len(closes)
        seen["last"] = closes[-1]
        return LR("markov", "UP", 0.4, "", {})

    monkeypatch.setattr("src.backtest.trend_run2.run_markov", voter)
    bucket = 5 * 60_000
    start = 0
    candles = []
    for i in range(5 * 4 + 2):
        px = 100 + i
        candles.append(_minute(start + i * 60_000, px, px + 1, px - 1, px + 0.4))
    eng = VoterReplay(
        voter="markov", window_ms=bucket, bucket_ms=bucket, lookback=3, cost=0.001, symbol="BTCUSDT", track="T1", label="T1"
    )
    for candle in candles:
        eng.push(candle)
    assert seen["n"] == 3
    # The last decision uses the last closed 5m bucket, not the two still-forming minutes.
    assert seen["last"] == pytest.approx(candles[19]["close"])
    assert seen["last"] != pytest.approx(candles[21]["close"])


def test_maker_fill_not_filled_and_fill_rates():
    from src.backtest.scalp_run2 import ExtendedReplay, fill_rate_summary

    eng = ExtendedReplay(tick=0.1, spread_pct=0.0001, venue="futures", symbol="BTCUSDT", asset_class="CRYPTO", max_hold=6)
    # Would-be winner that does fill.
    eng.open_setup(direction="UP", price=100.0, reward_pct=0.01, risk_pct=0.01, signal_time=0, score=6.0)
    # Bar 1 trades through 100 - 0.1 and also tags the reward later.
    eng.on_candle(_minute(60_000, 100, 100.2, 99.8, 100), [(60_000, 99.8, 1.0, True)])
    eng.on_candle(_minute(120_000, 100, 101.5, 100, 101.2), [(120_000, 101.2, 1.0, False)])
    assert eng.records
    assert eng.records[0]["outcome"] == "WIN"
    assert eng.records[0]["counts_for_graduation"] is True
    assert eng.would_be[0]["would_be"] == "WIN" and eng.would_be[0]["filled"] is True

    # Would-be loser that never trades through.
    eng.open_setup(direction="UP", price=100.0, reward_pct=0.01, risk_pct=0.01, signal_time=180_000, score=6.0)
    for i, ts in enumerate((240_000, 300_000, 360_000)):
        eng.on_candle(_minute(ts, 100.2, 100.4, 100.05, 100.2), [(ts, 100.3, 1.0, False)])
    # Risk is 99. The path has not hit it yet. Push a bar through the stop.
    eng.on_candle(_minute(420_000, 100, 100.1, 98.0, 98.5), [(420_000, 98.5, 1.0, True)])
    assert any(r["outcome"] == "NOT_FILLED" for r in eng.records)
    assert all(r["counts_for_graduation"] is False for r in eng.records if r["outcome"] == "NOT_FILLED")
    rates = fill_rate_summary(eng.would_be)
    assert rates["winners"] == pytest.approx(1.0)
    assert rates["losers"] == pytest.approx(0.0)


def test_same_candle_missing_trades_is_loss():
    from src.backtest.scalp_run2 import ExtendedReplay

    eng = ExtendedReplay(tick=0.1, spread_pct=0.0001, venue="futures", symbol="BTCUSDT", asset_class="CRYPTO", max_hold=5)
    eng.open_setup(direction="UP", price=100.0, reward_pct=0.01, risk_pct=0.01, signal_time=0, score=6.0)
    # Through-fill and both bracket edges in the same candle, no trade path.
    eng.on_candle(_minute(60_000, 100, 102, 98, 100), [])
    # The fill window is three candles. The later two do not trade through.
    eng.on_candle(_minute(120_000, 100, 100.2, 99.9, 100), [])
    eng.on_candle(_minute(180_000, 100, 100.2, 99.9, 100), [])
    counted = [r for r in eng.records if r["counts_for_graduation"]]
    # Not filled, because no aggTrades went through. The would-be path is a loss.
    assert eng.would_be[0]["would_be"] == "LOSS"
    assert eng.would_be[0]["filled"] is False
    assert counted == []
    assert eng.same_candle_loss >= 1

    eng2 = ExtendedReplay(tick=0.1, spread_pct=0.0001, venue="futures", symbol="BTCUSDT", asset_class="CRYPTO", max_hold=5)
    eng2.open_setup(direction="UP", price=100.0, reward_pct=0.01, risk_pct=0.01, signal_time=0, score=7.0)
    # Trade through the bid first (fill), then the reward prints before the stop.
    trades = [(60_000, 99.8, 1.0, True), (60_100, 101.1, 1.0, False)]
    eng2.on_candle(_minute(60_000, 100, 102, 98, 101), trades)
    wins = [r for r in eng2.records if r["outcome"] == "WIN"]
    assert wins and wins[0]["counts_for_graduation"] is True
    assert eng2.same_candle_trades >= 1


def test_one_position_at_a_time_extended():
    from src.backtest.scalp_run2 import ExtendedReplay

    eng = ExtendedReplay(tick=0.1, spread_pct=0.0001, venue="futures", symbol="BTCUSDT", asset_class="CRYPTO", max_hold=5)
    assert eng.open_setup(direction="UP", price=100.0, reward_pct=0.05, risk_pct=0.05, signal_time=0, score=6.0) is True
    eng.on_candle(_minute(60_000, 100, 100.2, 99.5, 100), [(60_000, 99.5, 1.0, True)])
    # Still open (brackets are 5% away). A second setup is refused.
    assert eng.open_setup(direction="UP", price=100.0, reward_pct=0.05, risk_pct=0.05, signal_time=120_000, score=9.0) is False
    assert eng.triggered == 1


def test_gap_ratio_fails_step1_at_one_percent():
    from src.backtest.run2 import evaluate_step1

    random_ctrl = {"net_mean": -0.0012, "target": -0.0012, "se": 0.0001, "n": 100}
    oracles = [{"gross": 0.004, "net": 0.0028, "cost": 0.0012, "wiring_ok": True}]
    good = evaluate_step1(
        random_ctrl=random_ctrl,
        oracles=oracles,
        truncation_ok=True,
        entry_ok=True,
        cost_ok=True,
        ledger_ok=True,
        same_candle_reported=True,
        gap_ratio=0.009,
        rule_sets_tried=2,
        k=6,
        z=3.09,
    )
    assert good["step1_ok"] is True
    bad = evaluate_step1(
        random_ctrl=random_ctrl,
        oracles=oracles,
        truncation_ok=True,
        entry_ok=True,
        cost_ok=True,
        ledger_ok=True,
        same_candle_reported=True,
        gap_ratio=0.01,
        rule_sets_tried=2,
        k=6,
        z=3.09,
    )
    assert bad["step1_ok"] is False
    broken = evaluate_step1(
        random_ctrl={"net_mean": 0.01, "target": -0.0012, "se": 0.0001, "n": 100},
        oracles=oracles,
        truncation_ok=True,
        entry_ok=True,
        cost_ok=True,
        ledger_ok=True,
        same_candle_reported=True,
        gap_ratio=0.0,
        rule_sets_tried=2,
        k=6,
        z=3.09,
    )
    assert broken["step1_ok"] is False
    identity = evaluate_step1(
        random_ctrl=random_ctrl,
        oracles=[{"gross": 0.004, "net": 0.0, "cost": 0.0012, "wiring_ok": False}],
        truncation_ok=True,
        entry_ok=True,
        cost_ok=True,
        ledger_ok=True,
        same_candle_reported=True,
        gap_ratio=0.0,
        rule_sets_tried=2,
        k=6,
        z=3.09,
    )
    assert identity["step1_ok"] is False
    text = " ".join(row["result"] for row in good["step1"])
    assert "rule_sets_tried = 2" in text
    assert "K = 6" in text
    assert "3.09" in text


def test_random_control_still_loses_cost():
    from src.backtest.runner import random_control

    rng = np.random.default_rng(7)
    slots = []
    price = 100.0
    for _ in range(3000):
        nxt = price * (1 + float(rng.normal(0, 0.01)))
        slots.append({"entry": price, "entry_close": price, "verify": nxt, "cost": 0.0012})
        price = nxt
    ctrl = random_control(slots, n=1500, seed=7)
    assert abs(ctrl["net_mean"] - ctrl["target"]) <= 2 * ctrl["se"]


def test_new_modules_do_not_touch_the_database():
    import src.backtest.agg as agg
    import src.backtest.download as download
    import src.backtest.oracle as oracle
    import src.backtest.report_run2 as report_run2
    import src.backtest.resample as resample
    import src.backtest.run2 as run2
    import src.backtest.run2_cli as run2_cli
    import src.backtest.scalp_run2 as scalp_run2
    import src.backtest.trend_run2 as trend_run2

    text = "".join(
        inspect.getsource(m)
        for m in (agg, download, oracle, report_run2, resample, run2, run2_cli, scalp_run2, trend_run2)
    )
    assert "supabase" not in text.lower()
    assert "get_db" not in text


def test_agg_cursor_groups_one_minute(tmp_path):
    import zipfile

    from src.backtest.agg import AggCursor

    rows = [
        "agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker",
        "1,100.0,2.0,1,1,60000,true",
        "2,99.5,1.0,2,2,61000,false",
        "3,101.0,4.0,3,3,120000,false",
    ]
    path = tmp_path / "agg.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("BTCUSDT-aggTrades-test.csv", "\n".join(rows))
    cur = AggCursor(path)
    assert cur.peek_minute() == 60_000
    first = cur.consume(keep_prices=True)
    assert first["buy"] == pytest.approx(1.0)
    assert first["sell"] == pytest.approx(2.0)
    assert first["min"] == pytest.approx(99.5)
    assert first["max"] == pytest.approx(100.0)
    assert len(first["prices"]) == 2
    second = cur.consume(keep_prices=False)
    assert second["minute"] == 120_000
    assert second["prices"] == []
    assert second["buy"] == pytest.approx(4.0)
    assert cur.consume(keep_prices=False) is None
