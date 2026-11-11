"""Single-voter trend replay. Markov or technical, never both.

The lens sees the last `lookback` closed resampled candles. Entry is the next
1m open. Exit is the close of the 1m candle that closes one window later.
Funding is applied to the track net and is not part of the window oracle.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone

from src.backtest.resample import closed_resampled, is_decision_close
from src.prediction.lens_markov import run_markov
from src.prediction.lens_technical import run_technical
from src.verification.verifier import counts_for_graduation, direction_sign, trend_returns


def _day(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, timezone.utc).strftime("%Y-%m-%d")


class VoterReplay:
    def __init__(
        self,
        *,
        voter: str,
        window_ms: int,
        bucket_ms: int,
        lookback: int,
        cost: float,
        symbol: str,
        track: str,
        label: str,
        funding: list[tuple[int, float]] | None = None,
        spread_assumed: bool = True,
    ):
        self.voter = voter
        self.window_ms = int(window_ms)
        self.bucket_ms = int(bucket_ms)
        self.lookback = int(lookback)
        self.cost = float(cost)
        self.symbol = symbol
        self.track = track
        self.label = label
        self.funding = list(funding or [])
        self.spread_assumed = spread_assumed
        cap = self.lookback * max(1, self.bucket_ms // 60_000) + 5
        self.buf: deque = deque(maxlen=cap)
        self.pending: dict | None = None
        self.open_trade: dict | None = None
        self.records: list[dict] = []
        self.slots: list[dict] = []
        self.gap_missing = 0
        self.expected: int | None = None
        self.last_move = 0

    def push(self, candle: dict) -> None:
        ts = int(candle["timestamp"])
        if self.expected is not None and ts > self.expected:
            self.gap_missing += (ts - self.expected) // 60_000
            self.pending = None
            if self.open_trade is not None and self.open_trade["verify_time"] < ts + 60_000:
                self.open_trade = None
        self.expected = ts + 60_000

        if self.pending is not None and ts == self.pending["signal_time"]:
            self.pending["price_at_prediction"] = float(candle["open"])
            self.pending["entry_open"] = float(candle["open"])
            self.pending["entry_close"] = float(candle["close"])
            self.pending["entry_time"] = ts
            self.pending["verify_time"] = ts + self.window_ms
            self.open_trade = self.pending
            self.pending = None
        elif self.pending is not None and ts > self.pending["signal_time"]:
            self.pending = None

        close_time = ts + 60_000
        if self.open_trade is not None and close_time == self.open_trade["verify_time"]:
            self._finalize(self.open_trade, float(candle["close"]))
            self.open_trade = None
        elif self.open_trade is not None and close_time > self.open_trade["verify_time"]:
            self.open_trade = None

        self.buf.append(candle)
        if not is_decision_close(ts, self.window_ms):
            return
        if self.open_trade is not None or self.pending is not None:
            return
        bars = closed_resampled(list(self.buf), self.bucket_ms)
        if len(bars) < self.lookback:
            return
        closes = [float(bar["close"]) for bar in bars[-self.lookback :]]
        lens = run_markov(closes, window=20) if self.voter == "markov" else run_technical(closes)
        direction = lens.direction
        record_base = {
            "symbol": self.symbol,
            "track": self.track,
            "label": self.label,
            "voter": self.voter,
            "timeframe": f"{self.window_ms // 60_000}m",
            "signal_time": close_time,
            "signal_close": float(candle["close"]),
            "prediction_direction": direction,
            "consensus_confidence": float(lens.confidence),
            "cost_pct": self.cost,
            "spread_assumed": self.spread_assumed,
            "rule_version": 2,
            "asset_class": "CRYPTO",
        }
        if direction not in ("UP", "DOWN"):
            self.records.append(
                {
                    **record_base,
                    "verify_time": close_time,
                    "counts_for_graduation": False,
                    "price_at_prediction": None,
                    "gross_return_pct": None,
                    "net_return_pct": None,
                    "hit": False,
                    "funding_paid": 0.0,
                    "funding_ignored": not self.funding,
                }
            )
            return
        self.pending = record_base

    def _funding(self, direction: str, entry_ts: int, exit_ts: int) -> float:
        sign = direction_sign(direction)
        paid = 0.0
        for ts, rate in self.funding:
            if entry_ts < ts <= exit_ts:
                paid += sign * float(rate)
        return paid

    def _finalize(self, trade: dict, verify_price: float) -> None:
        direction = trade["prediction_direction"]
        entry = float(trade["price_at_prediction"])
        returns = trend_returns(direction, entry, verify_price, trade["cost_pct"])
        paid = self._funding(direction, int(trade["entry_time"]), int(trade["verify_time"]))
        move = 1 if verify_price > entry else -1 if verify_price < entry else 0
        counted = counts_for_graduation(direction, True, False, trade["cost_pct"])
        record = {
            **trade,
            "price_at_verification": verify_price,
            "gross_return_pct": returns["gross_return_pct"],
            "net_return_pct": returns["net_return_pct"] - paid,
            "hit": bool(returns["hit"]),
            "funding_paid": paid,
            "funding_ignored": False if self.funding else True,
            "move": move,
            "prev_move": self.last_move,
            "day": _day(int(trade["signal_time"])),
            "counts_for_graduation": counted,
            "outcome": direction if counted else direction,
        }
        self.records.append(record)
        self.slots.append(
            {
                "entry": entry,
                "entry_close": float(trade.get("entry_close", entry)),
                "verify": verify_price,
                "cost": self.cost,
                "signal_time": trade["signal_time"],
            }
        )
        self.last_move = move


def truncation_voter(candles: list[dict], **kwargs) -> bool:
    if len(candles) < 40:
        return False
    cut = int(len(candles) * 0.6)
    t_ms = candles[cut]["timestamp"] + 60_000
    later = min(len(candles) - 1, cut + 1440)
    t2 = candles[later]["timestamp"] + 60_000

    def done(rows, limit):
        out = []
        for record in rows:
            verify = int(record.get("verify_time") or 0)
            if int(record["signal_time"]) < limit and verify <= limit:
                price = record.get("price_at_prediction")
                out.append(
                    (
                        int(record["signal_time"]),
                        record["prediction_direction"],
                        None if price is None else round(float(price), 8),
                        record.get("outcome"),
                    )
                )
        return out

    def replay(limit):
        engine = VoterReplay(**kwargs, symbol="BTCUSDT", track="T", label="T")
        for candle in candles:
            if int(candle["timestamp"]) + 60_000 <= limit:
                engine.push(candle)
        return engine.records

    return done(replay(t_ms), t_ms) == done(replay(t2), t_ms)
