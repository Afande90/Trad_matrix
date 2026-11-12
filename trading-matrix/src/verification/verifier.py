"""Outcome check. ABSTAIN is verified with was_correct NULL and never scores."""

from __future__ import annotations

from datetime import datetime, timezone


def classify_move(pct: float, band: float = 0.001) -> str:
    if pct > band:
        return "UP"
    if pct < -band:
        return "DOWN"
    return "SIDEWAYS"


def direction_sign(direction: str) -> int:
    if direction == "UP":
        return 1
    if direction == "DOWN":
        return -1
    return 0


def verify_prediction(predicted: str, price_then: float, price_now: float, verified_at: datetime | None = None) -> dict:
    stamp = (verified_at or datetime.now(timezone.utc)).isoformat()
    if predicted == "ABSTAIN":
        return {
            "outcome": "ABSTAIN",
            "price_at_verification": price_now,
            "was_correct": None,
            "verified_at": stamp,
            "pct": None,
            "counts_for_accuracy": False,
        }
    if price_then == 0:
        pct = 0.0
    else:
        pct = (price_now - price_then) / price_then
    actual = classify_move(pct)
    return {
        "outcome": actual,
        "price_at_verification": price_now,
        "was_correct": predicted == actual,
        "verified_at": stamp,
        "pct": pct,
        "counts_for_accuracy": True,
    }


def trend_returns(direction: str, entry: float, verify_price: float, cost_pct: float) -> dict:
    """MEASUREMENT_FIX A3. gross = direction × (P_verify − P_entry) / P_entry."""
    if entry == 0:
        gross = 0.0
    else:
        gross = direction_sign(direction) * (verify_price - entry) / entry
    net = gross - cost_pct
    hit = gross > 0 and direction in ("UP", "DOWN")
    return {"gross_return_pct": gross, "net_return_pct": net, "hit": hit}


def scalp_net(outcome: str, reward_pct: float, risk_pct: float, cost_pct: float, timeout_return_pct: float, direction: str) -> float | None:
    if outcome == "NOT_FILLED":
        return None
    if outcome == "WIN":
        return reward_pct - cost_pct
    if outcome == "LOSS":
        return -(risk_pct + cost_pct)
    if outcome == "TIMEOUT":
        return direction_sign(direction) * timeout_return_pct - cost_pct
    return None


def expectancy_net(nets: list[float]) -> float:
    if not nets:
        return 0.0
    return float(sum(nets) / len(nets))


def expectancy_r(nets: list[float], risks: list[float]) -> float:
    vals = [n / r for n, r in zip(nets, risks) if r]
    if not vals:
        return 0.0
    return float(sum(vals) / len(vals))


def counts_for_graduation(direction: str, verified: bool, blackout: bool, cost_pct: float | None, outcome: str | None = None) -> bool:
    if direction not in ("UP", "DOWN"):
        return False
    if not verified or blackout:
        return False
    if cost_pct is None:
        return False
    if outcome == "NOT_FILLED":
        return False
    return True
