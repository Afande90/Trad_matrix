import numpy as np
import pytest

from src.prediction.consensus import build_consensus, build_reduced_consensus
from src.prediction.embedder import embed_text
from src.prediction.lens_entropy import (
    critical_slowing_indicators,
    discretize_returns,
    entropy_regime,
    modulate_confidence,
    normalize_entropy,
    run_entropy,
    shannon_entropy,
)
from src.prediction.lens_markov import (
    MarkovState,
    build_transition_matrix,
    label_regimes,
    run_markov,
    stationary_distribution,
)
from src.prediction.lens_technical import _bb_signal, _macd_signal, _rsi_signal, combine_signals, macd_parts, run_technical
from src.prediction.lens_visual import TIMEFRAMES, adjust_visual_confidence, run_visual
from src.prediction.schemas import LensResult
from src.providers.base import RateLimitError
from src.providers.failover import predict_with_failover
from src.providers.gemini import GeminiProvider
from src.providers.groq_provider import GroqProvider


def _up(n=60, step=1.01):
    return 100 * np.cumprod(np.r_[1.0, np.full(n - 1, step)])


def _down(n=60, step=0.99):
    return 100 * np.cumprod(np.r_[1.0, np.full(n - 1, step)])


def test_rsi_overbought():
    result = run_technical(_up())
    assert result.raw_data["rsi"] > 70
    assert result.raw_data["rsi_direction"] == "DOWN"


def test_rsi_oversold():
    result = run_technical(_down())
    assert result.raw_data["rsi"] < 30
    assert result.raw_data["rsi_direction"] == "UP"


def test_rsi_neutral():
    closes = 100 + np.sin(np.linspace(0, 8 * np.pi, 80))
    result = run_technical(closes)
    assert 30 <= result.raw_data["rsi"] <= 70
    assert result.raw_data["rsi_direction"] == "SIDEWAYS"


def test_macd_bullish_cross():
    # The histogram crosses from negative to positive three bars before the end.
    closes = np.concatenate([np.linspace(120, 70, 50), np.linspace(70, 160, 40)])
    result = run_technical(closes[:53])
    assert result.raw_data["macd_direction"] == "UP"


def test_macd_bearish_cross():
    closes = np.concatenate([np.linspace(70, 140, 50), np.linspace(140, 50, 40)])
    result = run_technical(closes[:53])
    assert result.raw_data["macd_direction"] == "DOWN"


def test_bollinger_touch_lower():
    closes = np.concatenate([np.full(30, 100.0), [70.0]])
    result = run_technical(closes)
    assert result.raw_data["bb_direction"] == "UP"


def test_bollinger_touch_upper():
    closes = np.concatenate([np.full(30, 100.0), [130.0]])
    result = run_technical(closes)
    assert result.raw_data["bb_direction"] == "DOWN"


def test_combined_unanimous_up():
    direction, conf = combine_signals([("UP", 0.8), ("UP", 0.6), ("UP", 0.4)])
    assert direction == "UP"
    assert conf == pytest.approx(0.6)


def test_combined_mixed_sideways():
    direction, _ = combine_signals([("UP", 0.9), ("DOWN", 0.8), ("SIDEWAYS", 0.2)])
    assert direction == "SIDEWAYS"


def test_label_regimes_uptrend():
    labels = label_regimes(_up(80, 1.01))
    valid = labels[labels >= 0]
    assert valid[-1] == 2
    assert (valid == 2).mean() > 0.5


def test_label_regimes_downtrend():
    labels = label_regimes(_down(80, 0.99))
    valid = labels[labels >= 0]
    assert (valid == 0).mean() > 0.5


def test_label_regimes_flat():
    labels = label_regimes(np.full(50, 100.0))
    valid = labels[labels >= 0]
    assert set(valid.tolist()) == {1}


def test_markov_labels_all_three_on_random_walk():
    rng = np.random.default_rng(0)
    rets = rng.normal(0, 0.001, 8000)
    price = 100 * np.exp(np.cumsum(rets))
    labels = label_regimes(price)
    valid = labels[labels >= 0]
    shares = np.bincount(valid, minlength=3) / len(valid)
    assert (shares >= 0.10).all()


def test_transition_matrix_rows_sum_to_one():
    matrix = build_transition_matrix([2, 2, 2, 1])
    assert matrix.shape == (3, 3)
    assert np.allclose(matrix.sum(axis=1), 1.0)


def test_transition_matrix_shape_3x3():
    assert build_transition_matrix([0, 1, 2, 2]).shape == (3, 3)


def test_stationary_sums_to_one():
    matrix = build_transition_matrix([0, 1, 2, 2, 1, 0, 0, 1])
    assert stationary_distribution(matrix).sum() == pytest.approx(1.0)


def test_signal_positive_bull_matrix():
    closes = _up(100, 1.02)
    result = run_markov(closes)
    assert result.direction == "UP"
    assert result.confidence > 0


def test_signal_negative_bear_matrix():
    result = run_markov(_down(100, 0.98))
    assert result.direction == "DOWN"


def test_lensresult_contract():
    result = run_markov(_up(80))
    assert result.lens_name == "markov"
    assert result.direction in ("UP", "DOWN", "SIDEWAYS")
    assert 0 <= result.confidence <= 1
    assert "stationary" in result.reasoning
    assert "regime" in result.reasoning


def test_markov_streaming_matches_batch():
    rng = np.random.default_rng(1)
    price = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, 400)))
    labels = label_regimes(price)
    state = MarkovState()
    for px in price:
        state.push(float(px))
    valid = labels[labels >= 0]
    assert state.label == int(valid[-1])
    assert np.allclose(state.matrix(), build_transition_matrix(valid))


def test_discretize_uniform():
    rng = np.random.default_rng(2)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 500)))
    symbols = discretize_returns(closes, n_bins=10)
    counts = np.bincount(symbols, minlength=10)
    assert counts.min() > 0
    assert counts.max() / counts.min() < 3


def test_discretize_trending():
    symbols = discretize_returns(_up(100, 1.01), n_bins=10)
    assert len(symbols) == 99


def test_entropy_maximum_uniform():
    h = shannon_entropy([i % 10 for i in range(100)], n_bins=10)
    assert normalize_entropy(h, 10) == pytest.approx(1.0, abs=1e-9)


def test_entropy_minimum_constant():
    h = shannon_entropy([3, 3, 3, 3], n_bins=10)
    assert h == pytest.approx(0.0)
    assert normalize_entropy(h, 10) == 0.0


def test_normalize_range_0_1():
    assert 0.0 <= normalize_entropy(0.4, 10) <= 1.0


def test_regime_low():
    assert entropy_regime(0.2) == "LOW_ENTROPY"


def test_regime_high():
    assert entropy_regime(0.9) == "HIGH_ENTROPY"


def test_modulate_high_entropy():
    assert modulate_confidence(0.8, 0.9) < 0.4


def test_modulate_low_entropy():
    assert modulate_confidence(0.8, 0.1) > 0.7


def test_autocorrelation_random_near_zero():
    rng = np.random.default_rng(3)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400)))
    out = critical_slowing_indicators(closes)
    assert abs(out["autocorrelation_lag1"]) < 0.3


def test_autocorrelation_trending_high():
    # Returns themselves trend, so lag-1 correlation of the return series is high.
    # A constant drift has no return variance and is not a correlation.
    rets = np.linspace(0.001, 0.02, 200)
    closes = 100 * np.exp(np.cumsum(rets))
    out = critical_slowing_indicators(closes)
    assert out["autocorrelation_lag1"] > 0.5


def test_variance_slope_stable_zero():
    rng = np.random.default_rng(4)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400)))
    out = critical_slowing_indicators(closes)
    assert abs(out["variance_slope"]) < 1e-4


def test_variance_slope_growing_positive():
    rng = np.random.default_rng(5)
    scale = np.linspace(0.001, 0.05, 400)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 1, 400) * scale))
    out = critical_slowing_indicators(closes)
    assert out["variance_slope"] > 0


def test_tipping_risk_low():
    rng = np.random.default_rng(6)
    # Shrinking noise keeps the variance slope from tripping the warning.
    scale = np.linspace(0.02, 0.005, 400)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 1, 400) * scale))
    out = critical_slowing_indicators(closes)
    assert out["tipping_risk"] == "LOW"


def test_tipping_risk_high():
    # Persistent positive returns plus a variance explosion.
    base = np.full(250, 0.002)
    shock = np.linspace(0.0, 0.04, 250)
    rng = np.random.default_rng(7)
    rets = base + rng.normal(0, 1, 250) * shock
    closes = 100 * np.exp(np.cumsum(rets))
    out = critical_slowing_indicators(closes)
    assert out["tipping_risk"] in ("MODERATE", "HIGH")
    assert out["tipping_risk_score"] >= 0.3


def test_entropy_lens_is_sideways():
    result = run_entropy(_up(80))
    assert result.direction == "SIDEWAYS"
    assert "entropy_score" in result.raw_data
    assert "tipping_risk" in result.raw_data


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class _Client:
    def __init__(self, status, payload):
        self.status = status
        self.payload = payload
        self.calls = []

    async def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return _Resp(self.status, self.payload)


@pytest.mark.asyncio
async def test_gemini_success():
    client = _Client(200, {"candidates": [{"content": {"parts": [{"text": '{"direction": "UP", "confidence": 0.6, "reasoning": "because"}'}]}}]})
    result = await GeminiProvider(client=client, api_key="k").predict([{"close": 1}], {"rsi": 50})
    assert result.direction == "UP"
    assert "gemini" in client.calls[0]["url"]


@pytest.mark.asyncio
async def test_gemini_rate_limit_raises():
    client = _Client(429, {})
    with pytest.raises(RateLimitError):
        await GeminiProvider(client=client, api_key="k").predict([], {})


@pytest.mark.asyncio
async def test_groq_success():
    client = _Client(200, {"choices": [{"message": {"content": '{"direction": "DOWN", "confidence": 0.4, "reasoning": "x"}'}}]})
    result = await GroqProvider(client=client, api_key="k").predict([{"close": 1}], {})
    assert result.direction == "DOWN"
    assert client.calls[0]["headers"]["Authorization"] == "Bearer k"


class _P:
    def __init__(self, name, result=None, fail=False):
        self.name = name
        self.result = result
        self.fail = fail

    async def predict(self, candles, indicators):
        if self.fail:
            raise RateLimitError(self.name)
        return self.result


@pytest.mark.asyncio
async def test_failover_first_works():
    ok = LensResult("ai_model", "UP", 0.5, "a", {})
    result = await predict_with_failover([_P("gemini", ok)], [], {})
    assert result.direction == "UP"
    assert result.raw_data["model_used"] == "gemini"


@pytest.mark.asyncio
async def test_failover_cascade():
    ok = LensResult("ai_model", "DOWN", 0.4, "a", {})
    result = await predict_with_failover([_P("gemini", fail=True), _P("groq", ok)], [], {})
    assert result.raw_data["model_used"] == "groq"


@pytest.mark.asyncio
async def test_failover_all_fail():
    result = await predict_with_failover([_P("gemini", fail=True), _P("groq", fail=True)], [], {})
    assert result.direction == "SIDEWAYS"
    assert result.confidence == 0.0
    assert result.raw_data["model_used"] == "none"
    assert "abstaining" in result.reasoning


def _entropy(score=0.2):
    return LensResult("entropy", "SIDEWAYS", 0.0, "e", {"entropy_score": score, "regime": "LOW_ENTROPY", "tipping_risk": "LOW"})


def _lens(name, direction, conf=0.8):
    return LensResult(name, direction, conf, "r", {})


def test_unanimous_4_up():
    out = build_consensus(_lens("markov", "UP"), _lens("technical", "UP"), _lens("ai_model", "UP"), _lens("visual", "UP"), _entropy())
    assert out["prediction_direction"] == "UP"


def test_majority_3_of_4():
    out = build_consensus(_lens("markov", "UP"), _lens("technical", "UP"), _lens("ai_model", "UP"), _lens("visual", "DOWN"), _entropy())
    assert out["prediction_direction"] == "UP"


def test_split_2_2():
    out = build_consensus(_lens("markov", "UP"), _lens("technical", "UP"), _lens("ai_model", "DOWN"), _lens("visual", "DOWN"), _entropy())
    assert out["prediction_direction"] == "ABSTAIN"


def test_all_disagree():
    out = build_consensus(_lens("markov", "UP"), _lens("technical", "DOWN"), _lens("ai_model", "SIDEWAYS"), _lens("visual", "UP"), _entropy())
    assert out["prediction_direction"] == "ABSTAIN"
    assert out["consensus_confidence"] == 0.0


def test_entropy_not_in_confidence():
    voters = [_lens("markov", "UP", 0.8), _lens("technical", "UP", 0.8), _lens("ai_model", "UP", 0.8), _lens("visual", "UP", 0.8)]
    high = build_consensus(*voters, _entropy(0.95))
    low = build_consensus(*[_lens(v.lens_name, v.direction, v.confidence) for v in voters], _entropy(0.05))
    assert high["consensus_confidence"] == pytest.approx(0.8)
    assert low["consensus_confidence"] == pytest.approx(high["consensus_confidence"])


def test_entropy_preserves_confidence():
    # Alias of the measurement-fix rule: low entropy does not inflate the vote.
    out = build_consensus(_lens("markov", "DOWN", 0.5), _lens("technical", "DOWN", 0.5), _lens("ai_model", "DOWN", 0.5), _lens("visual", "UP", 0.1), _entropy(0.0))
    assert out["consensus_confidence"] == pytest.approx(0.5)


def test_reduced_voter_majority():
    agreed = build_reduced_consensus([_lens("markov", "UP", 0.6), _lens("technical", "UP", 0.4)], _entropy())
    assert agreed["prediction_direction"] == "UP"
    split = build_reduced_consensus([_lens("markov", "UP"), _lens("technical", "DOWN")], _entropy())
    assert split["prediction_direction"] == "ABSTAIN"
    three = build_reduced_consensus([_lens("a", "UP"), _lens("b", "UP"), _lens("c", "DOWN")], _entropy())
    assert three["prediction_direction"] == "ABSTAIN"


@pytest.mark.asyncio
async def test_embedding_failure_nonfatal():
    class Boom:
        async def post(self, *a, **k):
            raise RuntimeError("down")

    assert await embed_text("hello", client=Boom()) is None


def test_timeframe_agreement_boost():
    assert adjust_visual_confidence(0.9, 5) == pytest.approx(1.0)


def test_timeframe_agreement_drop():
    assert adjust_visual_confidence(0.5, 2) == pytest.approx(0.3)


@pytest.mark.asyncio
async def test_visual_analysis_mock(monkeypatch):
    monkeypatch.setattr("src.prediction.lens_visual.resample_ohlcv", lambda candles, rule: candles)
    monkeypatch.setattr("src.prediction.lens_visual.render_chart_image", lambda candles, title: b"\x89PNG\r\n\x1a\n")
    client = _Client(
        200,
        {"candidates": [{"content": {"parts": [{"text": '{"direction": "UP", "confidence": 0.5, "reasoning": "scan", "surprise_factors": ["gap"], "timeframe_agreement": 4}'}]}}]},
    )
    result = await run_visual([{"timestamp": 0, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}], client)
    assert result.direction == "UP"
    assert result.raw_data["method"] == "jepa_backward_forward_scan"


@pytest.mark.asyncio
async def test_visual_rate_limit_abstains(monkeypatch):
    monkeypatch.setattr("src.prediction.lens_visual.resample_ohlcv", lambda candles, rule: candles)
    monkeypatch.setattr("src.prediction.lens_visual.render_chart_image", lambda candles, title: b"\x89PNG\r\n\x1a\n")
    result = await run_visual([{"timestamp": 0, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}], _Client(429, {}))
    assert result.direction == "SIDEWAYS"
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_backward_scan_order(monkeypatch):
    seen = []

    def render(candles, title):
        seen.append(title)
        return b"\x89PNG\r\n\x1a\n"

    monkeypatch.setattr("src.prediction.lens_visual.resample_ohlcv", lambda candles, rule: candles)
    monkeypatch.setattr("src.prediction.lens_visual.render_chart_image", render)
    await run_visual([{"timestamp": 0, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}], _Client(500, {}))
    assert seen == [name for name, _rule, _n in TIMEFRAMES]


def test_macd_helper_and_bb_exist():
    # Keeps the cross detector and band helper covered on a short array.
    hist = np.array([-0.2, -0.1, 0.05, 0.1])
    assert _macd_signal(hist, 3)[0] == "UP"
    assert _bb_signal(100, 100, 110, 90)[0] == "SIDEWAYS"
    assert _rsi_signal(80)[0] == "DOWN"
    _ = macd_parts(np.linspace(1, 2, 40))
