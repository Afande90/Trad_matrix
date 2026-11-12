from datetime import datetime, timezone

import numpy as np
import pytest

from src.scalp.brackets import PositionBook, resolve_path
from src.scalp.ensemble import majority
from src.scalp.orderflow import delta_ratio, orderflow_lens
from src.scalp.profile import apply_profile_modifier, build_profile
from src.scalp.setup_scorer import raw_score_at, score_both
from src.scalp.trigger import scalp_confidence, should_trigger
from src.prediction.schemas import LensResult


def _rising(n=80):
    candles = []
    price = 100.0
    for i in range(n):
        price *= 1.002
        candles.append(
            {
                "timestamp": i * 60_000,
                "open": price * 0.999,
                "high": price * 1.002,
                "low": price * 0.998,
                "close": price,
                "volume": 10 + i,
            }
        )
    return candles


def test_setup_score_components():
    candles = _rising()
    prep_scores = score_both(candles)
    last = prep_scores[-1]
    assert last["side"] == "UP"
    assert last["buy"]["trend"] >= 1.5
    assert "momentum" in last["buy"]


def test_score_dead_market_zero():
    n = 30
    atr = np.concatenate([np.full(n - 1, 1.0), [0.1]])
    prep = {
        "close": np.linspace(100, 110, n),
        "high": np.linspace(101, 111, n),
        "low": np.linspace(99, 109, n),
        "open": np.linspace(100, 110, n),
        "ema_fast": np.linspace(100, 110, n),
        "ema_slow": np.linspace(99, 109, n),
        "rsi": np.full(n, 60.0),
        "atr": atr,
    }
    out = raw_score_at(prep, n - 1, "UP")
    assert out["dead"] is True
    assert out["score"] == 0.0
    assert out["trend"] == 0.0


def test_trigger_threshold():
    assert should_trigger(4.5, "UP", LensResult("ensemble", "UP", 0.5, "", {}), LensResult("orderflow", "UP", 0.5, "", {}), False) is True
    assert should_trigger(4.4, "UP", LensResult("ensemble", "UP", 0.5, "", {}), LensResult("orderflow", "UP", 0.5, "", {}), False) is False


def test_ensemble_majority():
    names = ["Strategy001", "Strategy003", "Strategy005", "Bandtastic", "Supertrend", "SwingHighToSky"]
    votes = {name: "UP" for name in names[:4]}
    votes["Supertrend"] = None
    votes["SwingHighToSky"] = None
    lens = majority(votes)
    assert lens.direction == "UP"
    assert lens.confidence == 4 / 6


def test_delta_ratio_sign():
    assert delta_ratio([(2.0, False), (1.0, True)]) > 0
    assert delta_ratio([(1.0, False), (3.0, True)]) < 0


def test_orderflow_silent_below_threshold():
    assert orderflow_lens([(1.0, False), (1.0, True)], 10, 9) is None


def test_trigger_requires_orderflow_or_ensemble():
    s2 = LensResult("ensemble", "UP", 0.5, "", {})
    s5 = LensResult("orderflow", "UP", 0.5, "", {})
    assert should_trigger(6, "UP", s2, None, False) is False
    assert should_trigger(6, "UP", None, s5, False) is False
    assert should_trigger(6, "UP", s2, s5, False) is True
    assert should_trigger(6, "UP", s2, s5, True) is False


def test_entropy_not_in_scalp_confidence():
    s2 = LensResult("ensemble", "UP", 0.4, "", {})
    # Score 8 → 0.8, ensemble 0.4, mean 0.6. Entropy is not an argument.
    assert scalp_confidence(8, s2, 1.0) == pytest.approx(0.6)


def test_quick_max_hold_15():
    candles = []
    for i in range(30):
        candles.append({"timestamp": i * 60_000, "open": 100, "high": 100.2, "low": 99.8, "close": 100})
    # Reward is far; a touch on bar 20 must not count for a 15-minute quick hold.
    candles[20]["high"] = 110
    out = resolve_path("UP", 100, 0.05, 0.02, candles, max_hold=15)
    assert out["outcome"] == "TIMEOUT"
    assert out["bars_held"] == 15


def test_extended_max_hold_60():
    candles = [{"timestamp": i * 60_000, "open": 100, "high": 100.1, "low": 99.9, "close": 100} for i in range(80)]
    candles[50]["high"] = 120
    out = resolve_path("UP", 100, 0.05, 0.02, candles, max_hold=60)
    assert out["outcome"] == "WIN"
    assert out["bars_held"] == 51


def test_timeout_counted_as_loss():
    candles = [{"timestamp": i * 60_000, "open": 100, "high": 100.1, "low": 99.9, "close": 100.05} for i in range(15)]
    out = resolve_path("UP", 100, 0.05, 0.02, candles, max_hold=15)
    assert out["outcome"] == "TIMEOUT"
    assert out["outcome"] != "WIN"


def test_checkpoints_recorded():
    candles = [{"timestamp": i * 60_000, "open": 100, "high": 100.2, "low": 99.8, "close": 100 + i * 0.01} for i in range(60)]
    out = resolve_path("UP", 100, 0.50, 0.40, candles, max_hold=60)
    assert "5" in out["checkpoints"]
    assert "15" in out["checkpoints"]
    assert "30" in out["checkpoints"]
    assert "60" in out["checkpoints"]


def test_mfe_mae_correct():
    candles = [
        {"timestamp": 0, "open": 100, "high": 101, "low": 99, "close": 100},
        {"timestamp": 60_000, "open": 100, "high": 103, "low": 98, "close": 102},
    ]
    out = resolve_path("UP", 100, 0.50, 0.40, candles, max_hold=2)
    assert out["mfe"] == 0.03
    assert out["mae"] == 0.02


def test_same_candle_resolved_or_loss():
    candle = {"timestamp": 5, "open": 100, "high": 110, "low": 90, "close": 100}
    missing = resolve_path("UP", 100, 0.05, 0.05, [candle], max_hold=5, trade_paths=None)
    assert missing["outcome"] == "LOSS"
    assert missing["resolved_by"] == "loss_no_trades"
    trades = [(1, 99), (2, 90), (3, 110)]
    # Risk is hit first in the tape.
    resolved = resolve_path("UP", 100, 0.05, 0.05, [candle], max_hold=5, trade_paths={5: trades})
    assert resolved["outcome"] == "LOSS"
    assert resolved["resolved_by"] == "aggTrades"
    reward_first = resolve_path("UP", 100, 0.05, 0.05, [candle], max_hold=5, trade_paths={5: [(1, 106), (2, 90)]})
    assert reward_first["outcome"] == "WIN"


def test_one_position_at_a_time():
    book = PositionBook()
    assert book.can_open("BTCUSDT", "QUICK", 0)
    book.open("BTCUSDT", "QUICK", 10)
    assert book.can_open("BTCUSDT", "QUICK", 5) is False
    assert book.can_open("BTCUSDT", "EXTENDED", 5) is True
    assert book.can_open("BTCUSDT", "QUICK", 11) is True


def test_profile_bins_adaptive():
    profile = build_profile([(100, 1), (100.2, 1), (101, 5)], atr=1.0)
    assert profile["bin_size"] == 0.1


def test_poc_is_max_volume():
    profile = build_profile([(100, 1), (101, 9), (102, 2)], atr=1.0)
    assert profile["poc"] == 101


def test_value_area_70pct():
    trades = [(100, 10), (101, 70), (102, 10), (103, 10)]
    profile = build_profile(trades, atr=10)
    covered = 0
    for price, qty in trades:
        key = round(price / profile["bin_size"]) * profile["bin_size"]
        if profile["val"] <= key <= profile["vah"]:
            covered += qty
    assert covered / 100 >= 0.70 - 1e-9


def test_target_blocked_modifier():
    profile = {"hvn": [105], "lvn": [], "poc": 100, "vah": 102, "val": 98, "bin_size": 1}
    mult, info = apply_profile_modifier("UP", 100, 110, profile)
    assert mult == 0.6
    assert info["target_blocked_by_hvn"] is True


def test_fast_zone_modifier():
    profile = {"hvn": [], "lvn": [112], "poc": 100, "vah": 102, "val": 98, "bin_size": 1}
    mult, info = apply_profile_modifier("UP", 103, 120, profile)
    assert mult == 1.15
    assert info["fast_zone"] is True


def test_s6_cannot_trigger_alone():
    assert should_trigger(8, "UP", None, None, False) is False


def test_weekend_tag_applied():
    from src.ingestion.market_hours import metal_weekend_tag

    saturday = int(datetime(2026, 11, 14, 12, tzinfo=timezone.utc).timestamp() * 1000)
    tuesday = int(datetime(2026, 11, 10, 12, tzinfo=timezone.utc).timestamp() * 1000)
    assert metal_weekend_tag("SCALP_METAL", saturday) == "METAL_WEEKEND"
    assert metal_weekend_tag("SCALP_METAL", tuesday) is None
    assert metal_weekend_tag("CRYPTO", saturday) is None


def test_metal_separate_tracks():
    assert "SCALP_METAL_QUICK" != "SCALP_QUICK"
    assert "SCALP_METAL_EXTENDED" != "SCALP_EXTENDED"
