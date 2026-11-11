"""Window oracle. The side is the true direction of the whole verification window.

Pass means the gross move is positive and the gap between gross and net is the
cost, to 1e-9. Funding is not part of this identity.
"""

from __future__ import annotations


def window_oracle(entries, exits=None, cost=None) -> dict:
    """Absolute window return minus cost. Funding is not included.

    `window_oracle(pairs, cost)` and `window_oracle(entries, exits, cost)` both work.
    """
    if cost is None and isinstance(exits, (int, float)):
        cost = float(exits)
        pairs = list(entries)
        entries = [p[0] for p in pairs]
        exits = [p[1] for p in pairs]
    grosses: list[float] = []
    for entry, exit_px in zip(entries, exits or []):
        if not entry:
            continue
        grosses.append(abs(exit_px - entry) / entry)
    if not grosses:
        return {
            "gross": None,
            "gross_mean": None,
            "net": None,
            "net_mean": None,
            "cost": float(cost),
            "n": 0,
            "breakeven_hit_rate": None,
            "wiring_ok": False,
            "passes": False,
            "gross": None,
            "net": None,
            "wiring_ok": False,
            "funding": 0.0,
        }
    gross = sum(grosses) / len(grosses)
    net = gross - float(cost)
    ok = oracle_passes(gross, net, float(cost))
    return {
        "gross": gross,
        "gross_mean": gross,
        "net": net,
        "net_mean": net,
        "cost": float(cost),
        "n": len(grosses),
        "breakeven_hit_rate": breakeven_hit_rate(float(cost), gross),
        "wiring_ok": ok,
        "passes": ok,
    }


def oracle_passes(gross_mean: float | None, net_mean: float | None, cost: float | None) -> bool:
    if gross_mean is None or net_mean is None or cost is None:
        return False
    if gross_mean <= 0:
        return False
    return abs((gross_mean - net_mean) - float(cost)) <= 1e-9


def window_pairs(candles: list[dict], window_min: int) -> tuple[list[float], list[float]]:
    """Entry is the next candle's open. Exit is the close at the end of the window."""
    by_ts = {int(c["timestamp"]): c for c in candles}
    window_ms = int(window_min) * 60_000
    entries: list[float] = []
    exits: list[float] = []
    for candle in candles:
        close_time = int(candle["timestamp"]) + 60_000
        if close_time % window_ms != 0:
            continue
        entry = by_ts.get(close_time)
        exit_candle = by_ts.get(close_time + window_ms - 60_000)
        if entry is None or exit_candle is None or not entry["open"]:
            continue
        entries.append(float(entry["open"]))
        exits.append(float(exit_candle["close"]))
    return entries, exits


def breakeven_hit_rate(cost: float, oracle_gross: float) -> float | None:
    if oracle_gross <= 0:
        return None
    return 0.5 + float(cost) / (2.0 * float(oracle_gross))


def ceiling_from_candles(candles: list[dict], window_ms: int, cost: float) -> dict:
    entries, exits = window_pairs(candles, max(1, int(window_ms) // 60_000))
    return window_oracle(entries, exits, cost)


def run_if_ceiling(candles: list[dict], window_ms: int, cost: float, strategy) -> dict:
    """The lens is not called when the window oracle cannot clear its cost."""
    oracle = ceiling_from_candles(candles, window_ms, cost)
    if oracle["net"] is None or oracle["net"] <= 0 or not oracle["wiring_ok"]:
        return {"ran": False, "oracle": oracle, "records": []}
    return {"ran": True, "oracle": oracle, "records": strategy(candles)}
