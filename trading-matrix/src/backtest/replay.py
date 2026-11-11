"""Causal replay. A candle is usable only after it closes.

A signal from the candle that closes at t is entered at the open of the next
candle. Indicators update only with closed candles. Trend decisions fire on
the live 15-minute cadence.
"""

from __future__ import annotations

from collections import deque

import numpy as np

from config.costs import round_trip_cost
from src.prediction.consensus import build_reduced_consensus
from src.prediction.lens_entropy import run_entropy
from src.prediction.lens_markov import MarkovState, describe_markov
from src.prediction.lens_technical import _bb_signal, _macd_signal, _rsi_signal, combine_signals
from src.prediction.schemas import LensResult
from src.scalp.brackets import PositionBook, resolve_path
from src.scalp.cost_gate import evaluate_cost_gate
from src.scalp.setup_scorer import _wilder_atr
from src.verification.lens_weights import WeightBook
from src.verification.verifier import classify_move, counts_for_graduation, trend_returns, verify_prediction


def candles_visible_at(candles: list[dict], t_ms: int, interval_ms: int = 60_000) -> list[dict]:
    return [c for c in candles if c["timestamp"] + interval_ms <= t_ms]


class _EMA:
    def __init__(self, period: int):
        self.period = period
        self.alpha = 2.0 / (period + 1.0)
        self.n = 0
        self.seed = 0.0
        self.value = None

    def push(self, x: float):
        self.n += 1
        if self.n < self.period:
            self.seed += x
            return None
        if self.n == self.period:
            self.value = (self.seed + x) / self.period
            return self.value
        self.value = self.alpha * x + (1.0 - self.alpha) * self.value
        return self.value


class _RSI:
    def __init__(self, period: int = 14):
        self.period = period
        self.prev = None
        self.buf = []
        self.avg_g = None
        self.avg_l = None
        self.value = None

    def push(self, close: float):
        if self.prev is None:
            self.prev = close
            return None
        delta = close - self.prev
        self.prev = close
        g = delta if delta > 0 else 0.0
        loss = -delta if delta < 0 else 0.0
        if self.avg_g is None:
            self.buf.append((g, loss))
            if len(self.buf) < self.period:
                return None
            self.avg_g = sum(p[0] for p in self.buf) / self.period
            self.avg_l = sum(p[1] for p in self.buf) / self.period
            self.value = self._val()
            return self.value
        a = 1.0 / self.period
        self.avg_g = (1 - a) * self.avg_g + a * g
        self.avg_l = (1 - a) * self.avg_l + a * loss
        self.value = self._val()
        return self.value

    def _val(self) -> float:
        if self.avg_l == 0:
            return 100.0 if self.avg_g > 0 else 50.0
        rs = self.avg_g / self.avg_l
        return 100.0 - 100.0 / (1.0 + rs)


class _MACD:
    def __init__(self):
        self.fast = _EMA(12)
        self.slow = _EMA(26)
        self.signal = _EMA(9)
        self.hist_hist = deque(maxlen=50)

    def push(self, close: float):
        a = self.fast.push(close)
        b = self.slow.push(close)
        if a is None or b is None:
            return None
        macd = a - b
        sig = self.signal.push(macd)
        if sig is None:
            return None
        hist = macd - sig
        self.hist_hist.append(hist)
        return hist

    def direction(self):
        if not self.hist_hist:
            return "SIDEWAYS", 0.0
        hist = np.array(self.hist_hist, dtype=float)
        # _macd_signal expects a full series and an index. Feed the deque as the series.
        return _macd_signal(hist, len(hist) - 1)


class _Bollinger:
    def __init__(self, period: int = 20):
        self.period = period
        self.buf = deque(maxlen=period)

    def push(self, close: float):
        self.buf.append(close)

    def signal(self, price: float):
        if len(self.buf) < self.period:
            return "SIDEWAYS", 0.0
        arr = np.asarray(self.buf, dtype=float)
        mid = float(arr.mean())
        std = float(arr.std())
        return _bb_signal(price, mid, mid + 2 * std, mid - 2 * std)


def _day(ts_ms: int) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ts_ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def _stamp(ts_ms: int) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ts_ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


class TrendReplay:
    """Push closed 1m candles. Retains only a short deque plus indicator state."""

    def __init__(
        self,
        symbol: str,
        asset_class: str,
        venue: str,
        fee_mode: str,
        spread_pct: float,
        spread_assumed: bool,
        cost_multiplier: float = 1.0,
        interval_ms: int = 15 * 60_000,
        window_ms: int = 15 * 60_000,
        weight_every: int = 100,
        funding: list[tuple[int, float]] | None = None,
        funding_ignored_default: bool = False,
        rule_version: int = 1,
        track: str = "CRYPTO",
    ):
        self.symbol = symbol
        self.asset_class = asset_class
        self.venue = venue
        self.track = track
        self.spread_assumed = spread_assumed
        self.funding = funding or []
        self.funding_ignored_default = funding_ignored_default
        self.rule_version = rule_version
        self.interval_ms = interval_ms
        self.window_ms = window_ms
        self.cost = round_trip_cost(asset_class, venue, fee_mode, spread_pct) * cost_multiplier
        self.base_cost = round_trip_cost(asset_class, venue, fee_mode, spread_pct)
        self.rsi = _RSI(14)
        self.macd = _MACD()
        self.bb = _Bollinger(20)
        self.markov = MarkovState(window=20)
        self.entropy_closes = deque(maxlen=80)
        self.weights = WeightBook(["markov", "technical"], every=weight_every)
        self.pending = None
        self.open_trades: list[dict] = []
        self.records: list[dict] = []
        self.slots: list[dict] = []
        self.gap_missing = 0
        self.gap_examples: list[int] = []
        self.expected_ts = None
        self.retained = 0
        self.last_move = 0
        self._last_weights_snapshot = None

    def push(self, candle: dict) -> None:
        ts = int(candle["timestamp"])
        if self.expected_ts is not None and ts != self.expected_ts:
            if ts > self.expected_ts:
                missed = (ts - self.expected_ts) // 60_000
                self.gap_missing += int(missed)
                if len(self.gap_examples) < 20:
                    self.gap_examples.append(int(self.expected_ts))
            self.pending = None
            # A trade whose verify candle fell inside the hole cannot be scored.
            self.open_trades = [t for t in self.open_trades if t["verify_time"] >= ts + 60_000]
        self.expected_ts = ts + 60_000

        if self.pending is not None:
            if ts == self.pending["signal_time"]:
                self.pending["price_at_prediction"] = float(candle["open"])
                self.pending["entry_open"] = float(candle["open"])
                self.pending["entry_close"] = float(candle["close"])
                self.pending["entry_time"] = ts
                self.pending["verify_time"] = ts + self.window_ms
                self.open_trades.append(self.pending)
            self.pending = None

        close = float(candle["close"])
        self.rsi.push(close)
        self.macd.push(close)
        self.bb.push(close)
        self.markov.push(close)
        self.entropy_closes.append(close)
        self.retained = len(self.entropy_closes)

        close_time = ts + 60_000
        still = []
        for trade in self.open_trades:
            if close_time == trade["verify_time"]:
                self._finalize(trade, close)
            elif close_time < trade["verify_time"]:
                still.append(trade)
        self.open_trades = still

        if self._is_decision(ts) and self._ready():
            self.pending = self._signal(candle, close_time)

    def _is_decision(self, open_ts: int) -> bool:
        return (open_ts + 60_000) % self.interval_ms == 0

    def _ready(self) -> bool:
        return self.rsi.value is not None and self.macd.hist_hist and self.markov.label >= 0 and len(self.entropy_closes) >= 30

    def _signal(self, candle: dict, close_time: int) -> dict:
        rsi_d, rsi_c = _rsi_signal(float(self.rsi.value))
        macd_d, macd_c = self.macd.direction()
        bb_d, bb_c = self.bb.signal(float(candle["close"]))
        tech_d, tech_c = combine_signals([(rsi_d, rsi_c), (macd_d, macd_c), (bb_d, bb_c)])
        tech = LensResult(
            "technical",
            tech_d,
            tech_c,
            f"RSI={self.rsi.value:.2f} verdict {rsi_d}; MACD verdict {macd_d}; Bollinger verdict {bb_d}",
            {"rsi": float(self.rsi.value), "rsi_direction": rsi_d, "macd_direction": macd_d, "bb_direction": bb_d},
        )
        direction, conf, reasoning, raw = describe_markov(self.markov.matrix(), int(self.markov.label))
        mark = LensResult("markov", direction, conf, reasoning, raw)
        entropy = run_entropy(list(self.entropy_closes))
        decision = build_reduced_consensus([mark, tech], entropy)
        return {
            "symbol": self.symbol,
            "asset_class": self.asset_class,
            "track": self.track,
            "timeframe": "15m",
            "signal_time": close_time,
            "signal_close": float(candle["close"]),
            "prediction_direction": decision["prediction_direction"],
            "consensus_confidence": decision["consensus_confidence"],
            "reasoning": decision["reasoning"],
            "lenses": decision["lenses"],
            "tech_direction": tech_d,
            "markov_direction": direction,
            "entropy_regime": entropy.raw_data.get("regime"),
            "entropy_score": entropy.raw_data.get("entropy_score"),
            "weights": self.weights.for_class(self.asset_class),
            "rule_version": self.rule_version,
            "spread_assumed": self.spread_assumed,
            "cost_pct": self.cost,
        }

    def _funding(self, direction: str, entry_ts: int, exit_ts: int) -> tuple[float, bool]:
        if not self.funding:
            return 0.0, self.funding_ignored_default
        sign = 1.0 if direction == "UP" else -1.0 if direction == "DOWN" else 0.0
        paid = 0.0
        for ts, rate in self.funding:
            if entry_ts < ts <= exit_ts:
                paid += sign * rate
        return paid, False

    def _finalize(self, trade: dict, verify_price: float) -> None:
        direction = trade["prediction_direction"]
        entry = float(trade["price_at_prediction"])
        checked = verify_prediction(direction, entry, verify_price)
        funding, funding_ignored = self._funding(direction, trade["entry_time"], trade["verify_time"])
        returns = trend_returns(direction, entry, verify_price, trade["cost_pct"])
        net = returns["net_return_pct"] - funding
        move = 1 if verify_price > entry else -1 if verify_price < entry else 0
        counted = counts_for_graduation(direction, True, False, trade["cost_pct"])
        record = {
            **trade,
            "outcome": checked["outcome"],
            "price_at_verification": verify_price,
            "was_correct": checked["was_correct"],
            "verified_at": _stamp(trade["verify_time"]),
            "gross_return_pct": returns["gross_return_pct"],
            "net_return_pct": net,
            "hit": bool(returns["hit"]),
            "move": move,
            "prev_move": self.last_move,
            "counts_for_graduation": counted,
            "blackout": False,
            "funding_paid": funding,
            "funding_ignored": funding_ignored,
            "day": _day(trade["signal_time"]),
            "setup_class": None,
            "data_trust": {"tag": "NO DATA", "reason": "backtest trust tag needs aggTrades calibration; not faked"},
        }
        self.records.append(record)
        self.slots.append(
            {
                "entry": entry,
                "entry_close": float(trade.get("entry_close", entry)),
                "verify": verify_price,
                "cost": self.base_cost,
                "day": record["day"],
                "signal_time": trade["signal_time"],
                "split": trade.get("split"),
            }
        )
        self.last_move = move
        if checked["was_correct"] is not None:
            actual = checked["outcome"]
            self.weights.observe(
                self.asset_class,
                {
                    "markov": trade["markov_direction"] == actual,
                    "technical": trade["tech_direction"] == actual,
                },
            )
        self._last_weights_snapshot = self.weights.snapshot()

    def snapshot_weights(self):
        return self.weights.snapshot()


def replay_candles(candles: list[dict], **kwargs) -> TrendReplay:
    engine = TrendReplay(**kwargs)
    for candle in candles:
        engine.push(candle)
    return engine


def scalp_gate_scan(
    candles: list[dict],
    *,
    venue: str,
    fee_mode: str,
    spread_pct: float,
    asset_class: str,
    cost_multiplier: float = 1.0,
    count_from: int | None = None,
    count_to: int | None = None,
) -> dict:
    """Count cost-gate blocks. Triggers need order flow, which needs a book.

    The public archive has no monthly bookTicker (the spot path 404s), so the
    order-flow lens stays silent and no setup is triggered. Passed-gate bars
    are reported, not invented into trades.
    """
    if len(candles) < 30:
        return {"bars": len(candles), "blocked": 0, "passed": 0, "triggered": 0, "by_class": {}}
    high = np.array([c["high"] for c in candles], dtype=float)
    low = np.array([c["low"] for c in candles], dtype=float)
    close = np.array([c["close"] for c in candles], dtype=float)
    atr = _wilder_atr(high, low, close, 8)
    counts = {
        "QUICK": {"blocked": 0, "passed": 0, "dead": 0, "target": 0, "breakeven": 0},
        "EXTENDED": {"blocked": 0, "passed": 0, "dead": 0, "target": 0, "breakeven": 0},
    }
    timestamps = np.array([c["timestamp"] for c in candles])
    atr5 = _atr5(high, low, close, timestamps)
    for i in range(20, len(candles)):
        ts = int(timestamps[i])
        if count_from is not None and ts < count_from:
            continue
        if count_to is not None and ts >= count_to:
            continue
        if np.isnan(atr[i]):
            continue
        window = atr[max(0, i - 9) : i + 1]
        avg = float(np.mean(window))
        for cls, this_atr in (("QUICK", float(atr[i])), ("EXTENDED", float(atr5[i]) if not np.isnan(atr5[i]) else float("nan"))):
            if np.isnan(this_atr) or this_atr <= 0:
                continue
            gate = evaluate_cost_gate(
                float(close[i]),
                this_atr,
                avg if cls == "QUICK" else this_atr,
                venue=venue,
                fee_mode=fee_mode,
                spread_pct=spread_pct,
                asset_class=asset_class,
                cost_multiplier=cost_multiplier,
            )
            if gate["blocked"]:
                counts[cls]["blocked"] += 1
                if "dead market" in gate["reasons"]:
                    counts[cls]["dead"] += 1
                if "target too small for costs" in gate["reasons"]:
                    counts[cls]["target"] += 1
                if "needs >50% wins to break even" in gate["reasons"]:
                    counts[cls]["breakeven"] += 1
            else:
                counts[cls]["passed"] += 1
    blocked = counts["QUICK"]["blocked"] + counts["EXTENDED"]["blocked"]
    passed = counts["QUICK"]["passed"] + counts["EXTENDED"]["passed"]
    return {"bars": len(candles), "blocked": blocked, "passed": passed, "triggered": 0, "by_class": counts}


def _atr5(high, low, close, timestamps) -> np.ndarray:
    n = len(close)
    out = np.full(n, np.nan)
    bars = []
    i = 0
    while i + 5 <= n:
        ts = timestamps[i : i + 5]
        if all(int(ts[j + 1]) - int(ts[j]) == 60_000 for j in range(4)):
            bars.append((i + 4, float(np.max(high[i : i + 5])), float(np.min(low[i : i + 5])), float(close[i + 4])))
            i += 5
        else:
            i += 1
    if len(bars) < 10:
        return out
    bh = np.array([b[1] for b in bars])
    bl = np.array([b[2] for b in bars])
    bc = np.array([b[3] for b in bars])
    atr = _wilder_atr(bh, bl, bc, 8)
    last = np.nan
    bi = 0
    for idx in range(n):
        while bi < len(bars) and bars[bi][0] <= idx:
            if not np.isnan(atr[bi]):
                last = atr[bi]
            bi += 1
        out[idx] = last
    return out


def position_smoke(events: list[tuple[str, str, int, int]]) -> list[bool]:
    """Test helper: (symbol, cls, open_index, exit_index) accepted or not."""
    book = PositionBook()
    accepted = []
    for symbol, cls, open_i, exit_i in events:
        ok = book.can_open(symbol, cls, open_i)
        accepted.append(ok)
        if ok:
            book.open(symbol, cls, exit_i)
    return accepted
