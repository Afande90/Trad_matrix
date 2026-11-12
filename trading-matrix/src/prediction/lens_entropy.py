"""Shannon entropy meta-lens. It never votes a direction.

MEASUREMENT_FIX B1: modulate_confidence still exists for the unit tests of the
formula, but consensus and the scalp brain do not call it. The score is a tag.
"""

from __future__ import annotations

import numpy as np

from src.prediction.schemas import LensResult


def discretize_returns(closes, n_bins: int = 10) -> list[int]:
    closes = np.asarray(closes, dtype=float)
    if len(closes) < 2:
        return []
    r = np.diff(closes) / closes[:-1]
    if len(r) == 0:
        return []
    if np.allclose(r, r[0]):
        return [0] * len(r)
    edges = np.percentile(r, np.linspace(0, 100, n_bins + 1))
    edges = np.asarray(edges, dtype=float)
    edges[0], edges[-1] = -np.inf, np.inf
    # Duplicate finite edges collapse bins; nudge them so digitize stays defined.
    for i in range(1, len(edges) - 1):
        if edges[i] <= edges[i - 1]:
            edges[i] = edges[i - 1] + 1e-15
    return (np.digitize(r, edges) - 1).tolist()


def shannon_entropy(symbols: list[int], n_bins: int = 10) -> float:
    if not symbols:
        return 0.0
    counts = np.bincount(np.asarray(symbols, dtype=int), minlength=n_bins).astype(float)
    total = counts.sum()
    if total <= 0:
        return 0.0
    p = counts / total
    p = p[p > 0]
    return float(-(p * np.log2(p)).sum())


def normalize_entropy(h: float, n_bins: int = 10) -> float:
    denom = np.log2(n_bins)
    if denom == 0:
        return 0.0
    return float(np.clip(h / denom, 0.0, 1.0))


def entropy_regime(score: float) -> str:
    if score < 0.4:
        return "LOW_ENTROPY"
    if score > 0.7:
        return "HIGH_ENTROPY"
    return "TRANSITIONING"


def entropy_shift(current: float, previous: float | None) -> str:
    if previous is None:
        return "STABLE"
    delta = current - previous
    if abs(delta) > 0.1:
        return "ENTROPY_RISING" if delta > 0 else "ENTROPY_DROPPING"
    return "STABLE"


def modulate_confidence(c: float, entropy_score: float) -> float:
    """Retired from scoring. Kept so the original formula stays tested."""
    return float(c) * (1.0 - 0.7 * float(entropy_score))


def critical_slowing_indicators(closes, window: int = 50) -> dict:
    closes = np.asarray(closes, dtype=float)
    r = np.diff(closes) / closes[:-1] if len(closes) > 1 else np.array([])
    autocorr = 0.0
    if len(r) >= window:
        a = r[-window:-1]
        b = r[-window + 1 :]
        if np.std(a) > 0 and np.std(b) > 0:
            autocorr = float(np.corrcoef(a, b)[0, 1])
            if np.isnan(autocorr):
                autocorr = 0.0
    variance_slope = 0.0
    if len(r) >= window * 2:
        h = window // 2
        v = [float(np.var(r[i - h : i])) for i in range(h, len(r))]
        if len(v) >= 2:
            variance_slope = float(np.polyfit(np.arange(len(v)), v, 1)[0])
    sma = np.convolve(closes, np.ones(20) / 20, mode="valid") if len(closes) >= 20 else np.array([])
    avg_recovery = 0.0
    if len(sma) >= 10:
        dev = closes[-len(sma) :] - sma
        signs = np.sign(dev)
        # zeros stay; crossings of the sign series
        cross = np.where(np.diff(signs))[0]
        if len(cross) >= 2:
            avg_recovery = float(np.mean(np.diff(cross)))
    score = 0.0
    reasons: list[str] = []
    if autocorr > 0.5:
        score += 0.3
        reasons.append(f"High autocorrelation ({autocorr:.2f})")
    if variance_slope > 0:
        score += 0.3
        reasons.append(f"Variance growing ({variance_slope:.6f})")
    if avg_recovery > 8:
        score += 0.4
        reasons.append(f"Slow recovery ({avg_recovery:.1f} periods)")
    risk = "HIGH" if score >= 0.6 else "MODERATE" if score >= 0.3 else "LOW"
    return {
        "autocorrelation_lag1": autocorr,
        "variance_slope": variance_slope,
        "avg_recovery_periods": avg_recovery,
        "tipping_risk": risk,
        "tipping_risk_score": score,
        "tipping_reasons": reasons,
    }


def rolling_entropy_score(closes, window: int = 50, n_bins: int = 10) -> tuple[float, str, float, str]:
    closes = np.asarray(closes, dtype=float)
    symbols = discretize_returns(closes[-window - 1 :], n_bins=n_bins) if len(closes) > 2 else []
    # discretize_returns uses the sample it is given; pass only the trailing window
    tail = closes[-(window + 1) :]
    symbols = discretize_returns(tail, n_bins=n_bins)
    h = shannon_entropy(symbols, n_bins=n_bins)
    score = normalize_entropy(h, n_bins=n_bins)
    # shift vs 5 periods ago: entropy of the window ending 5 bars earlier
    prev_score = None
    if len(closes) > window + 6:
        prev_tail = closes[-(window + 6) : -5]
        prev_h = shannon_entropy(discretize_returns(prev_tail, n_bins=n_bins), n_bins=n_bins)
        prev_score = normalize_entropy(prev_h, n_bins=n_bins)
    change = 0.0 if prev_score is None else float(score - prev_score)
    return score, entropy_regime(score), change, entropy_shift(score, prev_score)


def run_entropy(closes, window: int = 50, n_bins: int = 10) -> LensResult:
    score, regime, change, shift = rolling_entropy_score(closes, window=window, n_bins=n_bins)
    slowing = critical_slowing_indicators(closes, window=window)
    raw = {
        "entropy_score": score,
        "regime": regime,
        "entropy_change": change,
        "shift": shift,
        **slowing,
    }
    reasoning = (
        f"Entropy score {score:.3f} regime {regime} shift {shift} change {change:.3f}. "
        f"Tipping risk {slowing['tipping_risk']} (score {slowing['tipping_risk_score']:.2f}). "
        "This lens does not vote a direction."
    )
    return LensResult("entropy", "SIDEWAYS", 0.0, reasoning, raw)
