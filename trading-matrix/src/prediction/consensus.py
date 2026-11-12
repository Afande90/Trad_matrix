"""Consensus. Entropy is stored and does not change confidence (MEASUREMENT_FIX B1).

Live voters: 3 of 4 must agree, else ABSTAIN.
Backtest (AI and visual skipped): 2 of 2 or 3 of 3 must agree, else ABSTAIN.
The trust tag is not applied here and never scales the number.
"""

from __future__ import annotations

from dataclasses import asdict

from src.prediction.schemas import LensResult


def _consensus(voters: list[LensResult], entropy: LensResult, min_agree: int) -> dict:
    # Entropy is not applied. Confidence stays the mean of the agreeing voters.
    directions = [v.direction for v in voters]
    chosen = None
    for candidate in ("UP", "DOWN", "SIDEWAYS"):
        if directions.count(candidate) >= min_agree:
            chosen = candidate
            break
    if chosen is None:
        direction = "ABSTAIN"
        conf = 0.0
        agreeing: list[LensResult] = []
    else:
        direction = chosen
        agreeing = [v for v in voters if v.direction == chosen]
        conf = sum(v.confidence for v in agreeing) / len(agreeing)
    e = entropy.raw_data or {}
    parts = [f"{v.lens_name} {v.direction} {v.confidence:.3f}" for v in voters]
    parts.append(
        f"entropy_score {e.get('entropy_score')} regime {e.get('regime')} "
        f"tipping_risk {e.get('tipping_risk')}"
    )
    parts.append(f"verdict {direction}")
    lenses = {v.lens_name: asdict(v) for v in list(voters) + [entropy]}
    return {
        "prediction_direction": direction,
        "consensus_confidence": float(conf),
        "reasoning": "; ".join(parts),
        "lenses": lenses,
    }


def build_consensus(markov: LensResult, technical: LensResult, ai_model: LensResult, visual: LensResult, entropy: LensResult) -> dict:
    return _consensus([markov, technical, ai_model, visual], entropy, min_agree=3)


def build_reduced_consensus(voters: list[LensResult], entropy: LensResult) -> dict:
    n = len(voters)
    if n not in (2, 3):
        raise ValueError("reduced voter set must be 2 or 3")
    return _consensus(voters, entropy, min_agree=n)
