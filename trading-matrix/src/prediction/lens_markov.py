"""Markov regime lens.

Math follows source_materials/markov_regime.py. MEASUREMENT_FIX B2 replaces the
fixed 5% threshold with MARKOV_K * sigma * sqrt(window). Empty transition rows
are uniform 1/3 so every row sums to 1 (TECHNICAL_SPEC test).
"""

from __future__ import annotations

import os

import numpy as np

from src.prediction.schemas import LensResult

STATES = ["Bear", "Sideways", "Bull"]


def markov_k() -> float:
    raw = os.getenv("MARKOV_K", "1.0")
    return float(raw) if raw else 1.0


def label_regimes(closes, window: int = 20, threshold: float | None = None, k: float | None = None) -> np.ndarray:
    """Per-bar labels for indices that have a full window. Index-aligned with closes.

    2 = Bull, 0 = Bear, 1 = Sideways. Positions before `window` are -1.
    Threshold defaults to MARKOV_K * std(1-bar returns over the window) * sqrt(window).
    """
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    labels = np.full(n, -1, dtype=int)
    if n <= window:
        return labels
    rets = np.zeros(n)
    rets[1:] = np.diff(closes) / closes[:-1]
    kk = markov_k() if k is None else float(k)
    csum = np.cumsum(rets)
    csum2 = np.cumsum(rets * rets)
    for i in range(window, n):
        rolling = (closes[i] - closes[i - window]) / closes[i - window]
        # std of the `window` one-bar returns that end at i (rets[i-window+1 : i+1])
        a = i - window + 1
        b = i
        length = b - a + 1
        s = csum[b] - (csum[a - 1] if a > 0 else 0.0)
        s2 = csum2[b] - (csum2[a - 1] if a > 0 else 0.0)
        mean = s / length
        var = max(s2 / length - mean * mean, 0.0)
        sigma = var ** 0.5
        thr = float(threshold) if threshold is not None else kk * sigma * np.sqrt(window)
        if rolling > thr:
            labels[i] = 2
        elif rolling < -thr:
            labels[i] = 0
        else:
            labels[i] = 1
    return labels


def build_transition_matrix(labels) -> np.ndarray:
    counts = np.zeros((3, 3), dtype=float)
    arr = np.asarray(labels, dtype=int)
    arr = arr[arr >= 0]
    for i in range(len(arr) - 1):
        a = int(arr[i])
        b = int(arr[i + 1])
        if 0 <= a < 3 and 0 <= b < 3:
            counts[a, b] += 1.0
    matrix = np.zeros((3, 3), dtype=float)
    for i in range(3):
        row_sum = counts[i].sum()
        if row_sum == 0.0:
            matrix[i, :] = 1.0 / 3.0
        else:
            matrix[i, :] = counts[i] / row_sum
    return matrix


def nstep_forecast(matrix: np.ndarray, n: int) -> np.ndarray:
    return np.linalg.matrix_power(matrix, n)


def stationary_distribution(matrix: np.ndarray) -> np.ndarray:
    eigvals, eigvecs = np.linalg.eig(matrix.T)
    idx = int(np.argmin(np.abs(eigvals - 1.0)))
    vec = np.abs(np.real(eigvecs[:, idx]))
    total = vec.sum()
    if total == 0.0:
        return np.ones(3) / 3.0
    return vec / total


def signal_from_matrix(matrix: np.ndarray, current_state: int) -> float:
    return float(matrix[current_state, 2] - matrix[current_state, 0])


def direction_from_signal(signal: float) -> tuple[str, float]:
    if signal > 0.1:
        direction = "UP"
    elif signal < -0.1:
        direction = "DOWN"
    else:
        direction = "SIDEWAYS"
    return direction, float(min(1.0, abs(signal)))


class MarkovState:
    """Incremental transition counts. Same labels and matrix as the batch functions."""

    def __init__(self, window: int = 20, k: float | None = None):
        self.window = window
        self.k = markov_k() if k is None else float(k)
        self.closes: list[float] = []
        self.rets: list[float] = []
        self.counts = np.zeros((3, 3), dtype=float)
        self._last_label: int | None = None
        self.label = -1

    def push(self, close: float) -> int:
        close = float(close)
        if self.closes:
            prev = self.closes[-1]
            self.rets.append((close - prev) / prev if prev else 0.0)
        self.closes.append(close)
        if len(self.rets) > self.window:
            self.rets = self.rets[-self.window :]
        if len(self.closes) > self.window + 1:
            self.closes = self.closes[-(self.window + 1) :]
        label = -1
        if len(self.closes) == self.window + 1 and len(self.rets) == self.window:
            rolling = (self.closes[-1] - self.closes[0]) / self.closes[0]
            sigma = float(np.std(np.asarray(self.rets, dtype=float)))
            thr = self.k * sigma * np.sqrt(self.window)
            if rolling > thr:
                label = 2
            elif rolling < -thr:
                label = 0
            else:
                label = 1
            if self._last_label is not None and self._last_label >= 0:
                self.counts[self._last_label, label] += 1.0
            self._last_label = label
        self.label = label
        return label

    def matrix(self) -> np.ndarray:
        matrix = np.zeros((3, 3), dtype=float)
        for i in range(3):
            row_sum = float(self.counts[i].sum())
            if row_sum == 0.0:
                matrix[i, :] = 1.0 / 3.0
            else:
                matrix[i, :] = self.counts[i] / row_sum
        return matrix


def describe_markov(matrix: np.ndarray, current: int) -> tuple[str, float, str, dict]:
    signal = signal_from_matrix(matrix, current)
    direction, conf = direction_from_signal(signal)
    stat = stationary_distribution(matrix)
    row = matrix[current]
    regime = STATES[current]
    persistence = float(matrix[current, current])
    note = ""
    if float(stat[current]) < persistence:
        note = (
            f" Mean-reversion note: stationary share of {regime} "
            f"({float(stat[current]):.3f}) is below its row persistence ({persistence:.3f})."
        )
    reasoning = (
        f"current regime {regime}; "
        f"row probabilities Bear={row[0]:.3f} Sideways={row[1]:.3f} Bull={row[2]:.3f}; "
        f"signal {signal:.4f}; "
        f"stationary Bear={float(stat[0]):.3f} Sideways={float(stat[1]):.3f} Bull={float(stat[2]):.3f}."
        + note
    )
    raw = {
        "regime": regime,
        "state": int(current),
        "signal": signal,
        "row": [float(x) for x in row],
        "stationary": [float(x) for x in stat],
        "mean_reversion": bool(note),
    }
    return direction, conf, reasoning, raw


def run_markov(closes, window: int = 20) -> LensResult:
    labels = label_regimes(closes, window=window)
    valid = labels[labels >= 0]
    if len(valid) == 0:
        return LensResult("markov", "SIDEWAYS", 0.0, "Not enough closes for a regime label.", {"regime": "unknown"})
    matrix = build_transition_matrix(valid)
    current = int(valid[-1])
    direction, conf, reasoning, raw = describe_markov(matrix, current)
    return LensResult("markov", direction, conf, reasoning, raw)
