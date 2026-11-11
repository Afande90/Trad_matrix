"""EXTENDED maker scalp. One position. A fill is a trade through by one tick.

The would-be path assumes the limit filled. Whether aggTrades actually traded
through the setup is recorded separately, including when the answer is no.
"""

from __future__ import annotations

from src.scalp.brackets import resolve_path
from config.costs import scalp_outcome_cost
from src.verification.verifier import scalp_net


def _through(direction: str, price: float, trades: list[tuple], tick: float) -> bool:
    for trade in trades or []:
        px = float(trade[1] if len(trade) >= 2 else trade[0])
        if direction == "UP" and px <= price - tick:
            return True
        if direction == "DOWN" and px >= price + tick:
            return True
    return False


def fill_rate_summary(rows: list[dict]) -> dict:
    def rate(name: str):
        subset = [row for row in rows if row.get("would_be") == name]
        if not subset:
            return None
        return sum(1 for row in subset if row.get("filled")) / len(subset)

    return {"winners": rate("WIN"), "losers": rate("LOSS"), "timeouts": rate("TIMEOUT")}


class ExtendedReplay:
    def __init__(self, *, tick: float, spread_pct: float, venue: str, symbol: str, asset_class: str, max_hold: int = 60, funding: list | None = None):
        self.tick = float(tick)
        self.spread_pct = float(spread_pct)
        self.venue = venue
        self.symbol = symbol
        self.asset_class = asset_class
        self.max_hold = int(max_hold)
        self.funding = list(funding or [])
        self.records: list[dict] = []
        self.would_be: list[dict] = []
        self.watchers: list[dict] = []
        self.working: dict | None = None
        self.triggered = 0
        self.blocked = 0
        self.passed = 0
        self.not_filled = 0
        self.same_candle_trades = 0
        self.same_candle_loss = 0

    def _blocks(self, watcher: dict) -> bool:
        if watcher.get("record_written") and not (watcher.get("filled") and not watcher.get("actual_done")):
            return False
        if watcher.get("filled") and not watcher.get("actual_done"):
            return True
        if not watcher.get("filled") and watcher["fill_checked"] < 3:
            return True
        return False

    def open_setup(self, *, direction: str, price: float, reward_pct: float, risk_pct: float, signal_time: int, score: float, breakeven_wr: float | None = None) -> bool:
        if any(self._blocks(watcher) for watcher in self.watchers):
            return False
        watcher = {
            "direction": direction,
            "price": float(price),
            "reward_pct": float(reward_pct),
            "risk_pct": float(risk_pct),
            "signal_time": int(signal_time),
            "score": float(score),
            "breakeven_wr": breakeven_wr,
            "future": [],
            "trade_paths": {},
            "filled": False,
            "fill_index": None,
            "fill_checked": 0,
            "record_written": False,
            "actual_done": False,
            "breakeven_wr": breakeven_wr,
        }
        self.watchers.append(watcher)
        self.working = watcher
        self.triggered += 1
        return True

    def on_candle(self, candle: dict, trades: list[tuple] | None = None) -> None:
        trades = list(trades or [])
        for watcher in self.watchers:
            if not watcher["record_written"]:
                self._advance(watcher, candle, trades)
        self.watchers = [watcher for watcher in self.watchers if not watcher["record_written"]]

    def _advance(self, watcher: dict, candle: dict, trades: list[tuple]) -> None:
        watcher["future"].append(candle)
        ts = int(candle["timestamp"])
        if trades:
            watcher["trade_paths"][ts] = [(int(trade[0]), float(trade[1])) for trade in trades]
        if not watcher["filled"] and watcher["fill_checked"] < 3 and _through(watcher["direction"], watcher["price"], trades, self.tick):
            watcher["filled"] = True
            watcher["fill_index"] = len(watcher["future"]) - 1
        if watcher["fill_checked"] < 3:
            watcher["fill_checked"] += 1
        path = resolve_path(
            watcher["direction"],
            watcher["price"],
            watcher["reward_pct"],
            watcher["risk_pct"],
            watcher["future"],
            self.max_hold,
            watcher["trade_paths"],
        )
        final = path["outcome"] in ("WIN", "LOSS") or len(watcher["future"]) >= self.max_hold
        if not final:
            return
        # A limit that has not traded through still has the rest of its 3-candle window.
        if not watcher["filled"] and watcher["fill_checked"] < 3:
            return
        if not watcher["filled"]:
            self._close_unfilled(watcher, path)
            return
        actual_candles = watcher["future"][watcher["fill_index"] :]
        actual_paths = {k: v for k, v in watcher["trade_paths"].items() if any(int(c["timestamp"]) == k for c in actual_candles)}
        actual = resolve_path(
            watcher["direction"],
            watcher["price"],
            watcher["reward_pct"],
            watcher["risk_pct"],
            actual_candles,
            self.max_hold,
            actual_paths,
        )
        actual_final = actual["outcome"] in ("WIN", "LOSS") or len(actual_candles) >= self.max_hold
        if not actual_final:
            return
        self.same_candle_trades += int(actual["same_candle"]["aggTrades"])
        self.same_candle_loss += int(actual["same_candle"]["loss_no_trades"])
        would = path["outcome"]
        self.would_be.append({"would_be": would, "filled": True, "signal_time": watcher["signal_time"]})
        outcome = actual["outcome"]
        cost = scalp_outcome_cost(outcome, self.venue, self.spread_pct)
        net = None if cost is None else scalp_net(
            outcome, watcher["reward_pct"], watcher["risk_pct"], cost, actual["timeout_return_pct"], watcher["direction"]
        )
        paid = 0.0
        if self.funding and actual_candles:
            entry_ts = int(actual_candles[0]["timestamp"])
            exit_ts = int(actual_candles[min(len(actual_candles), self.max_hold) - 1]["timestamp"]) + 60_000
            sign = 1.0 if watcher["direction"] == "UP" else -1.0
            for ts_f, rate in self.funding:
                if entry_ts < int(ts_f) <= exit_ts:
                    paid += sign * float(rate)
            if net is not None:
                net -= paid
        gross = None
        if net is not None and cost is not None:
            if outcome == "WIN":
                gross = watcher["reward_pct"]
            elif outcome == "LOSS":
                gross = -watcher["risk_pct"]
            else:
                gross = (net + paid) + cost
        self.records.append(
            {
                "symbol": self.symbol,
                "outcome": outcome,
                "would_be": would,
                "counts_for_graduation": outcome in ("WIN", "LOSS", "TIMEOUT"),
                "prediction_direction": watcher["direction"],
                "signal_time": watcher["signal_time"],
                "price_at_prediction": watcher["price"],
                "cost_pct": cost,
                "gross_return_pct": gross,
                "net_return_pct": net,
                "hit": outcome == "WIN",
                "reward_pct": watcher["reward_pct"],
                "risk_pct": watcher["risk_pct"],
                "breakeven_wr": watcher.get("breakeven_wr"),
                "funding_paid": paid,
                "spread_assumed": True,
                "score": watcher["score"],
                "breakeven_wr": watcher.get("breakeven_wr"),
                "resolved_by": actual["resolved_by"],
            }
        )
        watcher["record_written"] = True
        watcher["actual_done"] = True

    def _close_unfilled(self, watcher: dict, path: dict) -> None:
        would = path["outcome"]
        self.same_candle_trades += int(path["same_candle"]["aggTrades"])
        self.same_candle_loss += int(path["same_candle"]["loss_no_trades"])
        self.would_be.append({"would_be": would, "filled": False, "signal_time": watcher["signal_time"]})
        self.not_filled += 1
        self.records.append(
            {
                "symbol": self.symbol,
                "outcome": "NOT_FILLED",
                "would_be": would,
                "counts_for_graduation": False,
                "prediction_direction": watcher["direction"],
                "signal_time": watcher["signal_time"],
                "cost_pct": None,
                "spread_assumed": True,
                "score": watcher["score"],
                "breakeven_wr": watcher.get("breakeven_wr"),
            }
        )
        watcher["record_written"] = True
        watcher["actual_done"] = True
