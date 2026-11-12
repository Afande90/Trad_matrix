"""Run 3: the complete-sentence scalp rule. Tests written before the run."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from src.scalp.profile import build_profile


def test_governor_is_empty_unless_both_conditions_hold():
    from src.backtest.sentence import governor

    assert governor(12.0, 10.0, 11.0) == "UP"
    assert governor(8.0, 10.0, 9.0) == "DOWN"
    assert governor(12.0, 10.0, 10.0) is None
    assert governor(10.0, 10.0, 12.0) is None
    assert governor(None, 10.0, 12.0) is None


def test_doer_share_thresholds_and_silence():
    from src.backtest.sentence import doer

    assert doer(60.0, 40.0) == "BUYERS"
    assert doer(40.0, 60.0) == "SELLERS"
    assert doer(59.0, 41.0) is None
    assert doer(41.0, 59.0) is None
    assert doer(0.0, 0.0) is None


def test_target_uses_previous_day_levels_and_profile_poc():
    from src.backtest.sentence import day_poc, target_near

    trades = [(100.0, 1.0), (105.0, 9.0), (110.0, 1.0)]
    poc = day_poc(trades, atr=10.0)
    assert poc == build_profile(trades, 10.0)["poc"]
    assert target_near(105.0, 4.0, [90.0, poc, 130.0]) is True
    assert target_near(100.0, 4.0, [101.0]) is True
    assert target_near(100.0, 4.0, [101.1]) is False
    assert target_near(100.0, 4.0, []) is False
    assert day_poc([], 10.0) is None


def test_exception_empties_only_above_three_atr_and_state_needs_both_filters():
    from src.backtest.sentence import exception_veto, state_passes

    assert exception_veto(3.1, 1.0) is True
    assert exception_veto(3.0, 1.0) is False
    assert exception_veto(1.0, None) is True
    assert state_passes(gate_blocked=False, dead=False) is True
    assert state_passes(gate_blocked=True, dead=False) is False
    assert state_passes(gate_blocked=False, dead=True) is False


def test_one_empty_role_is_no_trade_and_variants_use_the_doer():
    from src.backtest.sentence import trade_side

    full = {
        "governor": "UP",
        "doer": "BUYERS",
        "target": True,
        "state": True,
        "wide": False,
    }
    assert trade_side(full, "WITH") == "UP"
    assert trade_side(full, "AGAINST") is None
    faded = {**full, "doer": "SELLERS"}
    assert trade_side(faded, "AGAINST") == "DOWN"
    assert trade_side(faded, "WITH") is None
    for key, empty in (
        ("governor", None),
        ("doer", None),
        ("target", False),
        ("state", False),
        ("wide", True),
    ):
        broken = {**full, key: empty}
        assert trade_side(broken, "WITH") is None

    off_governor = trade_side(full, "WITH", disabled={1})
    assert off_governor == "UP"
    off_governor_fade = trade_side({**full, "governor": None, "doer": "SELLERS"}, "AGAINST", disabled={1})
    assert off_governor_fade == "DOWN"
    assert trade_side({**full, "doer": None}, "WITH", disabled={2}) == "UP"
    assert trade_side({**full, "doer": None}, "AGAINST", disabled={2}) == "DOWN"
    assert trade_side({**full, "target": False}, "WITH", disabled={3}) == "UP"
    assert trade_side({**full, "wide": True}, "WITH", disabled={5}) == "UP"


def test_variant_is_chosen_on_train_net_mean_only():
    from src.backtest.sentence import choose_variant

    assert choose_variant({"counted": 400, "net_mean": -0.001}, {"counted": 400, "net_mean": -0.0002}) == "AGAINST"
    assert choose_variant({"counted": 400, "net_mean": 0.001}, {"counted": 400, "net_mean": 0.0002}) == "WITH"
    assert choose_variant({"counted": 10, "net_mean": -0.01}, {"counted": 20, "net_mean": 0.05}) == "WITH"
    assert choose_variant({"counted": 0, "net_mean": None}, {"counted": 0, "net_mean": None}) == "WITH"
    assert choose_variant({"counted": 400, "net_mean": -0.002}, {"counted": 10, "net_mean": None}) == "WITH"
    assert choose_variant({"counted": 400, "net_mean": -0.002}, {"counted": 500, "net_mean": -0.002}) == "WITH"


def test_freeze_writes_rule_set_three_and_does_not_read_history(tmp_path):
    from src.backtest.run3 import freeze_run3

    src = inspect.getsource(freeze_run3)
    assert "read_klines" not in src
    assert "ZipFile" not in src
    assert "aggTrades" not in src
    path = tmp_path / "frozen_rules.json"
    payload = freeze_run3(
        path,
        "WITH",
        {"WITH": {"counted": 10, "net_mean": -0.001}, "AGAINST": {"counted": 12, "net_mean": -0.002}},
    )
    assert payload["rule_sets_tried"] == 3
    assert payload["K"] == 2
    assert payload["z"] == 2.88
    assert payload["variant"] == "WITH"
    assert payload["holdout_start"] == "2020-11-01"
    assert payload["holdout_end"] == "2022-10-31"
    assert payload["train_start"] == "2022-11-01"
    assert payload["train_end"] == "2024-10-31"
    assert "news calendar" in payload["exception"].lower() or payload.get("news_calendar") is False
    saved = json.loads(path.read_text())
    assert saved["rule_sets_tried"] == 3


def test_ledger_keeps_earlier_runs(tmp_path):
    from src.backtest.ledger import register_holdout
    from src.backtest.run3 import freeze_run3

    rules = tmp_path / "frozen_rules.json"
    ledger = tmp_path / "holdout_ledger.json"
    ledger.write_text(
        json.dumps(
            {
                "runs": [
                    {"rules_hash": "a" * 64, "holdout_start": "2026-06-08", "holdout_end": "2026-11-01", "symbols": ["BTCUSDT"]},
                    {"rules_hash": "b" * 64, "holdout_start": "2022-11-01", "holdout_end": "2024-11-01", "symbols": ["BTCUSDT"]},
                ]
            }
        )
    )
    freeze_run3(rules, "WITH", {"WITH": {"counted": 1, "net_mean": 0.0}, "AGAINST": {"counted": 1, "net_mean": -0.1}})
    register_holdout(ledger, rules, "2020-11-01", "2022-10-31", ["BTCUSDT"])
    runs = json.loads(ledger.read_text())["runs"]
    assert len(runs) == 3
    assert runs[0]["holdout_start"] == "2026-06-08"
    assert runs[1]["holdout_start"] == "2022-11-01"
    assert runs[2]["holdout_start"] == "2020-11-01"


def test_execute_registers_the_ledger_before_the_holdout_scan():
    from src.backtest.run3 import execute

    src = inspect.getsource(execute)
    assert src.index("register_holdout") < src.index("scan_holdout")


def _sentence_candles(n_extra: int, buy: float, sell: float):
    """Day one climbs. Day two sits on day one's high so the target role can fill."""
    start = 1_606_780_800_000  # 2020-12-01 00:00:00 UTC
    candles = []
    flows = []
    day_high = None
    for i in range(1440 + n_extra):
        ts = start + i * 60_000
        if i < 1440:
            close = 100.0 + i * 0.01
            high = close * 1.005
            low = close * 0.995
            day_high = high if day_high is None else max(day_high, high)
        else:
            close = day_high
            high = close * 1.005
            low = close * 0.995
        candles.append({"timestamp": ts, "open": close, "high": high, "low": low, "close": close})
        flows.append((buy, sell, [(close, 1.0)]))
    return candles, flows


def test_sentence_book_trades_only_when_every_role_is_filled():
    from src.backtest.sentence import SentenceBook

    candles, flows = _sentence_candles(180, 7.0, 3.0)
    book = SentenceBook()
    signals = []
    for candle, (buy, sell, trades) in zip(candles, flows):
        roles = book.push(candle, buy, sell, trades)
        if roles["side_with"]:
            signals.append((candle["timestamp"], roles["side_with"]))
    assert signals, "a complete WITH sentence should appear once the previous day and the EMAs exist"
    assert all(side == "UP" for _, side in signals)
    quiet_candles, quiet_flows = _sentence_candles(180, 5.0, 5.0)
    quiet = SentenceBook()
    quiet_signals = []
    for candle, (buy, sell, trades) in zip(quiet_candles, quiet_flows):
        roles = quiet.push(candle, buy, sell, trades)
        if roles["side_with"]:
            quiet_signals.append(candle["timestamp"])
    assert quiet_signals == []


def test_truncation_ignores_candles_after_the_cut():
    from src.backtest.sentence import sentence_signals

    candles, flows = _sentence_candles(400, 7.0, 3.0)
    cut = 1440 + 200
    full = sentence_signals(candles, flows, "WITH")
    short = sentence_signals(candles[:cut], flows[:cut], "WITH")
    limit = candles[cut - 1]["timestamp"] + 60_000
    assert short
    assert [row for row in full if row[0] <= limit] == short


def test_trend_drawdown_is_cumulative_net_and_scalp_baseline_is_breakeven():
    from src.backtest.report_run2 import drawdown_line, baseline_line

    trend = {"kind": "trend", "counted": 10, "max_dd_net": 0.123456, "losing_streak": 4, "max_dd_r": 99.0}
    text = drawdown_line(trend)
    assert "cumulative net" in text
    assert "12.3456%" in text
    assert "in R" not in text
    scalp = {
        "kind": "scalp",
        "counted": 10,
        "breakeven_wr_mean": 0.42,
        "baselines": {"ALWAYS_UP": 0.9, "ALWAYS_DOWN": 0.1, "PERSISTENCE": 0.2, "COIN": 0.5, "baseline_hit": 0.9},
        "max_dd_r": 3.5,
        "losing_streak": 2,
    }
    base = baseline_line(scalp)
    assert "break-even win rate=0.4200" in base
    assert "ALWAYS_UP=n/a" in base
    assert "0.9000" not in base
    assert "in R" in drawdown_line(scalp)


def test_run3_report_order_and_diagnostic_does_not_change_the_verdict():
    from src.backtest.report_run3 import render_run3

    track = {
        "label": "BTC COMPLETE SENTENCE",
        "kind": "scalp",
        "symbol": "BTCUSDT",
        "counted": 40,
        "days_with_calls": 10,
        "gross_mean": 0.001,
        "net_mean": -0.0004,
        "net_lb": -0.001,
        "net_mean_x2": -0.001,
        "net_mean_x3": -0.002,
        "random_net": -0.0009,
        "breakeven_wr_mean": 0.41,
        "hit_rate": 0.4,
        "hit_lb": 0.2,
        "oracle_gross": 0.004,
        "oracle_cost": 0.0009,
        "oracle_net": 0.0031,
        "breakeven_hit_rate": 0.6,
        "wins": 16,
        "losses": 20,
        "timeouts": 4,
        "blocked": 100,
        "not_filled": 3,
        "maker_fill_winners": "0.900",
        "maker_fill_losers": "0.950",
        "same_candle_trades": 1,
        "same_candle_loss": 0,
        "max_dd_r": 2.0,
        "losing_streak": 3,
        "level": "Observer",
        "spread_assumed_share": 1.0,
        "funding_ignored_share": 0.0,
        "net_by_month": {"2021-01": -0.01},
        "flags": [],
        "holdout_dates": "2020-11-01 → 2022-10-31",
    }
    text = render_run3(
        {
            "K": 2,
            "z": 2.88,
            "rule_sets_tried": 3,
            "step1_ok": True,
            "step1": [{"check": "WINDOW ORACLE", "result": "wiring ok"}],
            "kept": "WITH",
            "keep_reason": "both train variants had fewer than 300 calls",
            "train": {
                "WITH": {"counted": 12, "days_with_calls": 4, "gross_mean": 0.001, "net_mean": -0.0002},
                "AGAINST": {"counted": 9, "days_with_calls": 3, "gross_mean": -0.001, "net_mean": -0.001},
            },
            "track": track,
            "diagnostic": [
                {"role": "governor", "counted": 5000, "net_mean": 0.01},
                {"role": "doer", "counted": 10, "net_mean": -0.001},
                {"role": "target", "counted": 10, "net_mean": -0.001},
                {"role": "exception", "counted": 10, "net_mean": -0.001},
            ],
            "scope": ["No news calendar is bundled."],
        }
    )
    names = [
        "## CEILING",
        "## Step 1",
        "## TRAIN",
        "## HOLDOUT",
        "## Scope",
        "## DIAGNOSTIC - not evidence",
        "## DECISION",
    ]
    positions = [text.index(name) for name in names]
    assert positions == sorted(positions)
    assert text.splitlines()[0].startswith("TOO EARLY") or "TOO EARLY" in text.splitlines()[0]
    assert "Stop building" not in text.splitlines()[0]
    decision = text.split("## DECISION")[1]
    assert "TOO EARLY" in decision
    assert "0.01" not in decision
    assert "only test of this rule" in decision
    assert "Wait for the operator" in decision
    assert "No news calendar" in text
