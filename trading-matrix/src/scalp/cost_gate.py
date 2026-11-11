"""Scalp cost gate v2. Dead-market filter stays. Spread-ratio and the old
expected-move test are replaced by the reward/cost and breakeven checks.
"""

from __future__ import annotations

from config.costs import max_breakeven_wr, min_reward_cost_ratio, round_trip_cost, scalp_rr


def evaluate_cost_gate(
    price: float,
    atr: float,
    avg_atr: float,
    *,
    venue: str,
    fee_mode: str,
    spread_pct: float,
    asset_class: str = "CRYPTO",
    rr: float | None = None,
    cost_multiplier: float = 1.0,
    min_vol: float = 0.6,
) -> dict:
    rr = scalp_rr() if rr is None else rr
    reasons: list[str] = []
    blocked = False
    vol_ratio = (atr / avg_atr) if avg_atr else 0.0
    if avg_atr > 0 and atr > 0 and vol_ratio < min_vol:
        blocked = True
        reasons.append("dead market")
    cost = round_trip_cost(asset_class, venue, fee_mode, spread_pct) * cost_multiplier
    reward_pct = (rr * atr / price) if price else 0.0
    risk_pct = (atr / price) if price else 0.0
    denom = reward_pct + risk_pct
    breakeven = 1.0 if denom <= 0 else (risk_pct + cost) / denom
    if reward_pct < min_reward_cost_ratio() * cost:
        blocked = True
        reasons.append("target too small for costs")
    if breakeven > max_breakeven_wr():
        blocked = True
        reasons.append("needs >50% wins to break even")
    return {
        "blocked": blocked,
        "reasons": reasons,
        "cost_pct": cost,
        "reward_pct": reward_pct,
        "risk_pct": risk_pct,
        "breakeven_wr": breakeven,
        "vol_ratio": vol_ratio,
    }


def maker_filled(side: str, setup_price: float, later_candles: list[dict], tick: float, within: int = 3) -> bool:
    """Filled only if a later candle trades THROUGH the setup price by one tick."""
    for candle in later_candles[:within]:
        if side == "UP" and float(candle["low"]) <= setup_price - tick:
            return True
        if side == "DOWN" and float(candle["high"]) >= setup_price + tick:
            return True
    return False
