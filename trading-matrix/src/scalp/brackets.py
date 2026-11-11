"""First-touch brackets. Same-candle ambiguity uses aggTrades or counts as a loss."""

from __future__ import annotations


def bracket_prices(direction: str, entry: float, reward_pct: float, risk_pct: float) -> tuple[float, float]:
    if direction == "UP":
        return entry * (1.0 + reward_pct), entry * (1.0 - risk_pct)
    return entry * (1.0 - reward_pct), entry * (1.0 + risk_pct)


def _candle_hits(candle: dict, direction: str, reward_px: float, risk_px: float) -> tuple[bool, bool]:
    high = float(candle["high"])
    low = float(candle["low"])
    if direction == "UP":
        return high >= reward_px, low <= risk_px
    return low <= reward_px, high >= risk_px


def _first_in_trades(trades: list[tuple[int, float]], direction: str, reward_px: float, risk_px: float) -> str | None:
    for _ts, price in trades:
        if direction == "UP":
            if price >= reward_px:
                return "reward"
            if price <= risk_px:
                return "risk"
        else:
            if price <= reward_px:
                return "reward"
            if price >= risk_px:
                return "risk"
    return None


def resolve_path(
    direction: str,
    entry: float,
    reward_pct: float,
    risk_pct: float,
    candles: list[dict],
    max_hold: int,
    trade_paths: dict | None = None,
) -> dict:
    """`candles` start at the entry candle. Checkpoints are minutes while open."""
    reward_px, risk_px = bracket_prices(direction, entry, reward_pct, risk_pct)
    sign = 1.0 if direction == "UP" else -1.0
    mfe = 0.0
    mae = 0.0
    checkpoints: dict[str, float] = {}
    resolved_by = None
    outcome = "TIMEOUT"
    exit_price = float(candles[min(max_hold, len(candles)) - 1]["close"]) if candles else entry
    same_candle = {"aggTrades": 0, "loss_no_trades": 0}
    held = candles[:max_hold]
    for i, candle in enumerate(held):
        high = float(candle["high"])
        low = float(candle["low"])
        if direction == "UP":
            mfe = max(mfe, (high - entry) / entry)
            mae = max(mae, (entry - low) / entry)
        else:
            mfe = max(mfe, (entry - low) / entry)
            mae = max(mae, (high - entry) / entry)
        minute = i + 1
        if minute in (5, 15, 30, 60):
            checkpoints[str(minute)] = sign * (float(candle["close"]) - entry) / entry
        hit_reward, hit_risk = _candle_hits(candle, direction, reward_px, risk_px)
        if hit_reward and hit_risk:
            path = None if not trade_paths else trade_paths.get(int(candle["timestamp"]))
            if not path:
                outcome = "LOSS"
                resolved_by = "loss_no_trades"
                same_candle["loss_no_trades"] += 1
                exit_price = risk_px
                held = held[: i + 1]
                break
            which = _first_in_trades(path, direction, reward_px, risk_px)
            same_candle["aggTrades"] += 1
            if which == "reward":
                outcome = "WIN"
                exit_price = reward_px
            else:
                outcome = "LOSS"
                exit_price = risk_px
                if which is None:
                    resolved_by = "loss_no_trades"
            resolved_by = resolved_by or "aggTrades"
            held = held[: i + 1]
            break
        if hit_reward:
            outcome = "WIN"
            resolved_by = "candle"
            exit_price = reward_px
            held = held[: i + 1]
            break
        if hit_risk:
            outcome = "LOSS"
            resolved_by = "candle"
            exit_price = risk_px
            held = held[: i + 1]
            break
    else:
        outcome = "TIMEOUT"
        resolved_by = "timeout"
        if held:
            exit_price = float(held[-1]["close"])
    timeout_return = (exit_price - entry) / entry if entry else 0.0
    return {
        "outcome": outcome,
        "exit_price": exit_price,
        "timeout_return_pct": timeout_return,
        "mfe": mfe,
        "mae": mae,
        "checkpoints": checkpoints,
        "resolved_by": resolved_by,
        "same_candle": same_candle,
        "bars_held": len(held),
        "reward_px": reward_px,
        "risk_px": risk_px,
    }


class PositionBook:
    """One open setup per symbol and class. QUICK does not block EXTENDED."""

    def __init__(self):
        self.until: dict[tuple[str, str], int] = {}

    def can_open(self, symbol: str, setup_class: str, index: int) -> bool:
        end = self.until.get((symbol, setup_class))
        return end is None or index > end

    def open(self, symbol: str, setup_class: str, exit_index: int) -> None:
        self.until[(symbol, setup_class)] = exit_index
