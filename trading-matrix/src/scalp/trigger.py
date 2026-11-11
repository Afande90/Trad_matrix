"""A setup triggers only when the cost gate passes, S1 clears the score, and
both the ensemble and the order-flow lens agree with S1. S6 cannot trigger.
Entropy does not scale confidence.
"""

from __future__ import annotations

from src.prediction.schemas import LensResult
from src.scalp.profile import apply_profile_modifier


def agrees(lens: LensResult | None, direction: str) -> bool:
    return lens is not None and lens.direction == direction and not lens.raw_data.get("silent", False)


def should_trigger(
    s1_score: float,
    s1_direction: str,
    s2: LensResult | None,
    s5: LensResult | None,
    gate_blocked: bool,
    min_score: float = 4.5,
) -> bool:
    if gate_blocked:
        return False
    if s1_score < min_score:
        return False
    votes = 0
    if agrees(s2, s1_direction):
        votes += 1
    if agrees(s5, s1_direction):
        votes += 1
    return votes >= 2


def scalp_confidence(s1_score: float, s2: LensResult | None, profile_multiplier: float) -> float:
    parts = [s1_score / 10.0]
    if s2 is not None:
        parts.append(s2.confidence)
    base = sum(parts) / len(parts)
    return float(min(1.0, base * profile_multiplier))


def profile_adjustment(direction: str, entry: float, reward_price: float, profile: dict | None):
    return apply_profile_modifier(direction, entry, reward_price, profile)
