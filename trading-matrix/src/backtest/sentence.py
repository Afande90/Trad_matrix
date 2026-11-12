"""Complete-sentence scalp roles. One empty role means there is no trade.

The governor is the last closed 15m EMA state. The doer is the last three
closed 1m aggTrade bars. The target is the previous UTC day. Nothing here
reads a candle that is still open.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.backtest.resample import ClosedResampler
from src.scalp.cost_gate import evaluate_cost_gate
from src.scalp.profile import build_profile
from config.costs import assumed_spread_pct


def governor(ema20: float | None, ema50: float | None, close: float | None) -> str | None:
    if ema20 is None or ema50 is None or close is None:
        return None
    if ema20 > ema50 and close > ema50:
        return "UP"
    if ema20 < ema50 and close < ema50:
        return "DOWN"
    return None


def doer(buy: float, sell: float) -> str | None:
    total = float(buy) + float(sell)
    if total <= 0:
        return None
    share = float(buy) / total
    if share >= 0.60:
        return "BUYERS"
    if share <= 0.40:
        return "SELLERS"
    return None


def day_poc(trades: list[tuple[float, float]], atr: float | None) -> float | None:
    if atr is None or atr <= 0 or not trades:
        return None
    profile = build_profile([(float(price), float(qty)) for price, qty in trades], float(atr))
    if not profile:
        return None
    return float(profile["poc"])


def target_near(close: float, atr: float | None, levels: list[float]) -> bool:
    if atr is None or atr <= 0 or not levels:
        return False
    span = 0.25 * float(atr)
    return any(abs(float(close) - float(level)) <= span for level in levels)


def exception_veto(bar_range: float, atr: float | None) -> bool:
    """True when the wide-bar exception empties the setup."""
    if atr is None or atr <= 0:
        return True
    return float(bar_range) > 3.0 * float(atr)


def state_passes(*, gate_blocked: bool, dead: bool) -> bool:
    return not gate_blocked and not dead


def trade_side(roles: dict, variant: str, disabled: set[int] | None = None) -> str | None:
    """WITH follows the governor. AGAINST fades it. The doer must match the trade.

    Switching a role off drops that requirement. With the governor off, the
    only remaining side is the doer's side. Role 4, the cost gate, is never
    switched off.
    """
    skipped = set(disabled or ())
    if 3 not in skipped and not roles.get("target"):
        return None
    if not roles.get("state"):
        return None
    if 5 not in skipped and roles.get("wide"):
        return None
    flow = roles.get("doer")
    if 1 not in skipped:
        bias = roles.get("governor")
        if bias not in ("UP", "DOWN"):
            return None
        side = bias if variant == "WITH" else ("DOWN" if bias == "UP" else "UP")
    else:
        if flow == "BUYERS":
            side = "UP"
        elif flow == "SELLERS":
            side = "DOWN"
        else:
            return None
    if 2 not in skipped:
        if side == "UP" and flow != "BUYERS":
            return None
        if side == "DOWN" and flow != "SELLERS":
            return None
    return side


def choose_variant(with_row: dict, against_row: dict) -> str:
    """Higher train net mean. Both samples under 300 calls keep WITH."""
    if int(with_row.get("counted") or 0) < 300 and int(against_row.get("counted") or 0) < 300:
        return "WITH"
    with_net = with_row.get("net_mean")
    against_net = against_row.get("net_mean")
    if against_net is None:
        return "WITH"
    if with_net is None:
        return "AGAINST"
    if float(against_net) > float(with_net):
        return "AGAINST"
    return "WITH"


def cumulative_net_drawdown(nets: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for net in nets:
        equity += float(net)
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


class _EMA:
    def __init__(self, period: int):
        self.period = int(period)
        self.alpha = 2.0 / (self.period + 1.0)
        self.seed: list[float] = []
        self.value: float | None = None

    def push(self, price: float) -> float | None:
        if self.value is None:
            self.seed.append(float(price))
            if len(self.seed) == self.period:
                self.value = sum(self.seed) / self.period
            return self.value
        self.value = self.alpha * float(price) + (1.0 - self.alpha) * self.value
        return self.value


class _Wilder:
    def __init__(self, period: int = 8):
        self.period = int(period)
        self.alpha = 1.0 / self.period
        self.trs: list[float] = []
        self.prev: float | None = None
        self.value: float | None = None

    def push(self, high: float, low: float, close: float) -> float | None:
        if self.prev is None:
            tr = float(high) - float(low)
        else:
            tr = max(float(high) - float(low), abs(float(high) - self.prev), abs(float(low) - self.prev))
        self.prev = float(close)
        self.trs.append(tr)
        if self.value is None:
            if len(self.trs) == self.period + 1:
                self.value = sum(self.trs[1 : self.period + 1]) / self.period
            return self.value
        self.value = (1.0 - self.alpha) * self.value + self.alpha * tr
        return self.value


def _day(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000, timezone.utc).strftime("%Y-%m-%d")


class SentenceBook:
    """Streaming roles. push() is called once per closed 1m candle."""

    def __init__(self, spread: float | None = None):
        self.spread = assumed_spread_pct() if spread is None else float(spread)
        self.m15 = ClosedResampler(15, keep=4)
        self.m5 = ClosedResampler(5, keep=4)
        self.ema20 = _EMA(20)
        self.ema50 = _EMA(50)
        self.atr1 = _Wilder(8)
        self.atr5 = _Wilder(8)
        self.atr1_window: list[float] = []
        self.atr5_now: float | None = None
        self.governor_side: str | None = None
        self.flow: list[tuple[float, float]] = []
        self.day: str | None = None
        self.day_high: float | None = None
        self.day_low: float | None = None
        self.day_bins: dict[float, float] = {}
        self.day_atr: float | None = None
        self.prev_high: float | None = None
        self.prev_low: float | None = None
        self.prev_poc: float | None = None

    def _freeze_day(self) -> None:
        trades = [(price, qty) for price, qty in self.day_bins.items() if qty > 0]
        self.prev_high = self.day_high
        self.prev_low = self.day_low
        self.prev_poc = day_poc(trades, self.day_atr)
        self.day_high = None
        self.day_low = None
        self.day_bins = {}
        self.day_atr = None

    def push(self, candle: dict, buy: float, sell: float, trades: list[tuple[float, float]] | None = None) -> dict:
        ts = int(candle["timestamp"])
        day = _day(ts)
        if self.day is None:
            self.day = day
        elif day != self.day:
            self._freeze_day()
            self.day = day
        high = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])
        self.day_high = high if self.day_high is None else max(self.day_high, high)
        self.day_low = low if self.day_low is None else min(self.day_low, low)
        for price, qty in trades or []:
            self.day_bins[float(price)] = self.day_bins.get(float(price), 0.0) + float(qty)
        atr1 = self.atr1.push(high, low, close)
        if atr1 is not None:
            self.atr1_window.append(float(atr1))
            if len(self.atr1_window) > 10:
                self.atr1_window.pop(0)
        for bar in self.m5.push(candle):
            updated = self.atr5.push(float(bar["high"]), float(bar["low"]), float(bar["close"]))
            if updated is not None:
                self.atr5_now = float(updated)
        if self.atr5_now is not None:
            self.day_atr = self.atr5_now
        for bar in self.m15.push(candle):
            ema20 = self.ema20.push(float(bar["close"]))
            ema50 = self.ema50.push(float(bar["close"]))
            self.governor_side = governor(ema20, ema50, float(bar["close"]))
        self.flow.append((float(buy), float(sell)))
        if len(self.flow) > 3:
            self.flow.pop(0)
        bought = sum(item[0] for item in self.flow)
        sold = sum(item[1] for item in self.flow)
        levels = [level for level in (self.prev_high, self.prev_low, self.prev_poc) if level is not None]
        atr5 = self.atr5_now
        gate = None
        gate_blocked = True
        if atr5 is not None and atr5 > 0 and close > 0:
            gate = evaluate_cost_gate(
                close,
                atr5,
                atr5,
                venue="futures",
                fee_mode="maker",
                spread_pct=self.spread,
                asset_class="CRYPTO",
            )
            gate_blocked = bool(gate["blocked"])
        dead = True
        if atr1 is not None and len(self.atr1_window) >= 10:
            avg = sum(self.atr1_window) / len(self.atr1_window)
            dead = avg <= 0 or (float(atr1) / avg) < 0.6
        roles = {
            "timestamp": ts,
            "close": close,
            "governor": self.governor_side,
            "doer": doer(bought, sold),
            "target": target_near(close, atr5, levels),
            "state": state_passes(gate_blocked=gate_blocked, dead=dead),
            "wide": exception_veto(high - low, atr1),
            "reward_pct": None if gate is None else float(gate["reward_pct"]),
            "risk_pct": None if gate is None else float(gate["risk_pct"]),
            "breakeven_wr": None if gate is None else float(gate["breakeven_wr"]),
            "gate_blocked": gate_blocked,
            "dead": dead,
        }
        roles["side_with"] = trade_side(roles, "WITH")
        roles["side_against"] = trade_side(roles, "AGAINST")
        return roles


def sentence_signals(candles: list[dict], flows: list[tuple], variant: str) -> list[tuple[int, str]]:
    book = SentenceBook()
    out = []
    for candle, flow in zip(candles, flows):
        buy, sell, trades = flow
        roles = book.push(candle, buy, sell, trades)
        side = trade_side(roles, variant)
        if side:
            out.append((int(candle["timestamp"]) + 60_000, side))
    return out
