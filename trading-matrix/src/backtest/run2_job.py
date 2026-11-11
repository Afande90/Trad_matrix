"""Run 2 execution. Frozen rules and the ledger row are written before the new holdout is read."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config.costs import (
    assumed_spread_pct,
    round_trip_cost,
    scalp_outcome_cost,
    warn_if_metal_fee_unconfirmed,
)
from src.backtest.agg import AggCursor
from src.backtest.download import agg_url, ensure_file, ensure_funding, ensure_klines, fetch_ticks
from src.backtest.ledger import register_holdout
from src.backtest.loader import iter_symbol_months, load_funding, month_iter, read_klines_zip
from src.backtest.oracle import window_oracle
from src.backtest.replay import _atr5
from src.backtest.report_run2 import render_run2
from src.backtest.run2 import HOLDOUT_END, HOLDOUT_START, K, RULE_SETS_TRIED, Z, evaluate_step1, freeze_run2_rules
from src.backtest.runner import _calendar_days, collect_flags, random_control, split_bounds, summarize_split
from src.backtest.scalp_run2 import ExtendedReplay, fill_rate_summary
from src.backtest.trend_run2 import VoterReplay, truncation_voter
from src.ingestion.market_hours import metal_weekend_tag
from src.scalp.brackets import bracket_prices
from src.scalp.cost_gate import evaluate_cost_gate
from src.scalp.ensemble import ensemble_lens
from src.scalp.orderflow import delta_only_lens
from src.scalp.setup_scorer import score_both
from src.scalp.trigger import agrees, should_trigger
from src.verification.graduation import z_for_k


ROOT = Path("data/history")
RULES = Path("backtest/frozen_rules.json")
LEDGER = Path("backtest/holdout_ledger.json")
RUN1 = Path("reports/backtest_2026-11-11.md")


def _ms(day: str) -> int:
    year, month, dom = (int(part) for part in day.split("-"))
    return int(datetime(year, month, dom, tzinfo=timezone.utc).timestamp() * 1000)


def _day(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def _stamp_range(start: datetime, end: datetime) -> str:
    return f"{start.strftime('%Y-%m-%d')} → {end.strftime('%Y-%m-%d')}"


class WindowCatcher:
    """Entry = next 1m open. Exit = close at entry + window. No lens, no funding."""

    def __init__(self, window_ms: int, start_ms: int, end_ms: int):
        self.window_ms = int(window_ms)
        self.start_ms = int(start_ms)
        self.end_ms = int(end_ms)
        self.entries: list[float] = []
        self.exits: list[float] = []
        self.pending: dict | None = None
        self.gap_missing = 0
        self.prev: int | None = None
        self.span_start: int | None = None
        self.span_end: int | None = None

    def push(self, candle: dict) -> None:
        ts = int(candle["timestamp"])
        if ts + 60_000 < self.start_ms:
            self.prev = ts
            return
        if ts >= self.end_ms + self.window_ms:
            return
        if self.start_ms <= ts < self.end_ms:
            if self.span_start is None:
                self.span_start = ts
            self.span_end = ts
        if self.prev is not None and ts > self.prev + 60_000 and self.start_ms <= ts <= self.end_ms:
            self.gap_missing += (ts - self.prev) // 60_000 - 1
            self.pending = None
        self.prev = ts
        close_time = ts + 60_000
        if self.pending is not None:
            if self.pending.get("entry") is None and ts == self.pending["signal_time"]:
                self.pending["entry"] = float(candle["open"])
            if self.pending.get("entry") is not None and close_time == self.pending["exit_time"]:
                self.entries.append(float(self.pending["entry"]))
                self.exits.append(float(candle["close"]))
                self.pending = None
            elif close_time > self.pending["exit_time"]:
                self.pending = None
        if close_time % self.window_ms == 0 and self.start_ms <= close_time < self.end_ms:
            self.pending = {"signal_time": close_time, "entry": None, "exit_time": close_time + self.window_ms}

    def ratio(self) -> float:
        if self.span_start is None or self.span_end is None or self.span_end <= self.span_start:
            return 1.0
        span = (self.span_end - self.span_start) // 60_000
        if span <= 0:
            return 1.0
        return self.gap_missing / span


def _stream(root: Path, symbol: str, market: str, start: str, end: str, consumers: list) -> None:
    for month, candles in iter_symbol_months(root, symbol, market, start, end):
        for candle in candles:
            for consumer in consumers:
                consumer.push(candle)
        print(f"  read {symbol} {month} ({len(candles)} candles)", flush=True)
        del candles


def _prepare_months(root: Path, symbol: str, start: str, end: str, label: str) -> list[str]:
    missing = []
    try:
        ensure_klines(root, symbol, "futures", start, end)
        ensure_funding(root, symbol, start, end)
    except Exception as exc:  # noqa: BLE001 - the report must say the download failed
        missing.append(f"{label} {symbol} {start}..{end}: {exc}")
    for month in month_iter(start, end):
        path = root / "futures" / symbol / f"{symbol}-1m-{month}.zip"
        if not path.exists() or path.stat().st_size <= 0:
            missing.append(f"{symbol} klines {month} missing")
    return missing


def _trend_engines(cost: float, funding: list) -> list[VoterReplay]:
    specs = [
        ("markov", 3_600_000, 300_000, "T1", "T1 MOMENTUM 1h"),
        ("markov", 14_400_000, 900_000, "T2", "T2 MOMENTUM 4h"),
        ("technical", 3_600_000, 300_000, "T3", "T3 REVERSION 1h"),
        ("technical", 14_400_000, 900_000, "T4", "T4 REVERSION 4h"),
    ]
    return [
        VoterReplay(
            voter=voter,
            window_ms=window,
            bucket_ms=bucket,
            lookback=500,
            cost=cost,
            symbol="BTCUSDT",
            track=track,
            label=label,
            funding=funding,
        )
        for voter, window, bucket, track, label in specs
    ]


def _filter_records(records: list[dict], start_ms: int, end_ms: int) -> list[dict]:
    return [row for row in records if start_ms <= int(row.get("signal_time") or 0) < end_ms]


def _slots(entries: list[float], exits: list[float], cost: float) -> list[dict]:
    return [{"entry": entry, "entry_close": entry, "verify": exit_px, "cost": cost} for entry, exit_px in zip(entries, exits)]


def _rate_text(rows: list[dict], name: str) -> str:
    subset = [row for row in rows if row.get("would_be") == name]
    if not subset:
        return "n/a"
    filled = sum(1 for row in subset if row.get("filled"))
    return f"{filled / len(subset):.3f} ({filled}/{len(subset)})"


def _annotate_scalp(records: list[dict], asset_class: str) -> None:
    prev = 0
    for record in records:
        record["day"] = _day(int(record["signal_time"]))
        record["move"] = 1 if record.get("outcome") == "WIN" else -1 if record.get("outcome") in ("LOSS", "TIMEOUT") else 0
        record["prev_move"] = prev
        record["funding_paid"] = float(record.get("funding_paid") or 0.0)
        record["funding_ignored"] = False
        if asset_class == "SCALP_METAL":
            record["weekend"] = metal_weekend_tag(asset_class, int(record["signal_time"]))
        if record.get("counts_for_graduation"):
            prev = record["move"]


def _both_edges(direction: str, setup: float, reward: float, risk: float, candle: dict) -> bool:
    reward_px, risk_px = bracket_prices(direction, setup, reward, risk)
    high = float(candle["high"])
    low = float(candle["low"])
    if direction == "UP":
        return high >= reward_px and low <= risk_px
    return low <= reward_px and high >= risk_px


def _need_prices(engine: ExtendedReplay, candle: dict) -> bool:
    for watcher in engine.watchers:
        if watcher.get("record_written"):
            continue
        if _both_edges(watcher["direction"], watcher["price"], watcher["reward_pct"], watcher["risk_pct"], candle):
            return True
    return False


def _trades_from_agg(ts: int, agg: dict | None, keep: bool) -> list[tuple]:
    if not agg or agg.get("min") is None:
        return []
    if keep and agg.get("prices"):
        return [(int(stamp), float(price), 0.0, False) for stamp, price in agg["prices"]]
    rows = [(ts, float(agg["min"]), float(agg["sell"]), True)]
    if float(agg["max"]) != float(agg["min"]):
        rows.append((ts + 1, float(agg["max"]), float(agg["buy"]), False))
    return rows


def run_extended(
    root: Path,
    symbol: str,
    asset_class: str,
    start: str,
    end: str,
    start_ms: int,
    end_ms: int,
    tick: float,
    spread: float,
    funding: list,
    download_agg: bool,
) -> dict:
    engine = ExtendedReplay(
        tick=tick,
        spread_pct=spread,
        venue="futures",
        symbol=symbol,
        asset_class=asset_class,
        max_hold=60,
        funding=funding,
    )
    blocked = 0
    passed = 0
    delta_buf: list[tuple[float, float]] = []
    warmup: list[dict] = []
    folder = root / "aggTrades" / symbol
    for month in month_iter(start, end):
        kpath = root / "futures" / symbol / f"{symbol}-1m-{month}.zip"
        if not kpath.exists():
            continue
        candles = read_klines_zip(kpath, symbol, "BINANCE_UM")
        joined = warmup + candles
        scores = score_both(joined)
        high = [float(c["high"]) for c in joined]
        low = [float(c["low"]) for c in joined]
        close = [float(c["close"]) for c in joined]
        atr = _atr5(high, low, close, [c["timestamp"] for c in joined])
        offset = len(warmup)
        zpath = folder / f"{symbol}-aggTrades-{month}.zip"
        if download_agg:
            ensure_file(agg_url(symbol, month), zpath)
        cursor = AggCursor(zpath) if zpath.exists() and zpath.stat().st_size > 0 else None
        try:
            for index, candle in enumerate(candles):
                ts = int(candle["timestamp"])
                agg = None
                keep = False
                if cursor is not None:
                    while cursor.peek_minute() is not None and cursor.peek_minute() < ts:
                        cursor.consume(False)
                    if cursor.peek_minute() == ts:
                        keep = _need_prices(engine, candle)
                        agg = cursor.consume(keep)
                trades = _trades_from_agg(ts, agg, keep)
                engine.on_candle(candle, trades)
                buy = float(agg["buy"]) if agg else 0.0
                sell = float(agg["sell"]) if agg else 0.0
                delta_buf.append((buy, sell))
                if len(delta_buf) > 3:
                    delta_buf.pop(0)
                if any(engine._blocks(watcher) for watcher in engine.watchers):
                    continue
                if ts + 60_000 < start_ms or ts + 60_000 >= end_ms:
                    continue
                joined_index = offset + index
                this_atr = float(atr[joined_index]) if joined_index < len(atr) else float("nan")
                if this_atr != this_atr or this_atr <= 0:
                    continue
                gate = evaluate_cost_gate(
                    float(candle["close"]),
                    this_atr,
                    this_atr,
                    venue="futures",
                    fee_mode="maker",
                    spread_pct=spread,
                    asset_class=asset_class,
                )
                if gate["blocked"]:
                    blocked += 1
                    continue
                passed += 1
                chosen = scores[joined_index]
                side = chosen["side"]
                score = float(chosen["chosen"]["score"])
                if score < 4.5 or side not in ("UP", "DOWN"):
                    continue
                rows = []
                for bought, sold in delta_buf:
                    if bought:
                        rows.append((bought, False))
                    if sold:
                        rows.append((sold, True))
                s5 = delta_only_lens(rows) if rows else None
                s2 = None
                if not agrees(s5, side):
                    s2 = ensemble_lens(joined[max(0, joined_index - 179) : joined_index + 1])
                if not should_trigger(score, side, s2, s5, False, require="either"):
                    continue
                engine.open_setup(
                    direction=side,
                    price=float(candle["close"]),
                    reward_pct=float(gate["reward_pct"]),
                    risk_pct=float(gate["risk_pct"]),
                    signal_time=ts + 60_000,
                    score=score,
                    breakeven_wr=float(gate["breakeven_wr"]),
                )
        finally:
            if cursor is not None:
                cursor.close()
        if download_agg and zpath.exists():
            zpath.unlink()
        warmup = joined[-220:]
        print(
            f"  scalp {symbol} {month} blocked {blocked} passed {passed} triggered {engine.triggered} counted {sum(1 for r in engine.records if r.get('counts_for_graduation'))}",
            flush=True,
        )
        del candles, joined, scores
    _annotate_scalp(engine.records, asset_class)
    kept = _filter_records(engine.records, start_ms, end_ms)
    would = [row for row in engine.would_be if start_ms <= int(row["signal_time"]) < end_ms]
    return {
        "records": kept,
        "blocked": blocked,
        "passed": passed,
        "triggered": engine.triggered,
        "not_filled": sum(1 for row in kept if row.get("outcome") == "NOT_FILLED"),
        "same_candle_trades": engine.same_candle_trades,
        "same_candle_loss": engine.same_candle_loss,
        "would_be": would,
        "fill_winners": _rate_text(would, "WIN"),
        "fill_losers": _rate_text(would, "LOSS"),
    }


def _pack(label, symbol, track, summary, oracle, ran, dates, extra) -> dict:
    counted = int(summary.get("counted") or 0)
    row = {
        "label": label,
        "track": track,
        "symbol": symbol,
        "counted": counted,
        "days_with_calls": summary.get("days_with_calls") or 0,
        "gross_mean": summary.get("gross_mean") if counted else None,
        "net_mean": summary.get("net_mean") if counted else None,
        "net_lb": summary.get("net_lb") if counted else None,
        "net_mean_x2": summary.get("net_mean_x2") if counted else None,
        "net_mean_x3": summary.get("net_mean_x3") if counted else None,
        "hit_rate": summary.get("hit_rate"),
        "hit_lb": summary.get("hit_lb"),
        "baselines": summary.get("baselines") if counted else None,
        "beats_baselines": summary.get("beats_baselines"),
        "breakeven_wr_mean": summary.get("breakeven_wr_mean"),
        "wins": summary.get("wins"),
        "losses": summary.get("losses"),
        "timeouts": summary.get("timeouts"),
        "max_dd_r": summary.get("max_dd_r"),
        "losing_streak": summary.get("losing_streak"),
        "level": summary.get("level"),
        "profit_spread_over_months": summary.get("profit_spread_over_months"),
        "spread_assumed_share": summary.get("spread_assumed_share") if counted else None,
        "funding_ignored_share": summary.get("funding_ignored_share") if counted else None,
        "net_by_month": summary.get("net_by_month") or {},
        "oracle_gross": oracle.get("gross"),
        "oracle_cost": oracle.get("cost"),
        "oracle_net": oracle.get("net"),
        "breakeven_hit_rate": oracle.get("breakeven_hit_rate"),
        "oracle_wiring_ok": oracle.get("wiring_ok"),
        "ran": ran,
        "holdout_dates": dates,
        "flags": extra.get("flags") or [],
        "unexplained_flags": extra.get("unexplained_flags") or [],
        "validate_net_mean": extra.get("validate_net_mean"),
        "random_net": extra.get("random_net"),
        "blocked": extra.get("blocked", 0),
        "not_filled": extra.get("not_filled", 0),
        "same_candle_trades": extra.get("same_candle_trades", 0),
        "same_candle_loss": extra.get("same_candle_loss", 0),
        "maker_fill_winners": extra.get("maker_fill_winners", "n/a"),
        "maker_fill_losers": extra.get("maker_fill_losers", "n/a"),
        "note": extra.get("note"),
    }
    return row


def _empty_summary() -> dict:
    return summarize_split([], [], Z, scalp=False)


def _outcome_multiples(records: list[dict]) -> tuple[float | None, float | None]:
    counted = [row for row in records if row.get("counts_for_graduation")]
    if not counted:
        return None, None
    x2 = []
    x3 = []
    for row in counted:
        gross = float(row["gross_return_pct"])
        cost = float(row["cost_pct"])
        paid = float(row.get("funding_paid") or 0.0)
        x2.append(gross - 2 * cost - paid)
        x3.append(gross - 3 * cost - paid)
    return sum(x2) / len(x2), sum(x3) / len(x3)


def run() -> None:
    print("freeze: looking up USD-M ticks", flush=True)
    looked = fetch_ticks(["BTCUSDT", "XAUUSDT"])
    ticks = looked["ticks"]
    print(f"ticks {ticks} from {looked['source']}", flush=True)
    payload = freeze_run2_rules(RULES, ticks["BTCUSDT"], ticks["XAUUSDT"], looked["source"])
    register_holdout(LEDGER, RULES, HOLDOUT_START, HOLDOUT_END, ["BTCUSDT", "XAUUSDT"])
    print(f"ledger written for {HOLDOUT_START} → {HOLDOUT_END} before any holdout read", flush=True)
    metal_unconfirmed = warn_if_metal_fee_unconfirmed()
    spread = assumed_spread_pct()
    trend_cost = round_trip_cost("CRYPTO", "futures", "taker", spread)
    timeout_cost = scalp_outcome_cost("TIMEOUT", "futures", spread)
    assert z_for_k(6) == 3.09

    print("sanity: stream 2024-11 futures through the four voters", flush=True)
    nov = read_klines_zip(ROOT / "futures" / "BTCUSDT" / "BTCUSDT-1m-2024-11.zip", "BTCUSDT", "BINANCE_UM")
    sanity = _trend_engines(trend_cost, [])
    for candle in nov[: 10 * 1440]:
        for engine in sanity:
            engine.push(candle)
    truncation_ok = truncation_voter(
        nov[: 12 * 1440],
        voter="markov",
        window_ms=3_600_000,
        bucket_ms=300_000,
        lookback=500,
        cost=trend_cost,
    )
    print(f"sanity finished. truncation identical: {truncation_ok}", flush=True)
    del nov, sanity

    print("download holdout futures klines and funding 2022-11..2024-10", flush=True)
    missing = _prepare_months(ROOT, "BTCUSDT", "2022-11", "2024-10", "holdout")
    if missing:
        _write_download_failure(missing, looked)
        return

    btc_start, btc_end = _ms(HOLDOUT_START), _ms(HOLDOUT_END)
    gold_bounds = split_bounds("2025-12", "2026-10")
    gold_start = int(gold_bounds["valid_end"].timestamp() * 1000)
    gold_end = int(gold_bounds["end"].timestamp() * 1000)
    seen_start, seen_end = _ms("2026-06-08"), _ms("2026-11-01")

    print("ceiling on BTC holdout", flush=True)
    btc_1h = WindowCatcher(3_600_000, btc_start, btc_end)
    btc_4h = WindowCatcher(14_400_000, btc_start, btc_end)
    _stream(ROOT, "BTCUSDT", "futures", "2022-11", "2024-10", [btc_1h, btc_4h])
    oracle_1h = window_oracle(btc_1h.entries, btc_1h.exits, trend_cost)
    oracle_4h = window_oracle(btc_4h.entries, btc_4h.exits, trend_cost)
    print(f"BTC 1h ceiling {oracle_1h}", flush=True)
    print(f"BTC 4h ceiling {oracle_4h}", flush=True)

    print("ceiling on gold holdout slice", flush=True)
    gold_60 = WindowCatcher(3_600_000, gold_start, gold_end)
    _stream(ROOT, "XAUUSDT", "futures", "2025-12", "2026-10", [gold_60])
    oracle_gold = window_oracle(gold_60.entries, gold_60.exits, timeout_cost)
    print(f"gold 60m ceiling {oracle_gold}", flush=True)

    btc_scalp_catch = WindowCatcher(3_600_000, btc_start, btc_end)
    # The 1h catcher already has the same windows. Reuse it for the scalp ceiling.
    oracle_btc_scalp = window_oracle(btc_1h.entries, btc_1h.exits, timeout_cost)
    print(f"BTC extended ceiling {oracle_btc_scalp}", flush=True)

    funding_btc = load_funding(ROOT, "BTCUSDT", "2022-11", "2024-10")
    funding_gold = load_funding(ROOT, "XAUUSDT", "2025-12", "2026-10")
    btc_days = _calendar_days(datetime(2022, 11, 1, tzinfo=timezone.utc), datetime(2024, 11, 1, tzinfo=timezone.utc))
    gold_days = _calendar_days(gold_bounds["valid_end"], gold_bounds["end"])
    btc_dates = f"{HOLDOUT_START} → {HOLDOUT_END}"
    gold_dates = _stamp_range(gold_bounds["valid_end"], gold_bounds["end"])

    trend_ran = bool(oracle_1h.get("net") is not None and oracle_1h["net"] > 0 and oracle_1h.get("wiring_ok"))
    trend4_ran = bool(oracle_4h.get("net") is not None and oracle_4h["net"] > 0 and oracle_4h.get("wiring_ok"))
    engines = _trend_engines(trend_cost, funding_btc)
    active = []
    if trend_ran:
        active.extend([engines[0], engines[2]])
    if trend4_ran:
        active.extend([engines[1], engines[3]])
    if active:
        print("run trend voters whose ceiling net is positive", flush=True)
        _stream(ROOT, "BTCUSDT", "futures", "2022-11", "2024-10", active)
    else:
        print("trend ceiling net <= 0; voters not run", flush=True)

    scalp_btc = None
    if oracle_btc_scalp.get("net") is not None and oracle_btc_scalp["net"] > 0 and oracle_btc_scalp.get("wiring_ok"):
        print("run BTC extended. aggTrades downloaded per month and deleted", flush=True)
        scalp_btc = run_extended(
            ROOT, "BTCUSDT", "CRYPTO", "2022-11", "2024-10", btc_start, btc_end, float(ticks["BTCUSDT"]), spread, funding_btc, True
        )
    else:
        print("BTC extended ceiling net <= 0; strategy not run and aggTrades not downloaded", flush=True)

    scalp_gold = None
    if oracle_gold.get("net") is not None and oracle_gold["net"] > 0 and oracle_gold.get("wiring_ok"):
        print("run gold extended", flush=True)
        scalp_gold = run_extended(
            ROOT,
            "XAUUSDT",
            "SCALP_METAL",
            gold_bounds["valid_end"].strftime("%Y-%m"),
            "2026-10",
            gold_start,
            gold_end,
            float(ticks["XAUUSDT"]),
            spread,
            funding_gold,
            True,
        )
    else:
        print("gold extended ceiling net <= 0; strategy not run", flush=True)

    print("seen period ceilings (not evidence)", flush=True)
    seen_1h = WindowCatcher(3_600_000, seen_start, seen_end)
    seen_4h = WindowCatcher(14_400_000, seen_start, seen_end)
    _stream(ROOT, "BTCUSDT", "futures", "2026-06", "2026-10", [seen_1h, seen_4h])
    seen_oracle_1h = window_oracle(seen_1h.entries, seen_1h.exits, trend_cost)
    seen_oracle_4h = window_oracle(seen_4h.entries, seen_4h.exits, trend_cost)
    seen_oracle_scalp = window_oracle(seen_1h.entries, seen_1h.exits, timeout_cost)

    def trend_summary(index, oracle, ran, days, dates):
        if not ran or not engines:
            summary = _empty_summary()
            records = []
        else:
            records = _filter_records(engines[index].records, btc_start, btc_end)
            summary = summarize_split(records, days, Z, scalp=False)
        return summary, records

    specs = [
        (0, "T1 MOMENTUM 1h", "T1", oracle_1h, trend_ran, "BTCUSDT"),
        (1, "T2 MOMENTUM 4h", "T2", oracle_4h, trend4_ran, "BTCUSDT"),
        (2, "T3 REVERSION 1h", "T3", oracle_1h, trend_ran, "BTCUSDT"),
        (3, "T4 REVERSION 4h", "T4", oracle_4h, trend4_ran, "BTCUSDT"),
    ]
    tracks = []
    entry_ok = True
    cost_ok = True
    for index, label, track, oracle, ran, symbol in specs:
        summary, records = trend_summary(index, oracle, ran, btc_days, btc_dates)
        for record in records:
            if record.get("counts_for_graduation"):
                if record.get("entry_time") != record.get("signal_time"):
                    entry_ok = False
                if record.get("price_at_prediction") != record.get("entry_open"):
                    entry_ok = False
                if not record.get("cost_pct") or record["cost_pct"] <= 0:
                    cost_ok = False
        slots = _slots(btc_1h.entries if index in (0, 2) else btc_4h.entries, btc_1h.exits if index in (0, 2) else btc_4h.exits, trend_cost)
        n = summary["counted"] if summary["counted"] >= 30 else min(2000, len(slots))
        rnd = random_control(slots, n, seed=1)
        flags, unexplained = collect_flags(summary, None, None, scalp=False)
        if not ran:
            flags.append("window oracle net <= 0, so the voter was not run")
        tracks.append(
            _pack(
                label,
                symbol,
                track,
                summary,
                oracle,
                ran,
                btc_dates,
                {
                    "flags": flags,
                    "unexplained_flags": unexplained,
                    "random_net": rnd.get("net_mean"),
                    "maker_fill_winners": "n/a (taker entry)",
                    "maker_fill_losers": "n/a (taker entry)",
                    "note": "Futures taker. Markov alone." if index < 2 else "Futures taker. Technical alone.",
                },
            )
        )

    def scalp_track(label, track, symbol, oracle, ran, result, days, dates, note, validate_net):
        if result is None:
            summary = summarize_split([], days, Z, scalp=True)
            extra = {
                "flags": ["window oracle net <= 0, so the strategy was not run"],
                "unexplained_flags": [],
                "maker_fill_winners": "n/a",
                "maker_fill_losers": "n/a",
                "note": note,
                "validate_net_mean": validate_net,
            }
        else:
            summary = summarize_split(result["records"], days, Z, scalp=True)
            x2, x3 = _outcome_multiples(result["records"])
            summary["net_mean_x2"] = x2
            summary["net_mean_x3"] = x3
            flags, unexplained = collect_flags(summary, None, None, scalp=True)
            extra = {
                "flags": flags,
                "unexplained_flags": unexplained,
                "blocked": result["blocked"],
                "not_filled": result["not_filled"],
                "same_candle_trades": result["same_candle_trades"],
                "same_candle_loss": result["same_candle_loss"],
                "maker_fill_winners": result["fill_winners"],
                "maker_fill_losers": result["fill_losers"],
                "note": note,
                "validate_net_mean": validate_net,
            }
            for record in result["records"]:
                if record.get("counts_for_graduation") and (not record.get("cost_pct") or record["cost_pct"] <= 0):
                    nonlocal_cost[0] = False
        slots = _slots(
            btc_1h.entries if symbol == "BTCUSDT" else gold_60.entries,
            btc_1h.exits if symbol == "BTCUSDT" else gold_60.exits,
            timeout_cost,
        )
        n = summary["counted"] if summary["counted"] >= 30 else min(2000, len(slots))
        rnd = random_control(slots, n, seed=1)
        extra["random_net"] = rnd.get("net_mean")
        return _pack(label, symbol, track, summary, oracle, ran and result is not None, dates, extra), rnd

    nonlocal_cost = [True]
    btc_scalp_row, rnd_scalp = scalp_track(
        "S1 BTC EXTENDED",
        "S1",
        "BTCUSDT",
        oracle_btc_scalp,
        True,
        scalp_btc,
        btc_days,
        btc_dates,
        "Maker entry. EXTENDED only. Trigger is S2 or S5. Gold is a separate track.",
        None,
    )
    gold_note = (
        f"Gold archive starts 2025-12. Holdout slice {gold_dates} is the last 20% of 2025-12 through 2026-10. "
        "The history is short. Expect TOO EARLY unless the ceiling itself is below zero, which stops the track first."
    )
    gold_row, _rnd_gold = scalp_track(
        "S2 GOLD EXTENDED",
        "S2",
        "XAUUSDT",
        oracle_gold,
        True,
        scalp_gold,
        gold_days,
        gold_dates,
        gold_note,
        None,
    )
    cost_ok = cost_ok and nonlocal_cost[0]
    tracks.extend([btc_scalp_row, gold_row])

    primary_slots = _slots(btc_1h.entries, btc_1h.exits, trend_cost)
    primary = random_control(primary_slots, min(2000, len(primary_slots)), seed=1)
    oracles = [oracle_1h, oracle_4h, oracle_btc_scalp, oracle_gold]
    gap_ratio = max(btc_1h.ratio(), btc_4h.ratio(), gold_60.ratio())
    step = evaluate_step1(
        random_ctrl=primary,
        oracles=[{"gross": row.get("gross"), "net": row.get("net"), "cost": row.get("cost"), "wiring_ok": row.get("wiring_ok")} for row in oracles],
        truncation_ok=truncation_ok,
        entry_ok=entry_ok,
        cost_ok=cost_ok,
        ledger_ok=RULES.exists() and LEDGER.exists(),
        same_candle_reported=True,
        gap_ratio=gap_ratio,
        rule_sets_tried=RULE_SETS_TRIED,
        k=K,
        z=Z,
    )
    seen_days = _calendar_days(datetime(2026, 6, 8, tzinfo=timezone.utc), datetime(2026, 11, 1, tzinfo=timezone.utc))
    funding_seen = load_funding(ROOT, "BTCUSDT", "2026-06", "2026-10")
    seen_engines = _trend_engines(trend_cost, funding_seen)
    seen_active = []
    seen_1h_run = seen_oracle_1h.get("net") is not None and seen_oracle_1h["net"] > 0 and seen_oracle_1h.get("wiring_ok")
    seen_4h_run = seen_oracle_4h.get("net") is not None and seen_oracle_4h["net"] > 0 and seen_oracle_4h.get("wiring_ok")
    if seen_1h_run:
        seen_active.extend([seen_engines[0], seen_engines[2]])
    if seen_4h_run:
        seen_active.extend([seen_engines[1], seen_engines[3]])
    if seen_active:
        print("seen period trend voters (not evidence)", flush=True)
        _stream(ROOT, "BTCUSDT", "futures", "2026-06", "2026-10", seen_active)

    def _seen_trend(index, label, oracle, ran):
        if not ran:
            counted, net = 0, None
        else:
            records = _filter_records(seen_engines[index].records, seen_start, seen_end)
            summary = summarize_split(records, seen_days, Z, scalp=False)
            counted, net = summary["counted"], summary["net_mean"]
        return {
            "label": label,
            "counted": counted,
            "net_mean": net,
            "oracle_gross": oracle.get("gross"),
            "oracle_net": oracle.get("net"),
            "oracle_cost": oracle.get("cost"),
        }

    seen_scalp = None
    if seen_oracle_scalp.get("net") is not None and seen_oracle_scalp["net"] > 0 and seen_oracle_scalp.get("wiring_ok"):
        print("seen period BTC extended (not evidence)", flush=True)
        seen_scalp = run_extended(
            ROOT, "BTCUSDT", "CRYPTO", "2026-06", "2026-10", seen_start, seen_end, float(ticks["BTCUSDT"]), spread, funding_seen, True
        )
    seen_tracks = [
        _seen_trend(0, "T1 MOMENTUM 1h", seen_oracle_1h, seen_1h_run),
        _seen_trend(1, "T2 MOMENTUM 4h", seen_oracle_4h, seen_4h_run),
        _seen_trend(2, "T3 REVERSION 1h", seen_oracle_1h, seen_1h_run),
        _seen_trend(3, "T4 REVERSION 4h", seen_oracle_4h, seen_4h_run),
        {
            "label": "S1 BTC EXTENDED",
            "counted": 0 if seen_scalp is None else summarize_split(seen_scalp["records"], seen_days, Z, scalp=True)["counted"],
            "net_mean": None if seen_scalp is None else summarize_split(seen_scalp["records"], seen_days, Z, scalp=True)["net_mean"],
            "oracle_gross": seen_oracle_scalp.get("gross"),
            "oracle_net": seen_oracle_scalp.get("net"),
            "oracle_cost": seen_oracle_scalp.get("cost"),
        },
        {"label": "S2 GOLD EXTENDED", "counted": 0, "net_mean": None, "oracle_net": None},
    ]
    if seen_scalp is not None:
        seen_summary = summarize_split(seen_scalp["records"], seen_days, Z, scalp=True)
        seen_tracks[4]["counted"] = seen_summary["counted"]
        seen_tracks[4]["net_mean"] = seen_summary["net_mean"]
    scope = [
        "Rule set 2. Reported K = 6. z = z_for_k(6) = 3.09. rule_sets_tried = 2.",
        "AI and visual lenses are excluded. Each trend track is one voter. It says nothing about the live 4-voter system.",
        "BTC holdout is 2022-11-01 to 2024-11-01 (end exclusive). It was not read before the ledger row.",
        "Develop window 2024-11 through 2026-05 was used only as a crash check on November 2024. Those numbers are not a verdict.",
        "2026-06-08 to 2026-11-01 is the seen period. It is not evidence.",
        (
            f"Ticks from {looked['source']}: BTCUSDT {ticks['BTCUSDT']}, XAUUSDT {ticks['XAUUSDT']}. "
            + (
                "Production fapi.binance.com returned HTTP 451 from this host, so the public USD-M testnet exchangeInfo was the lookup. "
                if "testnet" in looked["source"]
                else ""
            )
            + "Ticks were not tuned."
        ),
        "Spread is BT_ASSUMED_SPREAD_PCT. Every record is spread_assumed=true. Monthly bookTicker is not used.",
        "Trend cost is the futures taker round trip. Scalp WIN is maker+maker. LOSS and TIMEOUT are maker+taker. Spread and slippage are added once.",
        "Oracle net does not include funding. Track net does, when the funding file exists.",
        "XAUUSDT fee was not confirmed on Binance's fee page; FEE_FUT_MAKER and FEE_FUT_TAKER are used." if metal_unconfirmed else "Metal fee confirmed.",
        "S5 is aggTrade delta over the last 3 closed 1m candles. No bookTicker and no 0.25 confirmation.",
        "QUICK and the both-voters 15m trend are retired. They are not added to these tracks.",
        "One EXTENDED position at a time. NOT_FILLED is not counted.",
        f"BTC holdout gap ratio {btc_1h.ratio():.4%}. Gold holdout gap ratio {gold_60.ratio():.4%}.",
    ]
    result = {
        "K": K,
        "rule_sets_tried": RULE_SETS_TRIED,
        "z": Z,
        "step1_ok": step["step1_ok"],
        "step1": step["step1"],
        "tracks": tracks,
        "seen_tracks": seen_tracks,
        "scope": scope,
        "run1_text": RUN1.read_text() if RUN1.exists() else "",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write(result)


def _write(result: dict) -> None:
    text = render_run2(result)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    folder = Path("reports")
    folder.mkdir(parents=True, exist_ok=True)
    md = folder / f"backtest_{day}_run2.md"
    js = folder / f"backtest_{day}_run2.json"
    md.write_text(text)
    payload = {key: value for key, value in result.items() if key != "run1_text"}
    js.write_text(json.dumps(payload, indent=2, default=str))
    print(md)
    print(text)


def _write_download_failure(missing: list[str], looked: dict) -> None:
    lines = [
        "The new holdout could not be downloaded. No track numbers are invented.",
        "",
        "## CEILING",
        "",
        "No ceiling. The kline files are not complete.",
        "",
        "## Step 1",
        "",
        "- Data: download failed",
        "",
        "## DECISION",
        "",
        "RERUN. The holdout files are missing, so there is no verdict.",
        "",
        "Missing:",
    ]
    lines.extend(f"- {row}" for row in missing)
    lines.append("")
    lines.append(f"Tick lookup source: {looked.get('source')}")
    text = "\n".join(lines)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = Path("reports") / f"backtest_{day}_run2.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    print(path)
    print(text)


def _load(symbol: str, start: str, end: str, start_ms: int | None, end_ms: int | None):
    """Closed 1m futures candles, plus the count of missing minutes inside the window."""
    candles = []
    missing = 0
    prev = None
    for month, rows in iter_symbol_months(ROOT, symbol, "futures", start, end):
        for candle in rows:
            ts = int(candle["timestamp"])
            if end_ms is not None and ts >= end_ms:
                return candles, missing
            if start_ms is not None and ts < start_ms:
                prev = ts
                continue
            if prev is not None and ts > prev + 60_000 and (start_ms is None or prev >= start_ms):
                missing += (ts - prev) // 60_000 - 1
            prev = ts
            candles.append(candle)
        print(f"  loaded {symbol} {month} ({len(candles)} kept)", flush=True)
    return candles, missing


def _days(start: str, end: str) -> list[str]:
    return _calendar_days(
        datetime.fromtimestamp(_ms(start) / 1000, timezone.utc),
        datetime.fromtimestamp(_ms(end) / 1000, timezone.utc),
    )


def summarize(records: list[dict], z: float, days: list[str], scalp: bool, funding_missing: bool) -> dict:
    rows = []
    for record in records:
        row = dict(record)
        if funding_missing:
            row["funding_ignored"] = True
        rows.append(row)
    summary = summarize_split(rows, days, z, scalp)
    if scalp:
        net_x2, net_x3 = _outcome_multiples(rows)
        summary["net_mean_x2"] = net_x2
        summary["net_mean_x3"] = net_x3
    return summary


if __name__ == "__main__":
    run()
