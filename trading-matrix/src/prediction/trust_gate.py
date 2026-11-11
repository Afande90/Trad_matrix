"""Data trust tag. TRUST_GATE Revisions 1–2.

The tag is PASS / WEAK / FAIL / NO DATA. It never abstains and never scales
confidence. Candle-volume Benford and return-Zipf are retired.

Benford uses Nigrini MAD bands. Clustering and the Hill tail have no published
cutoffs for Binance aggTrades: the first 30 days are calibration (tag NO DATA);
after that FAIL means the latest reading is outside that symbol's own 1st–99th
percentile. WEAK is the band between the 5th and the 1st (and 95th–99th), the
only split that keeps the three labels without inventing a research cutoff.
"""

from __future__ import annotations

import heapq
import math
from collections import Counter

import numpy as np

BENFORD = {d: math.log10(1.0 + 1.0 / d) for d in range(1, 10)}
ROUND_LEVELS = (0.1, 0.5, 1.0, 5.0, 10.0)
CALIBRATION_MS = 30 * 24 * 3600 * 1000
HEAP_MAX = 4096


def first_digit(x: float) -> int:
    if x == 0:
        return 0
    s = f"{abs(x):.10e}"
    return int(s[0])


def benford_mad(values: list[float]) -> dict:
    """MAD of first-digit shares vs Benford. Chi-square is stored and never decides."""
    clean = [v for v in values if v is not None and v > 0]
    if not clean:
        return {"mad": None, "chi2_counts": None, "n": 0, "band": "NO DATA"}
    digits = [first_digit(v) for v in clean]
    counts = Counter(digits)
    n = len(digits)
    mad_sum = 0.0
    chi2 = 0.0
    observed = {}
    for d in range(1, 10):
        obs = counts.get(d, 0) / n
        exp = BENFORD[d]
        observed[d] = obs
        mad_sum += abs(obs - exp)
        expected_count = exp * n
        chi2 += (counts.get(d, 0) - expected_count) ** 2 / expected_count
    mad = mad_sum / 9.0
    return {
        "mad": mad,
        "chi2_counts": chi2,
        "n": n,
        "observed": observed,
        "band": mad_band(mad),
    }


def mad_band(mad: float) -> str:
    """Nigrini: PASS <= 0.012, WEAK through 0.015, else FAIL."""
    if mad <= 0.012:
        return "PASS"
    if mad <= 0.015:
        return "WEAK"
    return "FAIL"


def _is_round_size(qty: float) -> bool:
    if qty <= 0:
        return False
    for level in ROUND_LEVELS:
        # Same levels across orders of magnitude (0.001, 0.01, 0.1, 1, 10, ...).
        scale = 10 ** math.floor(math.log10(qty))
        for candidate in (level * scale, level * scale * 10):
            if candidate <= 0:
                continue
            if abs(qty - candidate) / candidate <= 0.02:
                return True
    return False


def _neighbor_side(qty: float) -> str | None:
    """'low' / 'high' if qty sits in the non-round band beside a round level."""
    if qty <= 0 or _is_round_size(qty):
        return None
    scale = 10 ** math.floor(math.log10(qty))
    for level in ROUND_LEVELS:
        for candidate in (level * scale, level * scale * 10):
            if candidate <= 0:
                continue
            rel = qty / candidate
            if 0.90 <= rel < 0.98:
                return "low"
            if 1.02 < rel <= 1.10:
                return "high"
    return None


def round_cluster_ratio(values: list[float]) -> dict:
    """Share of round sizes vs the average share of the two neighbouring bands."""
    clean = [float(v) for v in values if v is not None and v > 0]
    n = len(clean)
    if n == 0:
        return {"ratio": None, "n": 0, "round_share": 0.0, "neighbor_share": 0.0}
    rounds = 0
    low = 0
    high = 0
    for v in clean:
        if _is_round_size(v):
            rounds += 1
            continue
        side = _neighbor_side(v)
        if side == "low":
            low += 1
        elif side == "high":
            high += 1
    round_share = rounds / n
    neighbor_share = ((low / n) + (high / n)) / 2.0
    ratio = None if neighbor_share == 0 else round_share / neighbor_share
    return {
        "ratio": ratio,
        "n": n,
        "round_share": round_share,
        "neighbor_share": neighbor_share,
        "round_count": rounds,
        "neighbor_low": low,
        "neighbor_high": high,
    }


def hill_exponent(values: list[float], tail_frac: float = 0.05) -> float | None:
    """Hill estimate on the largest `tail_frac` of the sample."""
    clean = np.asarray([v for v in values if v is not None and v > 0], dtype=float)
    if len(clean) < 20:
        return None
    ordered = np.sort(clean)[::-1]
    k = max(2, int(len(ordered) * tail_frac))
    k = min(k, len(ordered) - 1)
    tail = ordered[:k]
    threshold = ordered[k]
    if threshold <= 0:
        return None
    logs = np.log(tail / threshold)
    denom = float(np.sum(logs))
    if denom <= 0:
        return None
    return float(k / denom)


def _worst(*bands: str) -> str:
    rank = {"FAIL": 3, "WEAK": 2, "PASS": 1, "NO DATA": 0}
    best = "PASS"
    for band in bands:
        if band and rank.get(band, 0) > rank.get(best, 0):
            best = band
    return best


def _percentile_band(value: float | None, samples: list[float]) -> str:
    if value is None or len(samples) < 24:
        return "NO DATA"
    arr = np.asarray(samples, dtype=float)
    p01, p05, p95, p99 = np.percentile(arr, [1, 5, 95, 99])
    if value < p01 or value > p99:
        return "FAIL"
    if value < p05 or value > p95:
        return "WEAK"
    return "PASS"


class HourlyCounters:
    """Bounded counters for one hour. Raw trades are not retained."""

    def __init__(self, heap_max: int = HEAP_MAX):
        self.heap_max = heap_max
        self.digits = [0] * 10
        self.n = 0
        self.round_count = 0
        self.neighbor_low = 0
        self.neighbor_high = 0
        self._heap: list[float] = []  # min-heap of the largest sizes
        self.raw_retained = 0

    def add(self, qty: float) -> None:
        if qty is None or qty <= 0:
            return
        qty = float(qty)
        self.n += 1
        dig = first_digit(qty)
        if 1 <= dig <= 9:
            self.digits[dig] += 1
        if _is_round_size(qty):
            self.round_count += 1
        else:
            side = _neighbor_side(qty)
            if side == "low":
                self.neighbor_low += 1
            elif side == "high":
                self.neighbor_high += 1
        if len(self._heap) < self.heap_max:
            heapq.heappush(self._heap, qty)
        elif qty > self._heap[0]:
            heapq.heapreplace(self._heap, qty)

    def snapshot(self) -> dict:
        n = self.n
        mad = None
        chi2 = None
        if n > 0:
            mad_sum = 0.0
            chi2 = 0.0
            for d in range(1, 10):
                obs = self.digits[d] / n
                exp = BENFORD[d]
                mad_sum += abs(obs - exp)
                expected = exp * n
                chi2 += (self.digits[d] - expected) ** 2 / expected
            mad = mad_sum / 9.0
        neighbor_share = 0.0
        round_share = 0.0
        ratio = None
        if n > 0:
            round_share = self.round_count / n
            neighbor_share = ((self.neighbor_low / n) + (self.neighbor_high / n)) / 2.0
            if neighbor_share > 0:
                ratio = round_share / neighbor_share
        hill = hill_exponent(self._heap, tail_frac=0.05) if self._heap else None
        return {
            "n": n,
            "mad": mad,
            "chi2_counts": chi2,
            "benford_band": None if mad is None else mad_band(mad),
            "cluster_ratio": ratio,
            "hill": hill,
            "heap_size": len(self._heap),
        }


class TrustTracker:
    """Per-symbol hourly readings. Tag is NO DATA until 30 days have elapsed."""

    def __init__(self):
        self.readings: list[dict] = []

    def add_hour(self, ts_ms: int, counters: HourlyCounters) -> dict:
        snap = counters.snapshot()
        snap["ts"] = int(ts_ms)
        self.readings.append(snap)
        # Keep a bounded history (a few months of hours) so memory stays flat.
        if len(self.readings) > 24 * 120:
            self.readings = self.readings[-24 * 120 :]
        return self.tag(int(ts_ms))

    def tag(self, ts_ms: int) -> dict:
        if not self.readings:
            return _tag("NO DATA", reason="no trade counters")
        first = self.readings[0]["ts"]
        if ts_ms - first < CALIBRATION_MS:
            return _tag("NO DATA", reason="calibration period (first 30 days)", latest=self.readings[-1])
        calib_end = first + CALIBRATION_MS
        calib = [r for r in self.readings if r["ts"] < calib_end and r.get("mad") is not None]
        latest = self.readings[-1]
        benford = latest.get("benford_band") or "NO DATA"
        ratios = [r["cluster_ratio"] for r in calib if r.get("cluster_ratio") is not None]
        hills = [r["hill"] for r in calib if r.get("hill") is not None]
        cluster_band = _percentile_band(latest.get("cluster_ratio"), ratios)
        tail_band = _percentile_band(latest.get("hill"), hills)
        overall = _worst(benford, cluster_band, tail_band)
        return _tag(
            overall,
            reason="post-calibration",
            latest=latest,
            benford_band=benford,
            cluster_band=cluster_band,
            tail_band=tail_band,
        )


def _tag(label: str, **extra) -> dict:
    out = {"tag": label, "trust_score": None, "acted_on": False}
    out.update(extra)
    return out


def market_trust(candles: list[dict] | None = None, trades: list[float] | None = None, tracker: TrustTracker | None = None, ts_ms: int | None = None) -> dict:
    """Tag only. Candle volumes are ignored on purpose."""
    del candles  # retired: candle-volume Benford is not a trust input
    if tracker is not None and ts_ms is not None:
        return tracker.tag(ts_ms)
    if not trades:
        return _tag("NO DATA", reason="no aggTrades; never a fake PASS")
    counters = HourlyCounters()
    for qty in trades:
        counters.add(float(qty))
    snap = counters.snapshot()
    # A single batch with no 30-day history cannot leave calibration.
    return _tag("NO DATA", reason="no 30-day calibration for this batch", latest=snap, benford_band=snap.get("benford_band"))


def fail_exclusion_allowed(
    fail_daily: list[float],
    rest_daily: list[float],
    fail_calls: int,
    rest_calls: int,
    rule_version_written: bool,
    operator_approved: bool,
    z: float = 2.33,
) -> bool:
    """FAIL may exclude calls only with 300+ in each group, a positive gap
    lower bound on daily totals, a rule_versions row, and operator approval.
    """
    if fail_calls < 300 or rest_calls < 300:
        return False
    if not rule_version_written or not operator_approved:
        return False
    from src.verification.graduation import daily_net_lower_bound

    # Gap = rest - fail, on paired daily totals. Lower bound of the gap above 0.
    n = min(len(fail_daily), len(rest_daily))
    if n < 2:
        return False
    gap = [rest_daily[i] - fail_daily[i] for i in range(n)]
    return daily_net_lower_bound(gap, z) > 0.0
