"""Round-trip trading costs. Every brain calls this function."""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("trading_matrix.costs")

_metal_warned = False


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return float(default)
    return float(raw)


def side_fee(venue: str, fee_mode: str) -> float:
    venue = (venue or "other").lower()
    mode = (fee_mode or "taker").lower()
    if venue == "spot":
        if mode == "maker":
            return _env_float("FEE_SPOT_MAKER", 0.0010)
        return _env_float("FEE_SPOT_TAKER", 0.0010)
    if venue == "futures":
        if mode == "maker":
            return _env_float("FEE_FUT_MAKER", 0.0002)
        return _env_float("FEE_FUT_TAKER", 0.0005)
    return _env_float("FEE_OTHER", 0.0003)


def slippage_pct() -> float:
    return _env_float("SLIPPAGE_PCT", 0.0001)


def scalp_outcome_cost(outcome: str, venue: str, spread_pct: float) -> float | None:
    """Maker entry. A winning limit exit pays maker again. A stop or a time
    exit is a market order and pays taker. NOT_FILLED has no cost.
    """
    if outcome == "NOT_FILLED":
        return None
    maker = side_fee(venue, "maker")
    taker = side_fee(venue, "taker")
    extra = float(spread_pct) + slippage_pct()
    if outcome == "WIN":
        return float(maker + maker + extra)
    if outcome in ("LOSS", "TIMEOUT"):
        return float(maker + taker + extra)
    return None


def round_trip_cost(asset_class: str, venue: str, fee_mode: str, spread_pct: float) -> float:
    """Total cost of entering AND exiting, as a fraction of price.

    cost = fee_in + fee_out + spread_pct + slippage
    """
    fee = side_fee(venue, fee_mode)
    return float(fee + fee + float(spread_pct) + slippage_pct())


def warn_if_metal_fee_unconfirmed() -> bool:
    """Gold/silver perps: do not guess a special fee. Warn and use FEE_FUT_*.

    Returns True when the warning was issued (fee not confirmed by the operator).
    """
    global _metal_warned
    confirmed = os.getenv("METAL_FEE_CONFIRMED", "").strip().lower() in ("1", "true", "yes")
    if confirmed:
        return False
    if not _metal_warned:
        log.warning(
            "XAUUSDT/XAGUSDT fee was not confirmed on Binance's fee page; "
            "using FEE_FUT_TAKER / FEE_FUT_MAKER"
        )
        _metal_warned = True
    return True


def min_reward_cost_ratio() -> float:
    return _env_float("MIN_REWARD_COST_RATIO", 3.0)


def max_breakeven_wr() -> float:
    return _env_float("MAX_BREAKEVEN_WR", 0.50)


def scalp_rr() -> float:
    return _env_float("SCALP_RR", 1.5)


def assumed_spread_pct() -> float:
    return _env_float("BT_ASSUMED_SPREAD_PCT", 0.0001)


def scalp_fee_mode() -> str:
    return os.getenv("SCALP_FEE_MODE", "taker").strip().lower() or "taker"
