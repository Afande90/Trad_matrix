import logging

import numpy as np
import pytest

from config.costs import round_trip_cost, warn_if_metal_fee_unconfirmed
from src.prediction.consensus import build_consensus
from src.prediction.schemas import LensResult
from src.prediction.trust_gate import (
    HourlyCounters,
    TrustTracker,
    benford_mad,
    fail_exclusion_allowed,
    first_digit,
    hill_exponent,
    mad_band,
    market_trust,
    round_cluster_ratio,
)
from src.scalp.brackets import resolve_path
from src.scalp.cost_gate import evaluate_cost_gate, maker_filled
from src.scalp.ensemble import majority
from src.scalp.orderflow import delta_ratio, orderflow_lens
from src.scalp.profile import apply_profile_modifier, build_profile
from src.scalp.setup_scorer import score_both
from src.scalp.trigger import should_trigger
from src.verification.graduation import (
    RuleLog,
    baselines_from_moves,
    evaluate_learner_ladder,
    evaluate_level,
    wilson_lower,
    z_for_k,
)
from src.verification.lens_weights import WeightBook, recompute_directional_weights
from src.verification.stats_engine import empty_stats, record_verification
from src.verification.verifier import (
    counts_for_graduation,
    expectancy_net,
    scalp_net,
    verify_prediction,
)


def _benford_sizes(n, rng):
    # Significand uniform in log space → Benford first digits.
    sig = 10 ** rng.random(n)
    magnitude = 10 ** rng.integers(0, 4, n)
    return (sig * magnitude).tolist()


def test_benford_on_trade_sizes():
    rng = np.random.default_rng(0)
    out = benford_mad(_benford_sizes(20000, rng))
    assert out["band"] == "PASS"
    assert out["n"] == 20000


def test_mad_bands():
    assert mad_band(0.005) == "PASS"
    assert mad_band(0.012) == "PASS"
    assert mad_band(0.013) == "WEAK"
    assert mad_band(0.015) == "WEAK"
    assert mad_band(0.02) == "FAIL"


def test_large_n_does_not_force_fail():
    rng = np.random.default_rng(1)
    sizes = _benford_sizes(100000, rng)
    out = benford_mad(sizes)
    # Pearson chi-square on counts is large simply because n is large only when
    # the proportions are off. A Benford sample stays inside the MAD pass band.
    assert out["band"] == "PASS"
    assert out["chi2_counts"] is not None


def test_round_clustering_detects_fake():
    rng = np.random.default_rng(2)
    uniform = rng.uniform(0.05, 12, 5000).tolist()
    clustered = [1.0] * 4000 + [0.93, 1.07] * 200
    fake = round_cluster_ratio(uniform)
    real = round_cluster_ratio(clustered)
    assert real["ratio"] > fake["ratio"]
    assert real["ratio"] > 2


def test_power_law_tail_fit():
    rng = np.random.default_rng(3)
    # Pareto alpha ≈ 1.5 via inverse CDF.
    u = rng.random(8000)
    sizes = (1 - u) ** (-1 / 1.5)
    alpha = hill_exponent(sizes.tolist(), tail_frac=0.05)
    assert alpha == pytest.approx(1.5, abs=0.35)


def test_candle_volume_benford_removed():
    candles = [{"volume": float(i + 1), "close": 100.0} for i in range(500)]
    out = market_trust(candles, trades=None)
    assert out["tag"] == "NO DATA"
    assert out["acted_on"] is False


def test_trust_is_tag_not_confidence():
    high = LensResult("markov", "UP", 0.8, "", {})
    others = [LensResult(n, "UP", 0.8, "", {}) for n in ("technical", "ai_model", "visual")]
    entropy = LensResult("entropy", "SIDEWAYS", 0.0, "", {"entropy_score": 0.2, "regime": "LOW_ENTROPY", "tipping_risk": "LOW"})
    decision = build_consensus(high, *others, entropy)
    tag = market_trust(None, trades=None)
    # The tag is stored beside the decision. It does not change the number and does not abstain.
    assert tag["tag"] == "NO DATA"
    assert decision["consensus_confidence"] == pytest.approx(0.8)
    assert decision["prediction_direction"] == "UP"


def test_trust_never_abstains():
    tag = market_trust(trades=[1, 2, 3, 5, 8])
    assert tag["tag"] in ("PASS", "WEAK", "FAIL", "NO DATA")
    assert tag["acted_on"] is False


def test_calibration_period_no_data():
    tracker = TrustTracker()
    hour = 3600 * 1000
    start = 1_700_000_000_000
    last = None
    for i in range(24 * 10):
        counters = HourlyCounters()
        for qty in (1, 2, 5, 10, 20):
            counters.add(qty)
        last = tracker.add_hour(start + i * hour, counters)
    assert last["tag"] == "NO DATA"
    # 31 days later the same tracker can leave calibration.
    counters = HourlyCounters()
    for qty in (1, 2, 5, 10):
        counters.add(float(qty))
    tagged = tracker.add_hour(start + 31 * 24 * hour, counters)
    assert tagged["tag"] in ("PASS", "WEAK", "FAIL")


def test_exclusion_needs_300_each_and_rule_version():
    fail = [0.0] * 40
    rest = [0.01] * 40
    assert fail_exclusion_allowed(fail, rest, 100, 100, True, True) is False
    assert fail_exclusion_allowed(fail, rest, 300, 300, False, True) is False
    assert fail_exclusion_allowed(fail, rest, 300, 300, True, False) is False
    # Gap lower bound must be positive. A flat positive gap clears it.
    assert fail_exclusion_allowed([-0.01] * 40, [0.02] * 40, 300, 300, True, True) is True


def test_hourly_counters_bounded_memory():
    counters = HourlyCounters(heap_max=128)
    rng = np.random.default_rng(4)
    for qty in rng.random(100_000) * 10:
        counters.add(float(qty))
    assert counters.raw_retained == 0
    assert len(counters._heap) <= 128
    assert counters.n == 100_000


def test_first_digit_scientific():
    assert first_digit(0.0042) == 4
    assert first_digit(2500) == 2


def test_round_trip_cost_spot_taker(monkeypatch):
    monkeypatch.setenv("FEE_SPOT_TAKER", "0.0010")
    monkeypatch.setenv("SLIPPAGE_PCT", "0.0001")
    assert round_trip_cost("CRYPTO", "spot", "taker", 0.0001) == pytest.approx(0.0022)


def test_round_trip_cost_futures_maker(monkeypatch):
    monkeypatch.setenv("FEE_FUT_MAKER", "0.0002")
    monkeypatch.setenv("SLIPPAGE_PCT", "0.0001")
    assert round_trip_cost("SCALP_METAL", "futures", "maker", 0.0001) == pytest.approx(0.0006)


def test_cost_gate_blocks_small_target(monkeypatch):
    monkeypatch.setenv("FEE_SPOT_TAKER", "0.0010")
    monkeypatch.setenv("SLIPPAGE_PCT", "0.0001")
    gate = evaluate_cost_gate(100_000, 20, 20, venue="spot", fee_mode="taker", spread_pct=0.0001)
    assert gate["blocked"]
    assert "target too small for costs" in gate["reasons"]


def test_cost_gate_blocks_high_breakeven(monkeypatch):
    monkeypatch.setenv("FEE_SPOT_TAKER", "0.0010")
    monkeypatch.setenv("SLIPPAGE_PCT", "0.0001")
    # risk 0.5% sits between 2×cost and 4×cost: reward clears 3×cost, breakeven does not.
    price = 100_000
    atr = price * 0.005
    gate = evaluate_cost_gate(price, atr, atr, venue="spot", fee_mode="taker", spread_pct=0.0001)
    assert "needs >50% wins to break even" in gate["reasons"]
    assert gate["blocked"]


def test_quick_btc_blocked_at_taker_fees(monkeypatch):
    monkeypatch.setenv("FEE_SPOT_TAKER", "0.0010")
    monkeypatch.setenv("SLIPPAGE_PCT", "0.0001")
    price = 100_000
    atr = price * (0.00086 / 1.5)  # the addendum's ~0.086% target
    gate = evaluate_cost_gate(price, atr, atr, venue="spot", fee_mode="taker", spread_pct=0.0001)
    assert gate["blocked"]
    assert "target too small for costs" in gate["reasons"]


def test_maker_requires_trade_through():
    candles = [{"high": 100.2, "low": 100.0, "open": 100, "close": 100.1}]
    assert maker_filled("UP", 100.0, candles, tick=0.1) is False
    candles[0]["low"] = 99.9
    assert maker_filled("UP", 100.0, candles, tick=0.1) is True


def test_not_filled_never_counted():
    assert scalp_net("NOT_FILLED", 0.01, 0.006, 0.002, 0.0, "UP") is None
    assert counts_for_graduation("UP", True, False, 0.002, outcome="NOT_FILLED") is False


def test_net_return_win_loss_timeout():
    assert scalp_net("WIN", 0.01, 0.006, 0.002, 0.0, "UP") == pytest.approx(0.008)
    assert scalp_net("LOSS", 0.01, 0.006, 0.002, 0.0, "UP") == pytest.approx(-0.008)
    assert scalp_net("TIMEOUT", 0.01, 0.006, 0.002, 0.001, "UP") == pytest.approx(-0.001)
    assert scalp_net("TIMEOUT", 0.01, 0.006, 0.002, 0.001, "DOWN") == pytest.approx(-0.003)


def test_expectancy_uses_net():
    nets = [0.008, -0.008, -0.001]
    assert expectancy_net(nets) == pytest.approx(sum(nets) / 3)


def test_metal_fee_warning_when_unconfirmed(monkeypatch, caplog):
    monkeypatch.delenv("METAL_FEE_CONFIRMED", raising=False)
    import config.costs as costs

    costs._metal_warned = False
    with caplog.at_level(logging.WARNING):
        assert warn_if_metal_fee_unconfirmed() is True
    assert "FEE_FUT_TAKER" in caplog.text


def test_verify_correct_up():
    out = verify_prediction("UP", 100, 101)
    assert out["was_correct"] is True
    assert out["outcome"] == "UP"


def test_verify_incorrect():
    out = verify_prediction("UP", 100, 99)
    assert out["was_correct"] is False
    assert out["outcome"] == "DOWN"


def test_verify_sideways_band():
    out = verify_prediction("UP", 100, 100.05)
    assert out["outcome"] == "SIDEWAYS"
    assert out["was_correct"] is False


def test_abstain_excluded_from_accuracy():
    out = verify_prediction("ABSTAIN", 100, 110)
    assert out["was_correct"] is None
    stats = record_verification(
        empty_stats(),
        symbol="BTCUSDT",
        asset_class="CRYPTO",
        was_correct=None,
        entropy_regime="HIGH_ENTROPY",
        trust_tag="NO DATA",
        lens_directions={"technical": "UP"},
        actual="UP",
    )
    assert stats == {}


def test_weight_bounds_and_sum():
    weights = recompute_directional_weights({"markov": 1.0, "technical": 0.0, "ai_model": 0.0, "visual": 0.0}, ["markov", "technical", "ai_model", "visual"])
    directional = [weights[k] for k in ("markov", "technical", "ai_model", "visual")]
    assert min(directional) >= 0.05 - 1e-9
    assert max(directional) <= 0.60 + 1e-9
    assert sum(directional) == pytest.approx(0.75)
    assert weights["entropy"] == pytest.approx(0.25)
    assert sum(weights.values()) == pytest.approx(1.0)


def test_better_lens_gets_more_weight():
    weights = recompute_directional_weights(
        {"markov": 0.9, "technical": 0.4, "ai_model": 0.4, "visual": 0.4},
        ["markov", "technical", "ai_model", "visual"],
    )
    assert weights["markov"] > weights["technical"]


def test_sideways_never_counted():
    assert counts_for_graduation("SIDEWAYS", True, False, 0.01) is False
    assert counts_for_graduation("ABSTAIN", True, False, 0.01) is False
    assert counts_for_graduation("UP", True, False, 0.01) is True
    assert counts_for_graduation("DOWN", True, True, 0.01) is False


def test_baselines_same_call_set():
    moves = [1, 1, -1, 0]
    prev = [1, -1, -1, 0]
    out = baselines_from_moves(moves, prev)
    assert out["ALWAYS_UP"] == pytest.approx(0.5)
    assert out["ALWAYS_DOWN"] == pytest.approx(0.25)
    assert out["COIN"] == 0.5
    assert out["baseline_hit"] == max(out["ALWAYS_UP"], out["ALWAYS_DOWN"], out["PERSISTENCE"], out["COIN"])


def test_wilson_lower_bound_known_values():
    assert wilson_lower(50, 100, 1.96) == pytest.approx(0.4038, abs=0.001)


def _calls(n_hit, n_miss, net_hit=0.01, net_miss=-0.01, day="2024-01-01"):
    rows = []
    for i in range(n_hit):
        rows.append({"hit": True, "net": net_hit, "day": day, "risk": 0.01, "since_rule_change": True})
    for i in range(n_miss):
        rows.append({"hit": False, "net": net_miss, "day": day, "risk": 0.01, "since_rule_change": True})
    return rows


def test_learner_requires_beating_baseline():
    good = _calls(270, 30)
    assert evaluate_level(good, baseline_hit=0.5, z=2.33) == "Learner"
    # 52% at n=300 does not clear a 2.33 Wilson bound over a 0.55 baseline.
    weak = _calls(156, 144)
    assert evaluate_level(weak, baseline_hit=0.55, z=2.33) == "Observer"


def test_competent_requires_net_lb_positive():
    # High hit rate, but every trade loses money. Learner, not Competent.
    rows = _calls(600, 0, net_hit=-0.001)
    # Spread the days so the daily bound is defined and negative.
    for i, row in enumerate(rows):
        row["day"] = f"2024-01-{(i % 28) + 1:02d}"
    assert evaluate_level(rows, baseline_hit=0.5, z=2.33) == "Learner"


def test_advisor_uses_post_change_calls():
    rows = _calls(1000, 0, net_hit=0.01)
    for i, row in enumerate(rows):
        row["day"] = f"2024-{(i % 12) + 1:02d}-01"
        row["since_rule_change"] = i >= 800
    level = evaluate_level(rows, baseline_hit=0.5, z=1.0)
    assert level != "Advisor"
    assert level != "Expert"


def test_checkpoint_only_evaluation():
    rows = _calls(400, 0, net_hit=-0.0001)
    assert evaluate_level(rows[:299], 0.5, 2.33) == "Observer"
    assert evaluate_level(rows[:300], 0.5, 2.33) == "Learner"


def test_demotion_rolling_300():
    good = _calls(900, 0, net_hit=-0.0001)
    bad = _calls(0, 300, net_hit=0, net_miss=-0.0001)
    rows = good + bad
    for i, row in enumerate(rows):
        row["day"] = f"d{i // 10}"
    # Lifetime hit rate is 75%, which still beats 0.5, but the latest 300 are all misses.
    assert evaluate_level(rows, baseline_hit=0.5, z=2.33) == "Observer"


def test_rule_change_writes_version():
    log = RuleLog()
    assert log.current == 1
    new_id = log.change("froze the backtest rules")
    assert new_id == 2
    assert log.rows[-1]["description"] == "froze the backtest rules"


def test_learner_ladder_matches_matrix_ladder():
    rows = _calls(300, 0, net_hit=-0.001)
    assert evaluate_learner_ladder(rows, 0.5, 2.33) == evaluate_level(rows, 0.5, 2.33)


def test_z_scales_with_tries():
    assert z_for_k(1) == 2.33
    assert z_for_k(5) == 2.88
    assert z_for_k(10) == 3.09
    assert z_for_k(20) == 3.29
    assert z_for_k(50) == 3.54
    with pytest.raises(ValueError):
        z_for_k(51)


def test_weight_book_updates_every_n():
    book = WeightBook(["markov", "technical"], every=2)
    book.observe("CRYPTO", {"markov": True, "technical": False})
    first = book.for_class("CRYPTO")
    book.observe("CRYPTO", {"markov": True, "technical": False})
    second = book.for_class("CRYPTO")
    assert second["markov"] >= first["markov"]
