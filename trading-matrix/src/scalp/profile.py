"""Volume profile from trades. Adjusts confidence. Never triggers alone."""

from __future__ import annotations


def build_profile(trades: list[tuple[float, float]], atr: float) -> dict | None:
    """trades are (price, qty). Bin size is 0.1 × ATR."""
    if atr <= 0 or not trades:
        return None
    bin_size = 0.1 * atr
    buckets: dict[float, float] = {}
    for price, qty in trades:
        key = round(price / bin_size) * bin_size
        buckets[key] = buckets.get(key, 0.0) + qty
    prices = sorted(buckets)
    poc = max(prices, key=lambda p: buckets[p])
    total = sum(buckets.values())
    idx = prices.index(poc)
    lo = hi = idx
    vol = buckets[poc]
    while vol < 0.70 * total and (lo > 0 or hi < len(prices) - 1):
        left = buckets[prices[lo - 1]] if lo > 0 else -1.0
        right = buckets[prices[hi + 1]] if hi < len(prices) - 1 else -1.0
        if right >= left:
            hi += 1
            vol += buckets[prices[hi]]
        else:
            lo -= 1
            vol += buckets[prices[lo]]
    hvn = []
    lvn = []
    for i, price in enumerate(prices):
        if i == 0 or i == len(prices) - 1:
            continue
        if buckets[price] >= buckets[prices[i - 1]] and buckets[price] >= buckets[prices[i + 1]]:
            hvn.append(price)
        if buckets[price] <= buckets[prices[i - 1]] and buckets[price] <= buckets[prices[i + 1]]:
            lvn.append(price)
    return {
        "bin_size": bin_size,
        "poc": poc,
        "vah": prices[hi],
        "val": prices[lo],
        "hvn": hvn,
        "lvn": lvn,
        "covered": vol / total if total else 0.0,
        "buckets": buckets,
    }


def apply_profile_modifier(direction: str, entry: float, reward_price: float, profile: dict | None, price_just_touched: float | None = None) -> tuple[float, dict]:
    if profile is None:
        return 1.0, {"modifier": 1.0}
    hvn = profile["hvn"]
    lvn = profile["lvn"]
    low_edge, high_edge = sorted((entry, reward_price))
    blocked = any(low_edge < node < high_edge for node in hvn)
    if blocked:
        return 0.6, {"modifier": 0.6, "target_blocked_by_hvn": True, "poc": profile["poc"], "vah": profile["vah"], "val": profile["val"]}
    # Fast zone: breaking a value-area edge into an LVN in the setup direction.
    if direction == "UP" and entry >= profile["vah"] and any(node > entry for node in lvn):
        return 1.15, {"modifier": 1.15, "fast_zone": True, "poc": profile["poc"], "vah": profile["vah"], "val": profile["val"]}
    if direction == "DOWN" and entry <= profile["val"] and any(node < entry for node in lvn):
        return 1.15, {"modifier": 1.15, "fast_zone": True, "poc": profile["poc"], "vah": profile["vah"], "val": profile["val"]}
    if price_just_touched is not None:
        near = [profile["poc"], *hvn]
        if any(abs(price_just_touched - node) <= profile["bin_size"] for node in near):
            away = (direction == "UP" and entry >= price_just_touched) or (direction == "DOWN" and entry <= price_just_touched)
            if away:
                return 1.1, {"modifier": 1.1, "bounce": True, "poc": profile["poc"], "vah": profile["vah"], "val": profile["val"]}
    return 1.0, {"modifier": 1.0, "poc": profile["poc"], "vah": profile["vah"], "val": profile["val"]}
