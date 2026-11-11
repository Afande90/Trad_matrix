"""Rule set 2. One voter on a closed higher-timeframe bar, and maker extended scalps.

A window oracle is the true direction of that whole window. If its net is not
above zero, the track is not run.
"""

from __future__ import annotations

from src.backtest.oracle import window_oracle
from src.backtest.replay import _atr5
from src.backtest.resample import ClosedResampler
from src.prediction.lens_markov import run_markov
from src.prediction.lens_technical import run_technical
from src.prediction.schemas import LensResult
from src.scalp.brackets import bracket_prices, resolve_path
from src.scalp.cost_gate import evaluate_cost_gate
from src.scalp.orderflow import delta_only_lens
from src.scalp.trigger import should_trigger
from src.verification.verifier import direction_sign, scalp_net, trend_returns
from config.costs import assumed_spread_pct, scalp_outcome_cost


TREND_SPECS = (
    ("T1", "T1 MOMENTUM 1h", "markov", 60, 5),
    ("T2", "T2 MOMENTUM 4h", "markov", 240, 15),
    ("T3", "T3 REVERSION 1h", "technical", 60, 5),
    ("T4", "T4 REVERSION 4h", "technical", 240, 15),
)


def _vote(voter: str, closes: list[float]) -> tuple[str, float]:
    result = run_markov(closes) if voter == "markov" else run_technical(closes)
    return result.direction, float(result.confidence)


def _funding(direction: str, entry_ts: int, exit_ts: int, schedule: list[tuple[int, float]]) -> float:
    sign = direction_sign(direction)
    paid = 0.0
    for ts, rate in schedule:
        if entry_ts < ts <= exit_ts:
            paid += sign * rate
    return paid


def replay_trend(candles: list[dict], *, lookback: int = 500, cost: float, funding: list[tuple[int, float]] | None = None) -> dict:
    """Walk closed 1m candles once. Four trend tracks share the pass."""
    funding = list(funding or [])
    resamplers = {
        5: ClosedResampler(5, keep=lookback),
        15: ClosedResampler(15, keep=lookback),
    }
    records: dict[str, list[dict]] = {spec[0]: [] for spec in TREND_SPECS}
    pending_trade: dict[str, dict | None] = {spec[0]: None for spec in TREND_SPECS}
    open_trades: dict[str, dict | None] = {spec[0]: None for spec in TREND_SPECS}
    oracle_pending: dict[int, dict | None] = {60: None, 240: None}
    oracle_done: dict[int, list[tuple[float, float]]] = {60: [], 240: []}
    last_move = {spec[0]: 0 for spec in TREND_SPECS}

    def _finish_oracle(window_min: int, exit_px: float) -> None:
        slot = oracle_pending[window_min]
        if slot is None or slot.get("entry") is None:
            oracle_pending[window_min] = None
            return
        oracle_done[window_min].append((float(slot["entry"]), float(exit_px)))
        oracle_pending[window_min] = None

    def _finalize(spec_id: str, exit_px: float) -> None:
        trade = open_trades[spec_id]
        open_trades[spec_id] = None
        if trade is None:
            return
        direction = trade["prediction_direction"]
        entry = float(trade["price_at_prediction"])
        returns = trend_returns(direction, entry, exit_px, cost)
        paid = _funding(direction, trade["entry_time"], trade["verify_time"], funding)
        move = 1 if exit_px > entry else -1 if exit_px < entry else 0
        counted = direction in ("UP", "DOWN")
        records[spec_id].append(
            {
                **trade,
                "price_at_verification": exit_px,
                "gross_return_pct": returns["gross_return_pct"],
                "net_return_pct": returns["net_return_pct"] - paid,
                "hit": bool(returns["hit"]),
                "funding_paid": paid,
                "move": move,
                "prev_move": last_move[spec_id],
                "day": _day(int(trade["signal_time"])),
                "counts_for_graduation": counted,
                "cost_pct": cost,
                "spread_assumed": True,
            }
        )
        if counted:
            last_move[spec_id] = move

    for index, candle in enumerate(candles):
        ts = int(candle["timestamp"])
        close_time = ts + 60_000
        for window_min, slot in list(oracle_pending.items()):
            if slot is None:
                continue
            if slot.get("entry") is None and ts == slot["signal_time"]:
                slot["entry"] = float(candle["open"])
            if slot.get("entry") is not None and close_time == slot["exit_time"]:
                _finish_oracle(window_min, float(candle["close"]))
            elif close_time > slot["exit_time"]:
                oracle_pending[window_min] = None
        for spec in TREND_SPECS:
            spec_id = spec[0]
            waiting = pending_trade[spec_id]
            if waiting is not None and ts == waiting["signal_time"]:
                waiting["entry_time"] = ts
                waiting["entry_open"] = float(candle["open"])
                waiting["price_at_prediction"] = float(candle["open"])
                waiting["verify_time"] = ts + spec[3] * 60_000
                open_trades[spec_id] = waiting
                pending_trade[spec_id] = None
            elif waiting is not None and ts > waiting["signal_time"]:
                pending_trade[spec_id] = None
            live = open_trades[spec_id]
            if live is not None and close_time == live["verify_time"]:
                _finalize(spec_id, float(candle["close"]))
            elif live is not None and close_time > live["verify_time"]:
                open_trades[spec_id] = None
        for minutes, sampler in resamplers.items():
            sampler.push(candle)
        for spec in TREND_SPECS:
            spec_id, _label, voter, window_min, bar_min = spec
            if close_time % (window_min * 60_000) != 0:
                continue
            closes = resamplers[bar_min].closes()
            if len(closes) < lookback:
                continue
            direction, conf = _vote(voter, closes[-lookback:])
            if oracle_pending[window_min] is None:
                oracle_pending[window_min] = {"signal_time": close_time, "entry": None, "exit_time": close_time + window_min * 60_000}
            if direction not in ("UP", "DOWN"):
                records[spec_id].append(
                    {
                        "signal_time": close_time,
                        "signal_close": float(candle["close"]),
                        "prediction_direction": direction,
                        "consensus_confidence": conf,
                        "voter": voter,
                        "verify_time": close_time,
                        "counts_for_graduation": False,
                        "price_at_prediction": None,
                        "spread_assumed": True,
                        "cost_pct": cost,
                    }
                )
                continue
            if pending_trade[spec_id] is None and open_trades[spec_id] is None:
                pending_trade[spec_id] = {
                    "signal_time": close_time,
                    "signal_close": float(candle["close"]),
                    "prediction_direction": direction,
                    "consensus_confidence": conf,
                    "voter": voter,
                    "track": spec_id,
                }

    tracks = {}
    for spec in TREND_SPECS:
        spec_id, label, _voter, window_min, _bar = spec
        pairs = oracle_done[window_min]
        ceiling = window_oracle([p[0] for p in pairs], [p[1] for p in pairs], cost)
        ran = ceiling["net_mean"] is not None and ceiling["net_mean"] > 0
        tracks[spec_id] = {
            "id": spec_id,
            "label": label,
            "window_min": window_min,
            "ceiling": ceiling,
            "ran": ran,
            "records": records[spec_id] if ran else [],
            "verdict": None if ran else "STOP as built",
        }
    return {"tracks": tracks, "oracle": oracle_done}


def _prices(minute_trades) -> list[float]:
    out = []
    for item in minute_trades or []:
        out.append(float(item[1] if len(item) >= 2 else item[0]))
    return out


def _through(side: str, setup: float, prices: list[float], tick: float) -> bool:
    for price in prices:
        if side == "UP" and price <= setup - tick:
            return True
        if side == "DOWN" and price >= setup + tick:
            return True
    return False


def score_last_bar(candles: list[dict]) -> tuple[str, float]:
    """Same formula as the last row of score_both, without rescoring the whole window."""
    from src.scalp.setup_scorer import prepare, smoothed_score

    if len(candles) <= 21:
        return "SIDEWAYS", 0.0
    prep = prepare(candles)
    i = len(candles) - 1
    buy = smoothed_score(prep, i, "UP")
    sell = smoothed_score(prep, i, "DOWN")
    if buy["score"] >= sell["score"]:
        return "UP", float(buy["score"])
    return "DOWN", float(sell["score"])


def replay_extended(
    candles: list[dict],
    trades_by_minute: dict | None = None,
    *,
    tick: float,
    score_fn=None,
    ensemble_fn=None,
    delta_fn=None,
    spread: float | None = None,
    asset_class: str = "CRYPTO",
    venue: str = "futures",
    max_hold: int = 60,
    book=None,
    funding: list[tuple[int, float]] | None = None,
) -> dict:
    """EXTENDED maker scalp. One position. S2 or S5 may confirm S1."""
    spread = assumed_spread_pct() if spread is None else float(spread)
    trades_by_minute = trades_by_minute or {}
    funding = list(funding or [])
    delta_fn = delta_fn or (lambda rows: delta_only_lens([(float(r[2]), bool(r[3])) for r in rows]))

    def _price_rows(ts: int):
        if book is not None:
            return book.price_rows(int(ts))
        return trades_by_minute.get(int(ts), [])

    def _delta_rows(ts: int):
        if book is not None:
            return book.delta_rows(int(ts))
        return trades_by_minute.get(int(ts), [])
    high = [float(c["high"]) for c in candles]
    low = [float(c["low"]) for c in candles]
    close = [float(c["close"]) for c in candles]
    atr = _atr5(high, low, close, [c["timestamp"] for c in candles])
    records = []
    skipped = 0
    blocked = 0
    passed = 0
    same_candle = {"aggTrades": 0, "loss_no_trades": 0}
    busy_until = -1
    last_move = 0
    fill_groups = {"WIN": [0, 0], "LOSS": [0, 0], "TIMEOUT": [0, 0]}

    def _score(i):
        if score_fn is not None:
            return score_fn(candles, i)
        return score_last_bar(candles[max(0, i - 80) : i + 1])

    def _ensemble(i):
        if ensemble_fn is not None:
            return ensemble_fn(candles, i)
        from src.scalp.ensemble import ensemble_lens

        return ensemble_lens(candles[max(0, i - 120) : i + 1])

    for i, candle in enumerate(candles):
        this_atr = float(atr[i]) if i < len(atr) else float("nan")
        if this_atr != this_atr or this_atr <= 0:
            continue
        gate = evaluate_cost_gate(
            float(candle["close"]),
            this_atr,
            this_atr,
            venue=venue,
            fee_mode="maker",
            spread_pct=spread,
            asset_class=asset_class,
        )
        if gate["blocked"]:
            if i > busy_until:
                blocked += 1
            continue
        side, score = _score(i)
        if ensemble_fn is not None:
            s2 = _ensemble(i)
        elif score >= 4.5 and i > busy_until:
            s2 = _ensemble(i)
        else:
            s2 = None
        recent = []
        for candle_j in candles[max(0, i - 2) : i + 1]:
            recent.extend(_delta_rows(int(candle_j["timestamp"])))
        s5 = delta_fn(recent) if recent else None
        triggered = should_trigger(score, side, s2, s5, gate["blocked"], mode="either")
        if i <= busy_until:
            if triggered:
                skipped += 1
            continue
        passed += 1
        if not triggered or side not in ("UP", "DOWN"):
            continue
        setup = float(candle["close"])
        filled_at = None
        for j in range(i + 1, min(i + 4, len(candles))):
            ts_j = int(candles[j]["timestamp"])
            if book is not None:
                hit = book.through(ts_j, side, setup, tick)
            else:
                hit = _through(side, setup, _prices(_price_rows(ts_j)), tick)
            if hit:
                filled_at = j
                break
        path_start = filled_at if filled_at is not None else i + 1
        path = candles[path_start : path_start + max_hold]
        reward_px, risk_px = bracket_prices(side, setup, gate["reward_pct"], gate["risk_pct"])
        trade_paths = {}
        for bar in path:
            high_hit = float(bar["high"]) >= reward_px if side == "UP" else float(bar["low"]) <= reward_px
            risk_hit = float(bar["low"]) <= risk_px if side == "UP" else float(bar["high"]) >= risk_px
            if not (high_hit and risk_hit):
                continue
            rows = _price_rows(int(bar["timestamp"]))
            if rows:
                trade_paths[int(bar["timestamp"])] = [(int(r[0]), float(r[1])) for r in rows]
        if not path:
            continue
        resolved = resolve_path(side, setup, gate["reward_pct"], gate["risk_pct"], path, max_hold, trade_paths)
        same_candle["aggTrades"] += resolved["same_candle"]["aggTrades"]
        same_candle["loss_no_trades"] += resolved["same_candle"]["loss_no_trades"]
        would = resolved["outcome"]
        filled = filled_at is not None
        if would in fill_groups:
            fill_groups[would][1] += 1
            if filled:
                fill_groups[would][0] += 1
        if not filled:
            records.append(
                {
                    "outcome": "NOT_FILLED",
                    "would_be": would,
                    "counts_for_graduation": False,
                    "signal_time": int(candle["timestamp"]) + 60_000,
                    "prediction_direction": side,
                    "cost_pct": None,
                    "spread_assumed": True,
                }
            )
            busy_until = min(i + 3, len(candles) - 1)
            continue
        outcome = resolved["outcome"]
        cost = scalp_outcome_cost(outcome, venue, spread)
        net = None if cost is None else scalp_net(outcome, gate["reward_pct"], gate["risk_pct"], cost, resolved["timeout_return_pct"], side)
        paid = 0.0
        if net is not None and filled_at is not None:
            exit_ts = int(candles[min(path_start + resolved["bars_held"] - 1, len(candles) - 1)]["timestamp"]) + 60_000
            paid = _funding(side, int(candles[filled_at]["timestamp"]), exit_ts, funding)
            net -= paid
        gross = None if net is None else net + cost + paid
        counted = outcome in ("WIN", "LOSS", "TIMEOUT")
        records.append(
            {
                "outcome": outcome,
                "would_be": would,
                "counts_for_graduation": counted,
                "signal_time": int(candle["timestamp"]) + 60_000,
                "entry_time": int(candles[filled_at]["timestamp"]),
                "prediction_direction": side,
                "price_at_prediction": setup,
                "price_at_verification": resolved["exit_price"],
                "cost_pct": cost,
                "gross_return_pct": gross,
                "net_return_pct": net,
                "hit": outcome == "WIN",
                "reward_pct": gate["reward_pct"],
                "risk_pct": gate["risk_pct"],
                "breakeven_wr": gate["breakeven_wr"],
                "funding_paid": paid,
                "spread_assumed": True,
                "resolved_by": resolved["resolved_by"],
                "day": _day(int(candle["timestamp"]) + 60_000),
                "move": 1 if outcome == "WIN" else -1,
                "prev_move": last_move,
            }
        )
        if counted:
            last_move = 1 if outcome == "WIN" else -1
        busy_until = path_start + resolved["bars_held"] - 1

    def _rate(name):
        filled, total = fill_groups[name]
        return None if total == 0 else filled / total

    return {
        "records": records,
        "skipped_while_open": skipped,
        "blocked": blocked,
        "passed": passed,
        "same_candle": same_candle,
        "fill_rate_winners": _rate("WIN"),
        "fill_rate_losers": _rate("LOSS"),
        "fill_rate_timeouts": _rate("TIMEOUT"),
    }


def _day(ts_ms: int) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ts_ms / 1000, timezone.utc).strftime("%Y-%m-%d")
