"""Order-flow lens. Needs aggTrades and a bookTicker imbalance.

Without a book the lens stays silent. It does not invent an imbalance.
"""

from __future__ import annotations

from src.prediction.schemas import LensResult


def delta_ratio(trades: list[tuple[float, bool]]) -> float:
    """trades are (qty, is_buyer_maker). m=true → seller-initiated."""
    buy = 0.0
    sell = 0.0
    for qty, is_buyer_maker in trades:
        if is_buyer_maker:
            sell += qty
        else:
            buy += qty
    total = buy + sell
    if total <= 0:
        return 0.0
    return (buy - sell) / total


def delta_only_lens(trades: list[tuple[float, bool]]) -> LensResult | None:
    """Run 2 lens S5. Buy volume versus sell volume. No book. Silent if there
    are no trades or the two sides are equal.
    """
    if not trades:
        return None
    ratio = delta_ratio(trades)
    if ratio == 0.0:
        return None
    direction = "UP" if ratio > 0 else "DOWN"
    return LensResult(
        "orderflow",
        direction,
        min(1.0, abs(ratio)),
        f"delta_ratio {ratio:.3f} book not used",
        {"delta_ratio": ratio, "book": False, "silent": False},
    )


def orderflow_lens(trades: list[tuple[float, bool]], bid_qty: float | None, ask_qty: float | None) -> LensResult | None:
    if bid_qty is None or ask_qty is None:
        return None
    denom = bid_qty + ask_qty
    if denom <= 0:
        return None
    ratio = delta_ratio(trades)
    imbalance = (bid_qty - ask_qty) / denom
    if abs(ratio) > 0.25 and imbalance * ratio > 0:
        direction = "UP" if ratio > 0 else "DOWN"
        conf = min(1.0, abs(ratio) + abs(imbalance) / 2)
        return LensResult(
            "orderflow",
            direction,
            conf,
            f"delta_ratio {ratio:.3f} book_imbalance {imbalance:.3f}",
            {"delta_ratio": ratio, "book_imbalance": imbalance, "silent": False},
        )
    return None
