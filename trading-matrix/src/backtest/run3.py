"""Run 3. Train chooses WITH or AGAINST. The ledger is written before the holdout is read."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from config.costs import assumed_spread_pct, scalp_outcome_cost
from src.backtest.agg import AggCursor
from src.backtest.download import agg_url, ensure_file, ensure_funding, ensure_klines
from src.backtest.ledger import register_holdout
from src.backtest.loader import load_funding, month_iter, read_klines_zip
from src.backtest.oracle import window_oracle
from src.backtest.report_run3 import render_run3
from src.backtest.run2_job import _outcome_multiples
from src.backtest.runner import _calendar_days, _max_dd_r, collect_flags, random_control, summarize_split
from src.backtest.scalp_run2 import ExtendedReplay
from src.backtest.sentence import SentenceBook, cumulative_net_drawdown, trade_side
from src.scalp.brackets import bracket_prices

TRAIN_START = "2022-11-01"
TRAIN_END = "2024-10-31"
HOLDOUT_START = "2020-11-01"
HOLDOUT_END = "2022-10-31"
TICK = 0.10


def _ms(day: str) -> int:
    year, month, dom = (int(part) for part in day.split("-"))
    return int(datetime(year, month, dom, tzinfo=timezone.utc).timestamp() * 1000)


def _day(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def _exclusive_end(day: str) -> int:
    """The given calendar day is included."""
    return _ms(day) + 86_400_000


def freeze_run3(path: Path, variant: str, train: dict) -> dict:
    payload = {
        "K": 2,
        "z": 2.88,
        "rule_sets_tried": 3,
        "variant": variant,
        "train_start": TRAIN_START,
        "train_end": TRAIN_END,
        "holdout_start": HOLDOUT_START,
        "holdout_end": HOLDOUT_END,
        "symbol": "BTCUSDT",
        "market": "USD-M perpetual",
        "closed_candles_only": True,
        "governor": "15m EMA20 > EMA50 and close > EMA50, or the mirror for DOWN",
        "doer": "buy share of the last 3 closed 1m trades; BUYERS >= 0.60; SELLERS <= 0.40",
        "target": "last close within 0.25 x ATR(5m) of the previous UTC day high, low, or profile POC",
        "state": "maker EXTENDED cost gate and the dead-market filter",
        "exception": "last closed 1m range > 3 x ATR(1m). No news calendar is bundled.",
        "news_calendar": False,
        "reward": "1.5 x ATR(5m)",
        "risk": "1.0 x ATR(5m)",
        "max_hold_min": 60,
        "entry": "maker limit at the setup price, trade-through by one tick within 3 candles",
        "outcome_cost": {"WIN": "maker+maker", "LOSS": "maker+taker", "TIMEOUT": "maker+taker"},
        "one_position_at_a_time": True,
        "tick_size": {"BTCUSDT": "0.10"},
        "tick_note": "Carried from run 2. Not looked up again and not tuned.",
        "assumed_spread_pct": 0.0001,
        "scalp_fee_mode": "maker",
        "train_WITH_counted": int(train["WITH"]["counted"]),
        "train_WITH_net_mean": train["WITH"]["net_mean"],
        "train_AGAINST_counted": int(train["AGAINST"]["counted"]),
        "train_AGAINST_net_mean": train["AGAINST"]["net_mean"],
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return payload


def _both_edges(direction: str, setup: float, reward: float, risk: float, candle: dict) -> bool:
    reward_px, risk_px = bracket_prices(direction, setup, reward, risk)
    high = float(candle["high"])
    low = float(candle["low"])
    if direction == "UP":
        return high >= reward_px and low <= risk_px
    return low <= reward_px and high >= risk_px


def _need_prices(engines: list[ExtendedReplay], candle: dict) -> bool:
    for engine in engines:
        for watcher in engine.watchers:
            if watcher.get("record_written"):
                continue
            if _both_edges(watcher["direction"], watcher["price"], watcher["reward_pct"], watcher["risk_pct"], candle):
                return True
    return False


def _price_path(ts: int, agg: dict | None, keep: bool) -> list[tuple]:
    if not agg or agg.get("min") is None:
        return []
    if keep and agg.get("prices"):
        return [(int(stamp), float(price)) for stamp, price in agg["prices"]]
    rows = [(ts, float(agg["min"]))]
    if float(agg["max"]) != float(agg["min"]):
        rows.append((ts + 1, float(agg["max"])))
    return rows


def _annotate(records: list[dict]) -> None:
    prev = 0
    for record in records:
        record["day"] = _day(int(record["signal_time"]))
        record["move"] = 1 if record.get("outcome") == "WIN" else -1 if record.get("outcome") in ("LOSS", "TIMEOUT") else 0
        record["prev_move"] = prev
        record["funding_paid"] = float(record.get("funding_paid") or 0.0)
        record["funding_ignored"] = not bool(record.get("funding_paid") or record.get("funding_applied"))
        if record.get("counts_for_graduation"):
            prev = record["move"]


def _rate(rows: list[dict], name: str) -> str:
    subset = [row for row in rows if row.get("would_be") == name]
    if not subset:
        return "n/a"
    filled = sum(1 for row in subset if row.get("filled"))
    return f"{filled / len(subset):.4f}"


class _HourOracle:
    def __init__(self):
        self.entries: list[float] = []
        self.exits: list[float] = []
        self.want: int | None = None
        self.entry: float | None = None
        self.entry_ts: int | None = None

    def push(self, candle: dict) -> None:
        ts = int(candle["timestamp"])
        if self.entry_ts is not None and ts > self.entry_ts + 59 * 60_000:
            self.entry = None
            self.entry_ts = None
        if (ts + 60_000) % 3_600_000 == 0:
            self.want = ts + 60_000
        if self.want is not None and ts == self.want:
            self.entry = float(candle["open"])
            self.entry_ts = ts
            self.want = None
        if self.entry_ts is not None and ts == self.entry_ts + 59 * 60_000 and self.entry:
            self.entries.append(self.entry)
            self.exits.append(float(candle["close"]))
            self.entry = None
            self.entry_ts = None


def _summarize_engine(engine: ExtendedReplay, start_ms: int, end_ms: int, days: list[str], z: float, funding_loaded: bool) -> dict:
    _annotate(engine.records)
    kept = [row for row in engine.records if start_ms <= int(row.get("signal_time") or 0) < end_ms]
    for row in kept:
        row["funding_ignored"] = not funding_loaded
    would = [row for row in engine.would_be if start_ms <= int(row["signal_time"]) < end_ms]
    summary = summarize_split(kept, days, z, True)
    net_x2, net_x3 = _outcome_multiples(kept)
    summary["net_mean_x2"] = net_x2
    summary["net_mean_x3"] = net_x3
    counted = [row for row in kept if row.get("counts_for_graduation")]
    summary["max_dd_net"] = cumulative_net_drawdown([float(row["net_return_pct"]) for row in counted]) if counted else 0.0
    summary["max_dd_r"] = _max_dd_r(
        [float(row["net_return_pct"]) for row in counted],
        [float(row.get("risk_pct") or row.get("cost_pct") or 1.0) for row in counted],
    ) if counted else 0.0
    summary["not_filled"] = sum(1 for row in kept if row.get("outcome") == "NOT_FILLED")
    summary["same_candle_trades"] = engine.same_candle_trades
    summary["same_candle_loss"] = engine.same_candle_loss
    summary["fill_winners"] = _rate(would, "WIN")
    summary["fill_losers"] = _rate(would, "LOSS")
    summary["records"] = kept
    return summary


def _scan(
    root: Path,
    month_from: str,
    month_to: str,
    start_ms: int,
    end_ms: int,
    specs: list[dict],
    download_agg: bool,
    spread: float,
    funding: list,
    truncation_month: str | None = None,
) -> dict:
    engines = {
        spec["name"]: ExtendedReplay(
            tick=TICK,
            spread_pct=spread,
            venue="futures",
            symbol="BTCUSDT",
            asset_class="CRYPTO",
            max_hold=60,
            funding=funding,
        )
        for spec in specs
    }
    book = SentenceBook(spread=spread)
    oracle = _HourOracle()
    blocked = 0
    missing = 0
    prev_ts = None
    span_start = None
    span_end = None
    primary_signals: list[tuple[int, str]] = []
    truncation_ok = None
    folder = root / "futures" / "BTCUSDT"
    agg_folder = root / "aggTrades" / "BTCUSDT"
    for month in month_iter(month_from, month_to):
        kpath = folder / f"BTCUSDT-1m-{month}.zip"
        if not kpath.exists():
            raise FileNotFoundError(kpath)
        candles = read_klines_zip(kpath, "BTCUSDT", "BINANCE_UM")
        zpath = agg_folder / f"BTCUSDT-aggTrades-{month}.zip"
        if download_agg:
            ensure_file(agg_url("BTCUSDT", month), zpath)
        cursor = AggCursor(zpath) if zpath.exists() and zpath.stat().st_size > 0 else None
        try:
            for candle in candles:
                ts = int(candle["timestamp"])
                agg = None
                keep = False
                if cursor is not None:
                    while cursor.peek_minute() is not None and cursor.peek_minute() < ts:
                        cursor.consume(False)
                    if cursor.peek_minute() == ts:
                        keep = _need_prices(list(engines.values()), candle)
                        agg = cursor.consume(keep)
                buy = float(agg["buy"]) if agg else 0.0
                sell = float(agg["sell"]) if agg else 0.0
                trades = list((agg.get("bins") or {}).items()) if agg else []
                roles = book.push(candle, buy, sell, trades)
                path = _price_path(ts, agg, keep)
                for engine in engines.values():
                    engine.on_candle(candle, path)
                close_time = ts + 60_000
                if start_ms <= close_time < end_ms:
                    if span_start is None:
                        span_start = close_time
                    if prev_ts is not None and close_time - prev_ts > 60_000:
                        missing += (close_time - prev_ts) // 60_000 - 1
                    span_end = close_time
                    oracle.push(candle)
                    if roles["gate_blocked"]:
                        blocked += 1
                    for spec in specs:
                        side = trade_side(roles, spec["variant"], spec["disabled"])
                        if spec["name"] == specs[0]["name"] and side:
                            primary_signals.append((close_time, side))
                        if not side or roles["reward_pct"] is None:
                            continue
                        engines[spec["name"]].open_setup(
                            direction=side,
                            price=float(roles["close"]),
                            reward_pct=float(roles["reward_pct"]),
                            risk_pct=float(roles["risk_pct"]),
                            signal_time=close_time,
                            score=0.0,
                            breakeven_wr=roles["breakeven_wr"],
                        )
                elif close_time <= start_ms:
                    oracle.push(candle)
                prev_ts = close_time
        finally:
            if cursor is not None:
                cursor.close()
        if truncation_month == month and zpath.exists():
            truncation_ok = _truncation_same_book(candles, zpath, spread, primary_signals, start_ms)
        if download_agg and zpath.exists():
            zpath.unlink()
        counted = sum(1 for row in engines[specs[0]["name"]].records if row.get("counts_for_graduation"))
        print(f"  sentence {month} blocked {blocked} open {engines[specs[0]['name']].triggered} counted {counted}", flush=True)
        del candles
    span = 0 if span_start is None or span_end is None else (span_end - span_start) // 60_000 + 1
    return {
        "engines": engines,
        "blocked": blocked,
        "oracle_entries": oracle.entries,
        "oracle_exits": oracle.exits,
        "gap_ratio": (missing / span) if span else 0.0,
        "truncation_ok": truncation_ok,
    }


def _truncation_same_book(candles: list[dict], zpath: Path, spread: float, full_signals: list[tuple[int, str]], start_ms: int) -> bool:
    if len(candles) < 1440 + 500:
        return False
    cut = len(candles) - 1440
    limit = int(candles[cut - 1]["timestamp"]) + 60_000
    short_book = SentenceBook(spread=spread)
    short: list[tuple[int, str]] = []
    cursor = AggCursor(zpath)
    try:
        for candle in candles[:cut]:
            ts = int(candle["timestamp"])
            agg = None
            while cursor.peek_minute() is not None and cursor.peek_minute() < ts:
                cursor.consume(False)
            if cursor.peek_minute() == ts:
                agg = cursor.consume(False)
            buy = float(agg["buy"]) if agg else 0.0
            sell = float(agg["sell"]) if agg else 0.0
            trades = list((agg.get("bins") or {}).items()) if agg else []
            roles = short_book.push(candle, buy, sell, trades)
            side = roles["side_with"]
            close_time = ts + 60_000
            if side and start_ms <= close_time:
                short.append((close_time, side))
    finally:
        cursor.close()
    before = [row for row in full_signals if row[0] <= limit]
    return before == short


def _pack(summary: dict, blocked: int, oracle: dict, random_net: float | None, dates: str) -> dict:
    counted = int(summary.get("counted") or 0)
    flags, unexplained = collect_flags(summary, None, None, True)
    return {
        "label": "BTC COMPLETE SENTENCE",
        "kind": "scalp",
        "symbol": "BTCUSDT",
        "counted": counted,
        "days_with_calls": summary.get("days_with_calls") or 0,
        "gross_mean": summary.get("gross_mean") if counted else None,
        "net_mean": summary.get("net_mean") if counted else None,
        "net_lb": summary.get("net_lb") if counted else None,
        "net_mean_x2": summary.get("net_mean_x2") if counted else None,
        "net_mean_x3": summary.get("net_mean_x3") if counted else None,
        "random_net": random_net,
        "breakeven_wr_mean": summary.get("breakeven_wr_mean"),
        "hit_rate": summary.get("hit_rate"),
        "hit_lb": summary.get("hit_lb"),
        "baselines": summary.get("baselines"),
        "beats_baselines": summary.get("beats_baselines"),
        "oracle_gross": oracle.get("gross"),
        "oracle_cost": oracle.get("cost"),
        "oracle_net": oracle.get("net"),
        "breakeven_hit_rate": oracle.get("breakeven_hit_rate"),
        "oracle_wiring_ok": oracle.get("wiring_ok"),
        "wins": summary.get("wins"),
        "losses": summary.get("losses"),
        "timeouts": summary.get("timeouts"),
        "blocked": blocked,
        "not_filled": summary.get("not_filled"),
        "maker_fill_winners": summary.get("fill_winners"),
        "maker_fill_losers": summary.get("fill_losers"),
        "same_candle_trades": summary.get("same_candle_trades"),
        "same_candle_loss": summary.get("same_candle_loss"),
        "max_dd_r": summary.get("max_dd_r"),
        "max_dd_net": summary.get("max_dd_net"),
        "losing_streak": summary.get("losing_streak"),
        "level": summary.get("level"),
        "spread_assumed_share": summary.get("spread_assumed_share"),
        "funding_ignored_share": summary.get("funding_ignored_share"),
        "net_by_month": summary.get("net_by_month"),
        "flags": flags,
        "unexplained_flags": unexplained,
        "profit_spread_over_months": summary.get("profit_spread_over_months"),
        "holdout_dates": dates,
        "note": "No news calendar is bundled. The exception is the 1m range versus ATR(1m) only.",
    }


def _step1(random_ctrl, oracle, truncation_ok, cost_ok, gap_ratio) -> dict:
    def random_ok() -> bool:
        if random_ctrl.get("net_mean") is None or random_ctrl.get("target") is None or not random_ctrl.get("n"):
            return False
        if random_ctrl["net_mean"] > 0:
            return False
        return abs(random_ctrl["net_mean"] - random_ctrl["target"]) <= 2 * (random_ctrl.get("se") or 0.0) + 1e-12

    oracle_ok = bool(oracle.get("wiring_ok")) and oracle.get("gross") is not None and oracle["gross"] > 0
    rows = [
        {"check": "RANDOM control", "result": f"net {random_ctrl.get('net_mean')} vs cost target {random_ctrl.get('target')} (n={random_ctrl.get('n')})", "ok": random_ok()},
        {"check": "WINDOW ORACLE", "result": "wiring ok" if oracle_ok else "wiring failed", "ok": oracle_ok},
        {"check": "Truncation test", "result": "identical: yes" if truncation_ok else "identical: no", "ok": bool(truncation_ok)},
        {"check": "Entry price", "result": "maker limit at the setup price; later aggTrades must trade through by one tick", "ok": True},
        {"check": "Costs applied", "result": "cost_pct > 0 on counted calls" if cost_ok else "cost missing", "ok": bool(cost_ok)},
        {"check": "Holdout ledger", "result": "registered before the holdout was read", "ok": True},
        {"check": "Rule sets tried (K)", "result": "rule_sets_tried = 3. Reported K = 2. z = 2.88.", "ok": True},
        {"check": "Same-candle cases", "result": "count shown; resolved by aggTrades or counted as loss", "ok": True},
        {"check": "Data gaps", "result": f"missing minutes {gap_ratio:.4%} of the spanned minutes", "ok": gap_ratio < 0.01},
    ]
    return {"step1_ok": all(row["ok"] for row in rows), "step1": rows}


def _train_row(summary: dict) -> dict:
    counted = int(summary.get("counted") or 0)
    return {
        "counted": counted,
        "days_with_calls": summary.get("days_with_calls") or 0,
        "gross_mean": summary.get("gross_mean") if counted else None,
        "net_mean": summary.get("net_mean") if counted else None,
    }


def scan_train(root: Path) -> dict:
    spread = assumed_spread_pct()
    ensure_klines(root, "BTCUSDT", "futures", "2022-11", "2024-10")
    ensure_funding(root, "BTCUSDT", "2022-11", "2024-10")
    funding = load_funding(root, "BTCUSDT", "2022-11", "2024-10")
    specs = [
        {"name": "WITH", "variant": "WITH", "disabled": set()},
        {"name": "AGAINST", "variant": "AGAINST", "disabled": set()},
    ]
    scanned = _scan(
        root,
        "2022-11",
        "2024-10",
        _ms(TRAIN_START),
        _exclusive_end(TRAIN_END),
        specs,
        True,
        spread,
        funding,
        truncation_month="2022-11",
    )
    days = _calendar_days(datetime(2022, 11, 1, tzinfo=timezone.utc), datetime(2024, 11, 1, tzinfo=timezone.utc))
    stats = {}
    for name in ("WITH", "AGAINST"):
        stats[name] = _train_row(
            _summarize_engine(scanned["engines"][name], _ms(TRAIN_START), _exclusive_end(TRAIN_END), days, 2.88, bool(funding))
        )
    from src.backtest.sentence import choose_variant

    kept = choose_variant(stats["WITH"], stats["AGAINST"])
    if int(stats["WITH"]["counted"]) < 300 and int(stats["AGAINST"]["counted"]) < 300:
        reason = "both train variants had fewer than 300 calls"
    elif kept == "AGAINST":
        reason = "AGAINST had the higher TRAIN net mean per call"
    elif stats["WITH"].get("net_mean") == stats["AGAINST"].get("net_mean"):
        reason = "the TRAIN net means were equal, so WITH was kept"
    else:
        reason = "WITH had the higher TRAIN net mean per call"
    return {"stats": stats, "kept": kept, "keep_reason": reason, "truncation_ok": scanned["truncation_ok"]}


def scan_holdout(root: Path, kept: str) -> dict:
    spread = assumed_spread_pct()
    ensure_klines(root, "BTCUSDT", "futures", "2020-11", "2022-10")
    ensure_funding(root, "BTCUSDT", "2020-11", "2022-10")
    funding = load_funding(root, "BTCUSDT", "2020-11", "2022-10")
    cost = float(scalp_outcome_cost("TIMEOUT", "futures", spread))
    specs = [
        {"name": "full", "variant": kept, "disabled": set()},
        {"name": "governor", "variant": kept, "disabled": {1}},
        {"name": "doer", "variant": kept, "disabled": {2}},
        {"name": "target", "variant": kept, "disabled": {3}},
        {"name": "exception", "variant": kept, "disabled": {5}},
    ]
    scanned = _scan(
        root,
        "2020-11",
        "2022-10",
        _ms(HOLDOUT_START),
        _exclusive_end(HOLDOUT_END),
        specs,
        True,
        spread,
        funding,
        None,
    )
    days = _calendar_days(datetime(2020, 11, 1, tzinfo=timezone.utc), datetime(2022, 11, 1, tzinfo=timezone.utc))
    oracle = window_oracle(scanned["oracle_entries"], scanned["oracle_exits"], cost)
    slots = [
        {"entry": entry, "entry_close": entry, "verify": exit_px, "cost": cost}
        for entry, exit_px in zip(scanned["oracle_entries"], scanned["oracle_exits"])
    ]
    rnd = random_control(slots, min(2000, len(slots)), seed=1)
    summaries = {
        name: _summarize_engine(
            scanned["engines"][name], _ms(HOLDOUT_START), _exclusive_end(HOLDOUT_END), days, 2.88, bool(funding)
        )
        for name in ("full", "governor", "doer", "target", "exception")
    }
    return {
        "summary": summaries["full"],
        "blocked": scanned["blocked"],
        "oracle": oracle,
        "random": rnd,
        "gap_ratio": scanned["gap_ratio"],
        "diagnostic": [
            {"role": role, "counted": summaries[role]["counted"], "net_mean": summaries[role]["net_mean"]}
            for role in ("governor", "doer", "target", "exception")
        ],
    }


def execute(root: Path | None = None) -> Path:
    root = Path(root) if root is not None else Path("data/history")
    rules = Path("backtest/frozen_rules.json")
    ledger = Path("backtest/holdout_ledger.json")
    print("train: WITH and AGAINST on 2022-11-01 to 2024-10-31", flush=True)
    train = scan_train(root)
    print(f"kept {train['kept']}: {train['keep_reason']}", flush=True)
    freeze_run3(rules, train["kept"], train["stats"])
    register_holdout(ledger, rules, HOLDOUT_START, HOLDOUT_END, ["BTCUSDT"])
    print("ledger written before the 2020-11 to 2022-10 holdout is read", flush=True)
    holdout = scan_holdout(root, train["kept"])
    summary = holdout["summary"]
    counted_rows = [row for row in summary.get("records") or [] if row.get("counts_for_graduation")]
    cost_ok = bool(counted_rows) and all(row.get("cost_pct") and row["cost_pct"] > 0 for row in counted_rows)
    if not counted_rows:
        cost_ok = True
    step = _step1(holdout["random"], holdout["oracle"], bool(train["truncation_ok"]), cost_ok, holdout["gap_ratio"])
    track = _pack(
        summary,
        holdout["blocked"],
        holdout["oracle"],
        holdout["random"].get("net_mean"),
        "2020-11-01 → 2022-10-31",
    )
    scope = [
        "Rule set 3. K = 2 because WITH and AGAINST were both run on TRAIN. z = 2.88. rule_sets_tried = 3.",
        "The kept variant was chosen on TRAIN net mean per call only. Nothing else was changed.",
        "Holdout 2020-11-01 to 2022-10-31 was registered before it was read, and the kept variant was run once.",
        "No news calendar is bundled. The exception role is the last closed 1m range versus 3 x ATR(1m).",
        "Governor: closed 15m EMA20 and EMA50. Doer: aggTrade buy share over the last 3 closed 1m candles.",
        "Target: previous UTC day high, low, or volume point of control from profile.py, within 0.25 x ATR(5m).",
        "State: maker EXTENDED cost gate and the dead-market filter (1m ATR below 0.6 of its 10-bar average).",
        "Bracket, fill, and costs match X1. WIN is maker+maker. LOSS and TIMEOUT are maker+taker. Spread 0.0001 is assumed.",
        "BTCUSDT tick 0.10 was carried from run 2 and was not tuned.",
        "Diagnostic rows switch one role off on the holdout. They are not evidence and they do not choose a variant.",
        "Run 1 and run 2 ledger rows are unchanged.",
    ]
    result = {
        "K": 2,
        "z": 2.88,
        "rule_sets_tried": 3,
        "step1_ok": step["step1_ok"],
        "step1": step["step1"],
        "kept": train["kept"],
        "keep_reason": train["keep_reason"],
        "train": train["stats"],
        "track": track,
        "diagnostic": holdout["diagnostic"],
        "scope": scope,
    }
    text = render_run3(result)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    folder = Path("reports")
    folder.mkdir(parents=True, exist_ok=True)
    md = folder / f"backtest_{day}_run3.md"
    js = folder / f"backtest_{day}_run3.json"
    md.write_text(text)
    payload = {key: value for key, value in result.items()}
    payload["track"] = {key: value for key, value in track.items()}
    js.write_text(json.dumps(payload, indent=2, default=str))
    print(md)
    print(text)
    return md
