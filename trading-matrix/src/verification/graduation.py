"""Honest ladder from MEASUREMENT_FIX Part B. Used by the backtest report.

Levels are evaluated only at checkpoints (every 100 counted calls).
"""

from __future__ import annotations

import math

import numpy as np

LEVELS = ["Observer", "Learner", "Competent", "Advisor", "Expert"]


def wilson_lower(hits: int, n: int, z: float) -> float:
    if n <= 0:
        return 0.0
    phat = hits / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (phat + z2 / (2.0 * n)) / denom
    margin = z * math.sqrt(phat * (1.0 - phat) / n + z2 / (4.0 * n * n)) / denom
    return float(center - margin)


def daily_net_lower_bound(daily_totals: list[float], z: float) -> float:
    """net_lb on daily totals. Days with no calls are already 0 in the list."""
    arr = np.asarray(daily_totals, dtype=float)
    n = len(arr)
    if n == 0:
        return 0.0
    mean = float(arr.mean())
    if n < 2:
        return mean
    sd = float(arr.std(ddof=1))
    return mean - z * sd / math.sqrt(n)


def z_for_k(k: int) -> float:
    """Luck correction. K = tracks tested × rule sets tried."""
    if k <= 1:
        return 2.33
    if k <= 5:
        return 2.88
    if k <= 10:
        return 3.09
    if k <= 20:
        return 3.29
    if k <= 50:
        return 3.54
    raise ValueError("K>50: the run proves nothing; simplify and start again")


def baselines_from_moves(moves: list[int], prev_moves: list[int]) -> dict:
    """moves: +1 up, -1 down, 0 flat. Same call set for every baseline.

    ALWAYS_UP / ALWAYS_DOWN / PERSISTENCE hit rates, plus COIN = 0.50.
    baseline_hit is the max of the four.
    """
    n = len(moves)
    if n == 0:
        return {
            "ALWAYS_UP": 0.0,
            "ALWAYS_DOWN": 0.0,
            "PERSISTENCE": 0.0,
            "COIN": 0.50,
            "baseline_hit": 0.50,
        }
    always_up = sum(1 for m in moves if m > 0) / n
    always_down = sum(1 for m in moves if m < 0) / n
    pers_hits = 0
    for m, prev in zip(moves, prev_moves):
        if prev > 0 and m > 0:
            pers_hits += 1
        elif prev < 0 and m < 0:
            pers_hits += 1
        elif prev == 0 and m == 0:
            pers_hits += 1
    persistence = pers_hits / n
    coin = 0.50
    baseline = max(always_up, always_down, persistence, coin)
    return {
        "ALWAYS_UP": always_up,
        "ALWAYS_DOWN": always_down,
        "PERSISTENCE": persistence,
        "COIN": coin,
        "baseline_hit": baseline,
    }


def _drop(level: str) -> str:
    idx = LEVELS.index(level)
    return LEVELS[max(0, idx - 1)]


def _recent(calls: list[dict], k: int) -> list[dict]:
    return calls[-k:] if len(calls) >= k else calls


def highest_qualifying(
    calls: list[dict],
    baseline_hit: float,
    z: float,
    max_dd_r: float = 30.0,
) -> str:
    """Promotion table only (no demotion). `calls` are counted calls in time order."""
    n = len(calls)
    if n == 0:
        return "Observer"
    hits = sum(1 for c in calls if c.get("hit"))
    hit_lb = wilson_lower(hits, n, z)
    nets = [float(c["net"]) for c in calls]
    # Daily totals across the days present on the calls, plus the caller may
    # have stored `daily_totals` on the first call. Fall back to one bucket per
    # call-day.
    daily = _daily_totals(calls)
    net_lb = daily_net_lower_bound(daily, z)
    level = "Observer"
    if n >= 300 and hit_lb > baseline_hit:
        level = "Learner"
    if n >= 600 and net_lb > 0:
        level = "Competent"
    post = [c for c in calls if c.get("since_rule_change")]
    if not any("since_rule_change" in c for c in calls):
        post = calls
    post_daily = _daily_totals(post) if post else []
    post_net_lb = daily_net_lower_bound(post_daily, z) if post else -1.0
    if n >= 1000 and net_lb > 0 and len(post) >= 500 and post_net_lb > 0:
        level = "Advisor"
    latest_500 = nets[-500:] if n >= 500 else []
    dd = _max_drawdown_r(calls)
    if (
        n >= 2000
        and net_lb > 0
        and len(post) >= 500
        and post_net_lb > 0
        and latest_500
        and float(np.mean(latest_500)) > 0
        and dd <= max_dd_r
    ):
        level = "Expert"
    return level


def _daily_totals(calls: list[dict]) -> list[float]:
    if not calls:
        return []
    if calls and calls[0].get("calendar_daily") is not None:
        return list(calls[0]["calendar_daily"])
    buckets: dict[str, float] = {}
    order: list[str] = []
    for c in calls:
        day = str(c.get("day"))
        if day not in buckets:
            buckets[day] = 0.0
            order.append(day)
        buckets[day] += float(c["net"])
    return [buckets[d] for d in order]


def _max_drawdown_r(calls: list[dict]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for c in calls:
        risk = float(c.get("risk") or 0.0)
        net = float(c["net"])
        r = net / risk if risk else net
        equity += r
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def evaluate_level(
    calls: list[dict],
    baseline_hit: float,
    z: float,
    max_dd_r: float = 30.0,
    calendar: list[str] | None = None,
) -> str:
    """Checkpoint-only evaluation. Days with no calls count as 0, and a
    checkpoint cannot see days after its last call.
    """
    n = len(calls)
    if n < 100:
        return "Observer"
    level = "Observer"
    for checkpoint in range(100, n + 1, 100):
        window = calls[:checkpoint]
        if calendar:
            last_day = str(window[-1].get("day"))
            days = [d for d in calendar if d <= last_day]
            totals = {d: 0.0 for d in days}
            for call in window:
                day = str(call.get("day"))
                if day in totals:
                    totals[day] += float(call["net"])
            stamped = [dict(c) for c in window]
            if stamped:
                stamped[0] = dict(stamped[0])
                stamped[0]["calendar_daily"] = [totals[d] for d in days]
            promoted = highest_qualifying(stamped, baseline_hit, z, max_dd_r=max_dd_r)
        else:
            promoted = highest_qualifying(window, baseline_hit, z, max_dd_r=max_dd_r)
        recent = _recent(window, 300)
        if promoted == "Learner" and len(recent) >= 300:
            hit_rate = sum(1 for c in recent if c.get("hit")) / len(recent)
            if hit_rate < baseline_hit:
                promoted = "Observer"
        elif promoted in ("Competent", "Advisor", "Expert") and len(recent) >= 300:
            if float(np.mean([c["net"] for c in recent])) < 0:
                promoted = _drop(promoted)
        level = promoted
    return level


def evaluate_learner_ladder(calls: list[dict], baseline_hit: float, z: float, max_dd_r: float = 30.0) -> str:
    """Trader School uses the same ladder. Same function, separate name."""
    return evaluate_level(calls, baseline_hit, z, max_dd_r=max_dd_r)


class RuleLog:
    """Local rule-change log. The live Supabase table already has row 1."""

    def __init__(self):
        self.rows = [{"id": 1, "description": "initial rules"}]

    def change(self, description: str) -> int:
        new_id = self.rows[-1]["id"] + 1
        self.rows.append({"id": new_id, "description": description})
        return new_id

    @property
    def current(self) -> int:
        return self.rows[-1]["id"]
