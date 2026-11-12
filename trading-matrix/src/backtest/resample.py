"""Resample closed 1m candles. A higher-timeframe bar is invisible until it closes."""

from __future__ import annotations

from collections import deque


class ClosedResampler:
    def __init__(self, minutes: int, keep: int = 500):
        self.ms = int(minutes) * 60_000
        self.closed: deque = deque(maxlen=keep)
        self.current: dict | None = None

    def push(self, candle: dict) -> list[dict]:
        ts = int(candle["timestamp"])
        bucket = ts - (ts % self.ms)
        emitted: list[dict] = []
        if self.current is not None and bucket != self.current["timestamp"]:
            if ts >= self.current["timestamp"] + self.ms:
                emitted.append(self.current)
                self.closed.append(self.current)
            self.current = None
        if self.current is None:
            self.current = {
                "timestamp": bucket,
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"]),
                "volume": float(candle.get("volume") or 0.0),
            }
        else:
            self.current["high"] = max(self.current["high"], float(candle["high"]))
            self.current["low"] = min(self.current["low"], float(candle["low"]))
            self.current["close"] = float(candle["close"])
            self.current["volume"] += float(candle.get("volume") or 0.0)
        if self.current is not None and ts + 60_000 >= self.current["timestamp"] + self.ms:
            emitted.append(self.current)
            self.closed.append(self.current)
            self.current = None
        return emitted

    def closes(self) -> list[float]:
        return [float(bar["close"]) for bar in self.closed]


def is_decision_close(open_ts: int, window_ms: int) -> bool:
    """True when this candle's close lands on the window boundary."""
    return (int(open_ts) + 60_000) % int(window_ms) == 0


def closed_resampled(candles: list[dict], bucket_ms: int) -> list[dict]:
    bars = ClosedResampler(max(1, int(bucket_ms) // 60_000), keep=10**9)
    for candle in candles:
        bars.push(candle)
    return list(bars.closed)


def is_decision_close(open_ts: int, window_ms: int) -> bool:
    """True when this 1m candle's close lands on the window boundary."""
    return (int(open_ts) + 60_000) % int(window_ms) == 0


def closed_resampled(candles: list[dict], bucket_ms: int) -> list[dict]:
    """Build higher-timeframe bars from closed 1m candles.

    A bucket is emitted only after its last 1m candle has closed. The
    still-forming bucket is dropped.
    """
    buckets: dict[int, dict] = {}
    order: list[int] = []
    width = int(bucket_ms)
    for candle in candles:
        ts = int(candle["timestamp"])
        bopen = ts - (ts % width)
        bend = bopen + width
        if ts < bopen or ts >= bend:
            continue
        slot = buckets.get(bopen)
        if slot is None:
            slot = {
                "timestamp": bopen,
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"]),
                "volume": float(candle.get("volume") or 0.0),
                "last_open": ts,
                "end": bend,
            }
            buckets[bopen] = slot
            order.append(bopen)
            continue
        slot["high"] = max(slot["high"], float(candle["high"]))
        slot["low"] = min(slot["low"], float(candle["low"]))
        slot["volume"] += float(candle.get("volume") or 0.0)
        if ts >= slot["last_open"]:
            slot["close"] = float(candle["close"])
            slot["last_open"] = ts
    out = []
    for bopen in order:
        slot = buckets[bopen]
        if slot["last_open"] + 60_000 < slot["end"]:
            continue
        out.append(
            {
                "timestamp": slot["timestamp"],
                "open": slot["open"],
                "high": slot["high"],
                "low": slot["low"],
                "close": slot["close"],
                "volume": slot["volume"],
            }
        )
    return out
