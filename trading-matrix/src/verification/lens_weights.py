"""Directional lens weights. Entropy stays at 0.25. The other weights sum to 0.75."""

from __future__ import annotations

import copy

import numpy as np


def _fit_bounds(weights: np.ndarray, lo: float, hi: float, target: float) -> np.ndarray:
    w = np.clip(np.asarray(weights, dtype=float), lo, hi)
    for _ in range(30):
        total = float(w.sum())
        if abs(total - target) < 1e-10:
            return w
        free = (w > lo + 1e-12) & (w < hi - 1e-12)
        if not np.any(free):
            room = (w - lo) if total > target else (hi - w)
            if float(room.sum()) == 0.0:
                return w
            w = np.clip(w + (target - total) * room / room.sum(), lo, hi)
            continue
        fixed_sum = float(w[~free].sum()) if np.any(~free) else 0.0
        gap = target - fixed_sum
        free_sum = float(w[free].sum())
        if free_sum == 0.0:
            w[free] = gap / int(free.sum())
        else:
            w[free] = w[free] * (gap / free_sum)
        w = np.clip(w, lo, hi)
    return w


def recompute_directional_weights(accuracies: dict[str, float], names: list[str]) -> dict[str, float]:
    raw = np.array([max(float(accuracies.get(n, 0.0)), 0.0) for n in names], dtype=float)
    if float(raw.sum()) == 0.0:
        raw = np.ones(len(names), dtype=float)
    scaled = raw / raw.sum() * 0.75
    fitted = _fit_bounds(scaled, 0.05, 0.60, 0.75)
    out = {n: float(fitted[i]) for i, n in enumerate(names)}
    out["entropy"] = 0.25
    return out


class WeightBook:
    def __init__(self, names: list[str], every: int = 100):
        self.names = list(names)
        self.every = every
        self.correct: dict[str, dict[str, int]] = {}
        self.total: dict[str, dict[str, int]] = {}
        self.verified: dict[str, int] = {}
        self.weights: dict[str, dict[str, float]] = {}

    def _ensure(self, asset_class: str) -> None:
        if asset_class not in self.weights:
            self.correct[asset_class] = {n: 0 for n in self.names}
            self.total[asset_class] = {n: 0 for n in self.names}
            self.verified[asset_class] = 0
            self.weights[asset_class] = recompute_directional_weights({}, self.names)

    def observe(self, asset_class: str, lens_hits: dict[str, bool]) -> None:
        self._ensure(asset_class)
        self.verified[asset_class] += 1
        for name, hit in lens_hits.items():
            if name not in self.total[asset_class]:
                continue
            self.total[asset_class][name] += 1
            if hit:
                self.correct[asset_class][name] += 1
        if self.verified[asset_class] % self.every == 0:
            acc = {
                n: (self.correct[asset_class][n] / self.total[asset_class][n]) if self.total[asset_class][n] else 0.0
                for n in self.names
            }
            self.weights[asset_class] = recompute_directional_weights(acc, self.names)

    def snapshot(self) -> dict:
        return copy.deepcopy(self.weights)

    def restore(self, snap: dict) -> None:
        self.weights = copy.deepcopy(snap)

    def for_class(self, asset_class: str) -> dict[str, float]:
        self._ensure(asset_class)
        return dict(self.weights[asset_class])
