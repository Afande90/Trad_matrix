"""Run the frozen rule set once. The ledger row is written before the new holdout is opened."""

from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config.costs import assumed_spread_pct, round_trip_cost, scalp_outcome_cost, warn_if_metal_fee_unconfirmed
from src.backtest.agg import AggCursor
from src.backtest.download import agg_url, ensure_funding, ensure_klines
from src.backtest.ledger import register_holdout
from src.backtest.loader import iter_symbol_months, load_funding
from src.backtest.oracle import window_oracle, window_pairs
from src.backtest.replay import _atr5
from src.backtest.report_run2 import render_run2
from src.backtest.run2 import K, Z, evaluate_step1, freeze_run2_rules
from src.backtest.run2_engine import score_last_bar
from src.backtest.run2_job import _days, _load, _ms, summarize
from src.backtest.runner import collect_flags, random_control
from src.backtest.scalp_run2 import ExtendedReplay, fill_rate_summary
from src.backtest.trend_run2 import VoterReplay, truncation_voter
from src.scalp.cost_gate import evaluate_cost_gate
from src.scalp.ensemble import ensemble_lens
from src.scalp.orderflow import delta_only_lens
from src.scalp.trigger import should_trigger

ROOT = Path("data/history")
DUBAI = timezone(timedelta(hours=4))
SPECS = (
    ("T1", "T1 MOMENTUM 1h", "markov", 60, 5),
    ("T2", "T2 MOMENTUM 4h", "markov", 240, 15),
    ("T3", "T3 REVERSION 1h", "technical", 60, 5),
    ("T4", "T4 REVERSION 4h", "technical", 240, 15),
)


def _engines(candles, funding, cost):
    engines = []
    for spec_id, label, voter, window_min, bar_min in SPECS:
        engines.append(
            VoterReplay(
                voter=voter,
                window_ms=window_min * 60_000,
                bucket_ms=bar_min * 60_000,
                lookback=500,
                cost=cost,
                symbol="BTCUSDT",
                track=spec_id,
                label=label,
                funding=funding,
            )
        )
    for candle in candles:
        for engine in engines:
            engine.push(candle)
    return engines


def _stamp(records: list[dict]) -> None:
    last = 0
    for record in records:
        if not record.get("signal_time"):
            continue
        record.setdefault("day", datetime.fromtimestamp(int(record["signal_time"]) / 1000, timezone.utc).strftime("%Y-%m-%d"))
        if record.get("counts_for_graduation"):
            record.setdefault("move", 1 if record.get("outcome") == "WIN" or record.get("hit") else -1)
            record.setdefault("prev_move", last)
            last = int(record["move"])
            record.setdefault("funding_paid", 0.0)


def _walk_scalp(candles, symbol, tick, asset_class, funding, start_month, end_month):
    eng = ExtendedReplay(
        tick=tick,
        spread_pct=assumed_spread_pct(),
        venue="futures",
        symbol=symbol,
        asset_class=asset_class,
        max_hold=60,
        funding=funding,
    )
    high = [float(c["high"]) for c in candles]
    low = [float(c["low"]) for c in candles]
    close = [float(c["close"]) for c in candles]
    atr = _atr5(high, low, close, [c["timestamp"] for c in candles])
    from src.scalp.setup_scorer import score_both

    scores = score_both(candles)
    deltas: deque = deque(maxlen=3)
    cursor = None
    cursor_month = None
    cursor_path = None

    def _pack(ts: int, keep: bool):
        nonlocal cursor, cursor_month, cursor_path
        month = datetime.fromtimestamp(ts / 1000, timezone.utc).strftime("%Y-%m")
        if month != cursor_month:
            if cursor is not None:
                cursor.close()
                if cursor_path is not None and cursor_path.exists():
                    cursor_path.unlink()
            dest = ROOT / "aggTrades" / symbol / f"{symbol}-aggTrades-{month}.zip"
            print(f"aggTrades {symbol} {month}", flush=True)
            try:
                from src.backtest.download import ensure_file

                ensure_file(agg_url(symbol, month), dest)
                cursor = AggCursor(dest)
                cursor_path = dest
            except Exception as exc:  # noqa: BLE001 - a missing month is a gap, not a crash
                print(f"aggTrades missing {symbol} {month}: {exc}", flush=True)
                cursor = None
                cursor_path = None
            cursor_month = month
        if cursor is None:
            return None
        while True:
            peek = cursor.peek_minute()
            if peek is None or peek > ts:
                return None
            pack = cursor.consume(keep_prices=keep)
            if pack["minute"] == ts:
                return pack

    for index, candle in enumerate(candles):
        ts = int(candle["timestamp"])
        busy = any(eng._blocks(watcher) for watcher in eng.watchers)
        pack = _pack(ts, busy)
        trades = list(pack["prices"]) if pack else []
        eng.on_candle(candle, trades)
        if pack:
            deltas.append((pack["buy"], pack["sell"]))
        else:
            deltas.append((0.0, 0.0))
        if any(eng._blocks(watcher) for watcher in eng.watchers):
            continue
        this_atr = float(atr[index]) if index < len(atr) else float("nan")
        if this_atr != this_atr or this_atr <= 0:
            continue
        gate = evaluate_cost_gate(
            float(candle["close"]),
            this_atr,
            this_atr,
            venue="futures",
            fee_mode="maker",
            spread_pct=assumed_spread_pct(),
            asset_class=asset_class,
        )
        if gate["blocked"]:
            eng.blocked += 1
            continue
        eng.passed += 1
        chosen = scores[index]
        side = chosen["side"]
        score = float(chosen["chosen"]["score"])
        if score < 4.5 or side not in ("UP", "DOWN"):
            continue
        rows = []
        for buy, sell in deltas:
            if buy:
                rows.append((buy, False))
            if sell:
                rows.append((sell, True))
        s5 = delta_only_lens(rows) if rows else None
        s2 = None
        if s5 is None or s5.direction != side:
            s2 = ensemble_lens(candles[max(0, index - 179) : index + 1])
        if not should_trigger(score, side, s2, s5, False, require="either"):
            continue
        eng.open_setup(
            direction=side,
            price=float(candle["close"]),
            reward_pct=gate["reward_pct"],
            risk_pct=gate["risk_pct"],
            signal_time=ts + 60_000,
            score=score,
            breakeven_wr=gate["breakeven_wr"],
        )
    if cursor is not None:
        cursor.close()
        if cursor_path is not None and cursor_path.exists():
            cursor_path.unlink()
    _stamp(eng.records)
    return eng


def _track_row(label, summary, ceiling, random_net, step_flags, note, validate_net, holdout_dates, extra):
    row = {
        "label": label,
        "counted": summary["counted"],
        "days_with_calls": summary["days_with_calls"],
        "gross_mean": summary["gross_mean"],
        "net_mean": summary["net_mean"],
        "net_lb": summary["net_lb"],
        "net_mean_x2": summary["net_mean_x2"],
        "net_mean_x3": summary["net_mean_x3"],
        "random_net": random_net,
        "baselines": summary["baselines"],
        "hit_rate": summary["hit_rate"],
        "hit_lb": summary["hit_lb"],
        "oracle_gross": ceiling.get("gross"),
        "oracle_cost": ceiling.get("cost"),
        "oracle_net": ceiling.get("net"),
        "breakeven_hit_rate": ceiling.get("breakeven_hit_rate"),
        "oracle_wiring_ok": ceiling.get("wiring_ok"),
        "ran": bool(summary["counted"]) and (ceiling.get("net") or 0) > 0,
        "holdout_dates": holdout_dates,
        "wins": summary["wins"],
        "losses": summary["losses"],
        "timeouts": summary["timeouts"],
        "blocked": extra.get("blocked", 0),
        "not_filled": extra.get("not_filled", 0),
        "same_candle_trades": extra.get("agg", 0),
        "same_candle_loss": extra.get("loss_no_trades", 0),
        "maker_fill_winners": extra.get("fill_winners", "n/a"),
        "maker_fill_losers": extra.get("fill_losers", "n/a"),
        "max_dd_r": summary["max_dd_r"],
        "losing_streak": summary["losing_streak"],
        "level": summary["level"],
        "spread_assumed_share": summary["spread_assumed_share"],
        "funding_ignored_share": summary["funding_ignored_share"],
        "flags": step_flags,
        "net_by_month": summary["net_by_month"],
        "validate_net_mean": validate_net,
        "beats_baselines": summary["beats_baselines"],
        "unexplained_flags": summary.get("unexplained_flags") or [],
        "profit_spread_over_months": summary["profit_spread_over_months"],
        "note": note,
    }
    return row


def _fmt_rate(value):
    if value is None:
        return "n/a"
    return f"{value:.4f}"


def execute(argv=None) -> Path:
    del argv
    logging.basicConfig(level=logging.WARNING)
    warn_if_metal_fee_unconfirmed()
    rules = Path("backtest/frozen_rules.json")
    ledger = Path("backtest/holdout_ledger.json")
    # The row was written before the holdout was opened. Do not rewrite the rules file.
    from src.backtest.ledger import rules_hash

    digest = rules_hash(rules)
    if digest != "5e6a8e984c229ea885783cb452187e67896df0d04866ee70e8b3e17bf91f8f73":
        raise SystemExit(f"frozen rules hash drifted: {digest}")
    register_holdout(ledger, rules, "2022-11-01", "2024-11-01", ["BTCUSDT", "XAUUSDT"])
    print("ledger row written; holdout not opened yet", flush=True)

    spread = assumed_spread_pct()
    trend_cost = round_trip_cost("CRYPTO", "futures", "taker", spread)
    timeout_cost = float(scalp_outcome_cost("TIMEOUT", "futures", spread))

    print("sanity 2024-11 to 2026-05", flush=True)
    dev, _gap = _load("BTCUSDT", "2024-11", "2026-05", _ms("2024-11-01"), _ms("2026-06-01"))
    dev_funding = [(t, r) for t, r in load_funding(ROOT, "BTCUSDT", "2024-11", "2026-05") if _ms("2024-11-01") <= t < _ms("2026-06-01")]
    _engines(dev, dev_funding, trend_cost)
    del dev
    print("sanity finished; those numbers are discarded", flush=True)

    ensure_klines(ROOT, "BTCUSDT", "futures", "2022-11", "2024-10")
    ensure_funding(ROOT, "BTCUSDT", "2022-11", "2024-10")
    candles, missing = _load("BTCUSDT", "2022-11", "2024-10", _ms("2022-11-01"), _ms("2024-11-01"))
    span = max(1, (candles[-1]["timestamp"] - candles[0]["timestamp"]) // 60_000)
    gap_ratio = missing / span
    funding = [(t, r) for t, r in load_funding(ROOT, "BTCUSDT", "2022-11", "2024-10") if _ms("2022-11-01") <= t < _ms("2024-11-01")]
    print(f"holdout candles {len(candles)} missing {missing}", flush=True)
    engines = _engines(candles, funding, trend_cost)
    pairs = {60: window_pairs(candles, 60), 240: window_pairs(candles, 240)}
    ceilings = {
        60: window_oracle(pairs[60][0], pairs[60][1], trend_cost),
        240: window_oracle(pairs[240][0], pairs[240][1], trend_cost),
    }
    x1_ceiling = window_oracle(pairs[60][0], pairs[60][1], timeout_cost)
    print("loading gold", flush=True)
    for _month, _part in iter_symbol_months(ROOT, "XAUUSDT", "futures", "2025-12", "2026-10"):
        pass
    gold, gold_missing = _load("XAUUSDT", "2025-12", "2026-10", None, _ms("2026-11-01"))
    from src.backtest.runner import split_bounds, which_split

    gold_bounds = split_bounds("2025-12", "2026-10")
    gold_hold = [c for c in gold if which_split(int(c["timestamp"]), gold_bounds) == "holdout"]
    gold_pairs = window_pairs(gold_hold, 60)
    x2_ceiling = window_oracle(gold_pairs[0], gold_pairs[1], timeout_cost)

    trunc_ok = truncation_voter(
        candles[:8000],
        voter="markov",
        window_ms=3_600_000,
        bucket_ms=300_000,
        lookback=500,
        cost=trend_cost,
    )
    entry_ok = True
    for engine in engines:
        for record in engine.records:
            if record.get("counts_for_graduation") and record.get("entry_time") != record.get("signal_time"):
                entry_ok = False
    slots = [{"entry": a, "verify": b, "cost": trend_cost} for a, b in zip(pairs[60][0], pairs[60][1])]
    random_btc = random_control(slots, min(2000, len(slots)), seed=1)
    step = evaluate_step1(
        random_ctrl=random_btc,
        oracles=[ceilings[60], ceilings[240], x1_ceiling, x2_ceiling],
        truncation_ok=trunc_ok,
        entry_ok=entry_ok,
        cost_ok=trend_cost > 0 and timeout_cost > 0,
        ledger_ok=True,
        same_candle_reported=True,
        gap_ratio=gap_ratio,
        rule_sets_tried=2,
        k=K,
        z=Z,
    )
    print(
        "step1",
        step["step1_ok"],
        "ceilings",
        ceilings[60].get("net"),
        ceilings[240].get("net"),
        x1_ceiling.get("net"),
        x2_ceiling.get("net"),
        flush=True,
    )
    days = _days("2022-11-01", "2024-11-01")
    tracks = []
    for engine, (spec_id, label, _voter, window_min, _bar) in zip(engines, SPECS):
        ceiling = ceilings[window_min]
        use = engine.records if step["step1_ok"] and (ceiling.get("net") or 0) > 0 else []
        summary = summarize(use, Z, days, False, len(funding) == 0)
        flags, unexplained = collect_flags(summary, None, None, False)
        summary["unexplained_flags"] = unexplained
        ctrl = random_control(
            [{"entry": a, "verify": b, "cost": trend_cost} for a, b in zip(pairs[window_min][0], pairs[window_min][1])],
            summary["counted"] if summary["counted"] >= 30 else min(2000, len(pairs[window_min][0])),
            seed=1,
        )
        note = None if use else "Window oracle net is not above the cost, so the voter was not judged."
        if not step["step1_ok"]:
            note = "An honesty check failed. The voter is not judged."
        tracks.append(
            _track_row(
                label,
                summary,
                ceiling,
                ctrl.get("net_mean"),
                flags,
                note,
                None,
                "2022-11-01 → 2024-11-01. Validate: n/a. 2024-11 to 2026-05 was a sanity check only.",
                {},
            )
        )

    def _maybe_scalp(name, ceiling, candles_in, symbol, tick, asset_class, fund, months, judged, days_list, validate_of, dates, note, slots):
        run = None
        if step["step1_ok"] and (ceiling.get("net") or 0) > 0:
            print(f"{name} ceiling clears cost", flush=True)
            run = _walk_scalp(candles_in, symbol, tick, asset_class, fund, months[0], months[1])
        records = []
        validate_net = None
        if run is not None:
            records = [r for r in run.records if judged(r)]
            if validate_of is not None:
                valid_records = [r for r in run.records if validate_of(r)]
                validate_net = summarize(valid_records, Z, [], True, len(fund) == 0)["net_mean"]
        summary = summarize(records, Z, days_list, True, len(fund) == 0)
        flags, unexplained = collect_flags(summary, None, {"net_mean": validate_net} if validate_net is not None else None, True)
        summary["unexplained_flags"] = unexplained
        rates = fill_rate_summary(run.would_be) if run is not None else {"winners": None, "losers": None}
        extra = {
            "blocked": run.blocked if run else 0,
            "not_filled": run.not_filled if run else 0,
            "agg": run.same_candle_trades if run else 0,
            "loss_no_trades": run.same_candle_loss if run else 0,
            "fill_winners": _fmt_rate(rates["winners"]),
            "fill_losers": _fmt_rate(rates["losers"]),
        }
        ctrl = random_control(slots, summary["counted"] if summary["counted"] >= 30 else min(2000, len(slots)), seed=1)
        return _track_row(name, summary, ceiling, ctrl.get("net_mean"), flags, note, validate_net, dates, extra)

    tracks.append(
        _maybe_scalp(
            "X1 BTC EXTENDED",
            x1_ceiling,
            candles,
            "BTCUSDT",
            0.1,
            "CRYPTO",
            funding,
            ("2022-11", "2024-10"),
            lambda _r: True,
            days,
            None,
            "2022-11-01 → 2024-11-01. Validate: n/a. 2024-11 to 2026-05 was a sanity check only.",
            None if (x1_ceiling.get("net") or 0) > 0 else "Window oracle net is not above the cost, so the scalp was not run.",
            [{"entry": a, "verify": b, "cost": timeout_cost} for a, b in zip(pairs[60][0], pairs[60][1])],
        )
    )
    gold_funding = load_funding(ROOT, "XAUUSDT", "2025-12", "2026-10")
    x2_run_records_validate_net = None
    # Validate net is filled after the walk, inside _maybe_scalp we only have holdout records.
    # Run gold once by calling _maybe_scalp, then if it ran the validate slice is inside that walk.
    # _maybe_scalp walks the candles it is given. Pass the full gold series and filter holdout.
    def _gold_judged(record):
        return which_split(int(record["signal_time"]), gold_bounds) == "holdout"

    tracks.append(
        _maybe_scalp(
            "X2 GOLD EXTENDED",
            x2_ceiling,
            gold,
            "XAUUSDT",
            0.01,
            "SCALP_METAL",
            gold_funding,
            ("2025-12", "2026-10"),
            _gold_judged,
            _days(gold_bounds["valid_end"].strftime("%Y-%m-%d"), gold_bounds["end"].strftime("%Y-%m-%d")),
            lambda record: which_split(int(record["signal_time"]), gold_bounds) == "validate",
            (
                f"Gold archive 2025-12 → 2026-11-01, split 60/20/20. "
                f"Holdout {gold_bounds['valid_end'].strftime('%Y-%m-%d')} → {gold_bounds['end'].strftime('%Y-%m-%d')}. "
                "The archive is short, so TOO EARLY is the expected honest result. This is not a quiet pass."
            ),
            "Gold archive starts 2025-12. The 20% holdout is a short sample. TOO EARLY is expected when the count or the days fall short. "
            "XAUUSDT fee was not confirmed; using FEE_FUT_MAKER and FEE_FUT_TAKER.",
            [{"entry": a, "verify": b, "cost": timeout_cost} for a, b in zip(gold_pairs[0], gold_pairs[1])],
        )
    )

    print("seen period", flush=True)
    seen_candles, _sm = _load("BTCUSDT", "2026-06", "2026-10", _ms("2026-06-08"), _ms("2026-11-01"))
    seen_funding = [(t, r) for t, r in load_funding(ROOT, "BTCUSDT", "2026-06", "2026-10") if _ms("2026-06-08") <= t < _ms("2026-11-01")]
    seen_engines = _engines(seen_candles, seen_funding, trend_cost)
    seen_days = _days("2026-06-08", "2026-11-01")
    seen = []
    for engine, (_i, label, *_rest) in zip(seen_engines, SPECS):
        summary = summarize(engine.records, Z, seen_days, False, len(seen_funding) == 0)
        seen.append({"label": label, "counted": summary["counted"], "net_mean": summary["net_mean"]})
    seen_pairs = window_pairs(seen_candles, 60)
    seen.append({"label": "X1 BTC EXTENDED ceiling", "counted": window_oracle(seen_pairs[0], seen_pairs[1], timeout_cost)["n"], "net_mean": window_oracle(seen_pairs[0], seen_pairs[1], timeout_cost)["net"]})
    seen_gold = [c for c in gold if _ms("2026-06-08") <= int(c["timestamp"]) < _ms("2026-11-01")]
    gp = window_pairs(seen_gold, 60)
    seen.append({"label": "X2 GOLD EXTENDED ceiling", "counted": window_oracle(gp[0], gp[1], timeout_cost)["n"], "net_mean": window_oracle(gp[0], gp[1], timeout_cost)["net"]})

    run1 = Path("reports/backtest_2026-11-11.md")
    result = {
        "K": K,
        "z": Z,
        "rule_sets_tried": 2,
        "step1_ok": step["step1_ok"],
        "step1": step["step1"],
        "tracks": tracks,
        "seen_tracks": seen,
        "run1_text": run1.read_text() if run1.exists() else "",
        "scope": [
            "Rule set 2. K = 6. z = 3.09. rule_sets_tried = 2. The second try is this pre-registered set, not a search.",
            "Develop months 2024-11 to 2026-05 were a sanity check. The engine finished. Those numbers are not a verdict.",
            "The new holdout is 2022-11-01 to 2024-11-01 (end exclusive). The ledger row was written before that sample was read. It was run once.",
            "2026-06-08 to 2026-11-01 is the seen period. It is not evidence and it is not in the ledger.",
            "Trend is BTCUSDT USD-M perpetual, taker in and taker out, entry at the next 1m open, exit at the window end, funding applied.",
            "Lens input is 500 closed bars resampled from closed 1m candles: 5m for the 1h window, 15m for the 4h window. SIDEWAYS is stored and not counted.",
            "Markov window 20, MARKOV_K 1.0, RSI 14, MACD 12/26/9, Bollinger 20/2. One voter. No weight modulation.",
            "S1 and S2 are maker EXTENDED scalps (frozen ids X1 and X2). Trigger is the cost gate, then the setup score, then the ensemble or the delta. The delta is aggTrade buy versus sell volume over the last 3 closed 1m candles. No bookTicker. QUICK is not mixed in.",
            "WIN pays maker + maker. LOSS and TIMEOUT pay maker + taker. Spread 0.0001 is assumed because the bookTicker archive returns 404. Slippage is 0.0001.",
            "fapi.binance.com exchangeInfo returned HTTP 451. Tick sizes BTCUSDT 0.10 and XAUUSDT 0.01 were not tuned.",
            "The metal fee was not confirmed. Gold uses FEE_FUT_MAKER and FEE_FUT_TAKER.",
            f"Gold missing minutes in the loaded archive: {gold_missing}. No news calendar, so blackout is false. AI and visual lenses stay excluded.",
        ],
    }
    text = render_run2(result)
    today = datetime.now(timezone.utc).astimezone(DUBAI).strftime("%Y-%m-%d")
    report = Path("reports") / f"backtest_{today}_run2.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(text)
    Path("reports", f"backtest_{today}_run2.json").write_text(json.dumps(result, indent=2, default=str))
    print(report, flush=True)
    return report
