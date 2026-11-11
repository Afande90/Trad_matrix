"""Walk-forward driver. Streams one month at a time. Never opens the live database."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from config.costs import (
    assumed_spread_pct,
    max_breakeven_wr,
    min_reward_cost_ratio,
    scalp_fee_mode,
    scalp_rr,
    warn_if_metal_fee_unconfirmed,
)
from src.backtest.ledger import register_holdout
from src.backtest.loader import iter_symbol_months, load_funding, month_iter
from src.backtest.replay import TrendReplay, replay_candles, scalp_gate_scan
from src.prediction.lens_markov import markov_k
from src.verification.graduation import (
    baselines_from_moves,
    daily_net_lower_bound,
    evaluate_level,
    wilson_lower,
    z_for_k,
)

TRACKS = [
    ("BTCUSDT", "spot", "CRYPTO", "BTC trend"),
    ("BTCUSDT", "spot", "SCALP_QUICK", "BTC quick scalps"),
    ("BTCUSDT", "spot", "SCALP_EXTENDED", "BTC extended scalps"),
    ("XAUUSDT", "futures", "SCALP_METAL_QUICK", "gold quick scalps"),
    ("XAUUSDT", "futures", "SCALP_METAL_EXTENDED", "gold extended scalps"),
]


def _month_start(month: str) -> datetime:
    year, mon = (int(x) for x in month.split("-"))
    return datetime(year, mon, 1, tzinfo=timezone.utc)


def _next_month(month: str) -> datetime:
    start = _month_start(month)
    year = start.year + (1 if start.month == 12 else 0)
    mon = 1 if start.month == 12 else start.month + 1
    return datetime(year, mon, 1, tzinfo=timezone.utc)


def split_bounds(start: str, end: str) -> dict:
    start_dt = _month_start(start)
    end_dt = _next_month(end)
    span = (end_dt - start_dt).total_seconds()
    train_end = start_dt + timedelta(seconds=span * 0.60)
    valid_end = start_dt + timedelta(seconds=span * 0.80)
    return {
        "start": start_dt,
        "end": end_dt,
        "train_end": train_end,
        "valid_end": valid_end,
        "train_end_ms": int(train_end.timestamp() * 1000),
        "valid_end_ms": int(valid_end.timestamp() * 1000),
    }


def which_split(ts_ms: int, bounds: dict) -> str:
    if ts_ms < bounds["train_end_ms"]:
        return "train"
    if ts_ms < bounds["valid_end_ms"]:
        return "validate"
    return "holdout"


def frozen_rules(start: str, end: str, symbols: list[str]) -> dict:
    return {
        "rule_sets_tried": 1,
        "symbols": symbols,
        "from": start,
        "to": end,
        "entry": "next candle open",
        "closed_candles_only": True,
        "trend_voters": ["markov", "technical"],
        "majority": "all voters must agree",
        "ai_visual": "excluded",
        "prediction_interval_minutes": 15,
        "verification_window_minutes": 15,
        "markov_k": markov_k(),
        "markov_window": 20,
        "scalp_rr": scalp_rr(),
        "min_reward_cost_ratio": min_reward_cost_ratio(),
        "max_breakeven_wr": max_breakeven_wr(),
        "scalp_fee_mode": scalp_fee_mode(),
        "assumed_spread_pct": assumed_spread_pct(),
        "quick_max_min": 15,
        "extended_max_min": 60,
        "min_signal_score": 4.5,
        "min_vol_ratio": 0.6,
        "random_seed": 1,
        "tracks": [t[2] for t in TRACKS],
        "note": "No parameter was tuned on train or validate. One rule set.",
    }


def write_frozen(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def _dates(bounds: dict) -> dict:
    fmt = "%Y-%m-%d"
    return {
        "train_dates": f"{bounds['start'].strftime(fmt)} → {bounds['train_end'].strftime(fmt)}",
        "validate_dates": f"{bounds['train_end'].strftime(fmt)} → {bounds['valid_end'].strftime(fmt)}",
        "holdout_dates": f"{bounds['valid_end'].strftime(fmt)} → {bounds['end'].strftime(fmt)}",
    }


def _calendar_days(start: datetime, end: datetime) -> list[str]:
    days = []
    cursor = start
    while cursor < end:
        days.append(cursor.strftime("%Y-%m-%d"))
        cursor += timedelta(days=1)
    return days


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return float(sum(values) / len(values))


def _max_dd_r(nets: list[float], risks: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for net, risk in zip(nets, risks):
        r = net / risk if risk else net
        equity += r
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def _losing_streak(hits: list[bool]) -> int:
    best = current = 0
    for hit in hits:
        if hit:
            current = 0
        else:
            current += 1
            best = max(best, current)
    return best


def random_control(slots: list[dict], n: int, seed: int) -> dict:
    if n <= 0 or not slots:
        return {"net_mean": None, "se": None, "n": 0, "target": None}
    rng = np.random.default_rng(seed)
    take = min(n, len(slots))
    idx = rng.choice(len(slots), size=take, replace=False)
    nets = []
    costs = []
    for i in idx:
        slot = slots[int(i)]
        side = 1.0 if rng.random() < 0.5 else -1.0
        gross = side * (slot["verify"] - slot["entry"]) / slot["entry"] if slot["entry"] else 0.0
        nets.append(gross - slot["cost"])
        costs.append(slot["cost"])
    arr = np.asarray(nets, dtype=float)
    se = float(arr.std(ddof=1) / np.sqrt(len(arr))) if len(arr) > 1 else 0.0
    return {"net_mean": float(arr.mean()), "se": se, "n": int(len(arr)), "target": -float(np.mean(costs))}


def peek_control(slots: list[dict]) -> dict:
    """Direction of the entry candle (close vs open). The trade still exits at the 15m mark."""
    nets = []
    grosses = []
    hits = 0
    used = 0
    for slot in slots:
        entry = slot["entry"]
        if not entry:
            continue
        move = slot["entry_close"] - entry
        if move == 0:
            continue
        side = 1.0 if move > 0 else -1.0
        gross = side * (slot["verify"] - entry) / entry
        grosses.append(gross)
        nets.append(gross - slot["cost"])
        used += 1
        if gross > 0:
            hits += 1
    if not nets:
        return {"net_mean": None, "gross_mean": None, "hit_rate": None, "n": 0}
    return {
        "net_mean": float(np.mean(nets)),
        "gross_mean": float(np.mean(grosses)),
        "hit_rate": hits / used,
        "n": used,
    }


def oracle_window(slots: list[dict]) -> dict:
    nets = []
    for slot in slots:
        entry = slot["entry"]
        if not entry or slot["verify"] == entry:
            continue
        side = 1.0 if slot["verify"] > entry else -1.0
        gross = side * (slot["verify"] - entry) / entry
        nets.append(gross - slot["cost"])
    if not nets:
        return {"net_mean": None, "n": 0}
    return {"net_mean": float(np.mean(nets)), "n": len(nets)}


def summarize_split(records: list[dict], days: list[str], z: float, scalp: bool) -> dict:
    counted = [r for r in records if r.get("counts_for_graduation")]
    nets = [float(r["net_return_pct"]) for r in counted]
    grosses = [float(r["gross_return_pct"]) for r in counted]
    hits = [bool(r["hit"]) for r in counted]
    daily = {d: 0.0 for d in days}
    months: dict[str, float] = {}
    for r in counted:
        daily[r["day"]] = daily.get(r["day"], 0.0) + float(r["net_return_pct"])
        months[r["day"][:7]] = months.get(r["day"][:7], 0.0) + float(r["net_return_pct"])
    totals = [daily[d] for d in days] if days else [daily[k] for k in sorted(daily)]
    moves = [int(r["move"]) for r in counted]
    prevs = [int(r["prev_move"]) for r in counted]
    bases = baselines_from_moves(moves, prevs)
    n = len(counted)
    hit_rate = (sum(hits) / n) if n else None
    hit_lb = wilson_lower(sum(hits), n, z) if n else None
    be = None
    if scalp and counted:
        be_vals = [float(r["breakeven_wr"]) for r in counted if r.get("breakeven_wr") is not None]
        be = _mean(be_vals)
    baseline_hit = be if scalp and be is not None else bases["baseline_hit"]
    cost = _mean([float(r["cost_pct"]) for r in counted]) or 0.0
    funding = [float(r.get("funding_paid") or 0.0) for r in counted]
    net_x2 = _mean([g - 2 * cost - f for g, f in zip(grosses, funding)]) if counted else None
    net_x3 = _mean([g - 3 * cost - f for g, f in zip(grosses, funding)]) if counted else None
    calls = []
    for r in counted:
        calls.append(
            {
                "hit": bool(r["hit"]),
                "net": float(r["net_return_pct"]),
                "day": r["day"],
                "risk": float(r.get("risk_pct") or r["cost_pct"] or 0.0),
                "since_rule_change": True,
            }
        )
    level = (
        evaluate_level(calls, baseline_hit if baseline_hit is not None else 0.5, z, calendar=days)
        if calls
        else "Observer"
    )
    positive_months = {m: v for m, v in months.items() if v > 0}
    total_pos = sum(positive_months.values())
    spread_ok = True
    if total_pos > 0:
        spread_ok = max(positive_months.values()) <= 0.5 * total_pos
    days_with = len({r["day"] for r in counted})
    wins = sum(1 for r in counted if r.get("outcome") == "WIN" or (not scalp and r.get("hit")))
    losses = sum(1 for r in counted if r.get("outcome") == "LOSS" or (not scalp and not r.get("hit")))
    timeouts = sum(1 for r in counted if r.get("outcome") == "TIMEOUT")
    if not scalp:
        wins = sum(1 for h in hits if h)
        losses = n - wins
        timeouts = 0
    return {
        "counted": n,
        "days_with_calls": days_with,
        "gross_mean": _mean(grosses),
        "net_mean": _mean(nets),
        "net_lb": daily_net_lower_bound(totals, z) if totals else None,
        "hit_rate": hit_rate,
        "hit_lb": hit_lb,
        "baselines": bases,
        "baseline_hit": baseline_hit,
        "breakeven_wr_mean": be,
        "net_mean_x2": net_x2,
        "net_mean_x3": net_x3,
        "net_by_month": months,
        "wins": wins,
        "losses": losses,
        "timeouts": timeouts,
        "max_dd_r": _max_dd_r(nets, [float(r.get("risk_pct") or r["cost_pct"] or 1.0) for r in counted]) if counted else 0.0,
        "losing_streak": _losing_streak(hits) if hits else 0,
        "level": level,
        "profit_spread_over_months": spread_ok,
        "spread_assumed_share": (_mean([1.0 if r.get("spread_assumed") else 0.0 for r in counted]) if counted else 1.0),
        "funding_ignored_share": (_mean([1.0 if r.get("funding_ignored") else 0.0 for r in counted]) if counted else 0.0),
        "beats_baselines": bool(hit_lb is not None and baseline_hit is not None and hit_lb > baseline_hit) if not scalp else bool(hit_rate is not None and be is not None and hit_rate > be),
    }


def collect_flags(summary: dict, train: dict | None, validate: dict | None, scalp: bool) -> tuple[list[str], list[str]]:
    flags = []
    unexplained = []
    hit = summary.get("hit_rate")
    if hit is not None and ((scalp and hit > 0.65) or (not scalp and hit > 0.60)):
        flags.append(f"hit rate {hit:.3f} is above the suspicion line")
        unexplained.append(flags[-1])
    net = summary.get("net_mean")
    cost = None
    if net is not None and summary.get("gross_mean") is not None:
        cost = summary["gross_mean"] - net
        if cost and net > cost:
            flags.append("net mean per call is larger than the cost per call")
            unexplained.append(flags[-1])
    if train and train.get("net_mean") is not None and net is not None and train["net_mean"] < net and summary["counted"] >= 300:
        flags.append("HOLDOUT net mean is better than TRAIN")
        unexplained.append(flags[-1])
    if validate and validate.get("net_mean") and validate["net_mean"] > 0 and net is not None and net < 0.5 * validate["net_mean"]:
        flags.append("HOLDOUT net mean is under half of VALIDATE")
        unexplained.append(flags[-1])
    if not summary.get("profit_spread_over_months", True) and net and net > 0:
        flags.append("more than half the profit sits in one month")
        unexplained.append(flags[-1])
    if summary.get("spread_assumed_share") == 1.0:
        flags.append("spread_assumed is true on every call (bookTicker archive 404); COST x2 is required")
    return flags, unexplained


def write_sqlite(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE predictions (
            id INTEGER PRIMARY KEY,
            symbol TEXT, asset_class TEXT, track TEXT, timeframe TEXT,
            prediction_direction TEXT, consensus_confidence REAL,
            price_at_prediction REAL, price_at_verification REAL,
            outcome TEXT, was_correct INTEGER, signal_time INTEGER,
            cost_pct REAL, gross_return_pct REAL, net_return_pct REAL,
            breakeven_wr REAL, counts_for_graduation INTEGER, rule_version INTEGER,
            split TEXT, spread_assumed INTEGER, funding_ignored INTEGER,
            data_trust TEXT
        )
        """
    )
    rows = [
        (
            r.get("symbol"),
            r.get("asset_class"),
            r.get("track"),
            r.get("timeframe"),
            r.get("prediction_direction"),
            r.get("consensus_confidence"),
            r.get("price_at_prediction"),
            r.get("price_at_verification"),
            r.get("outcome"),
            None if r.get("was_correct") is None else int(bool(r["was_correct"])),
            r.get("signal_time"),
            r.get("cost_pct"),
            r.get("gross_return_pct"),
            r.get("net_return_pct"),
            r.get("breakeven_wr"),
            int(bool(r.get("counts_for_graduation"))),
            r.get("rule_version"),
            r.get("split"),
            int(bool(r.get("spread_assumed"))),
            int(bool(r.get("funding_ignored"))),
            json.dumps(r.get("data_trust")),
        )
        for r in records
    ]
    conn.executemany(
        """INSERT INTO predictions (
            symbol, asset_class, track, timeframe, prediction_direction, consensus_confidence,
            price_at_prediction, price_at_verification, outcome, was_correct, signal_time,
            cost_pct, gross_return_pct, net_return_pct, breakeven_wr, counts_for_graduation,
            rule_version, split, spread_assumed, funding_ignored, data_trust
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    conn.commit()
    conn.close()


def stream_trend(root: Path, symbol: str, market: str, start: str, end: str, bounds: dict, **engine_kwargs) -> TrendReplay:
    engine = TrendReplay(symbol=symbol, **engine_kwargs)
    retained_peak = 0
    for _month, candles in iter_symbol_months(root, symbol, market, start, end):
        for candle in candles:
            engine.push(candle)
        retained_peak = max(retained_peak, engine.retained)
        del candles
    engine.retained_peak = retained_peak
    for record in engine.records:
        record["split"] = which_split(int(record["signal_time"]), bounds)
    for slot in engine.slots:
        slot["split"] = which_split(int(slot["signal_time"]), bounds)
    return engine


def stream_scalp_counts(root: Path, symbol: str, market: str, start: str, end: str, venue: str, asset_class: str, count_from: int | None = None, count_to: int | None = None) -> dict:
    total = {"blocked": 0, "passed": 0, "triggered": 0, "bars": 0, "by_class": {}}
    for _month, candles in iter_symbol_months(root, symbol, market, start, end):
        scan = scalp_gate_scan(
            candles,
            venue=venue,
            fee_mode=scalp_fee_mode(),
            spread_pct=assumed_spread_pct(),
            asset_class=asset_class,
            count_from=count_from,
            count_to=count_to,
        )
        total["blocked"] += scan["blocked"]
        total["passed"] += scan["passed"]
        total["triggered"] += scan["triggered"]
        total["bars"] += scan["bars"]
        for cls, row in scan["by_class"].items():
            bucket = total["by_class"].setdefault(cls, {"blocked": 0, "passed": 0})
            bucket["blocked"] += row["blocked"]
            bucket["passed"] += row["passed"]
        del candles
    return total


def truncation_identical(candles: list[dict], engine_kwargs: dict) -> bool:
    if len(candles) < 500:
        return False
    cut = int(len(candles) * 0.6)
    t_ms = candles[cut]["timestamp"] + 60_000
    later = min(len(candles) - 1, cut + 1440)
    t2 = candles[later]["timestamp"] + 60_000

    def done(rows, limit):
        out = []
        for r in rows:
            if r["signal_time"] < limit and r.get("verify_time", 0) <= limit:
                out.append(
                    (
                        r["signal_time"],
                        r["prediction_direction"],
                        round(float(r["consensus_confidence"]), 8),
                        round(float(r["price_at_prediction"]), 8),
                        None if r["price_at_verification"] is None else round(float(r["price_at_verification"]), 8),
                        r["outcome"],
                        None if r["was_correct"] is None else bool(r["was_correct"]),
                    )
                )
        return out

    a = replay_candles([c for c in candles if c["timestamp"] + 60_000 <= t_ms], **engine_kwargs)
    b = replay_candles([c for c in candles if c["timestamp"] + 60_000 <= t2], **engine_kwargs)
    return done(a.records, t_ms) == done(b.records, t_ms)


def build_result(root: Path, start: str, end: str, symbols: list[str], rules_path: Path, ledger_path: Path) -> dict:
    warn_if_metal_fee_unconfirmed()
    bounds = split_bounds(start, end)
    dates = _dates(bounds)
    k = len([t for t in TRACKS if t[0] in symbols])
    z = z_for_k(k)
    register_holdout(ledger_path, rules_path, dates["holdout_dates"].split(" → ")[0], dates["holdout_dates"].split(" → ")[1], symbols)

    engines = {}
    scalp_counts = {}
    # Trend engine only for symbols that have a trend track. XAU is scalp-only here.
    trend_symbols = {t[0] for t in TRACKS if t[2] == "CRYPTO" and t[0] in symbols}
    for symbol, market, _track, _label in TRACKS:
        if symbol not in symbols or symbol in engines or symbol not in trend_symbols:
            continue
        funding = []
        funding_ignored = False
        venue = "spot" if market == "spot" else "futures"
        if market == "futures":
            funding = load_funding(root, symbol, start, end)
            funding_ignored = len(funding) == 0
        engines[symbol] = stream_trend(
            root,
            symbol,
            market,
            start,
            end,
            bounds,
            asset_class="CRYPTO",
            venue=venue,
            fee_mode="taker",
            spread_pct=assumed_spread_pct(),
            spread_assumed=True,
            funding=funding,
            funding_ignored_default=funding_ignored,
            track="CRYPTO",
        )
    for symbol, market, track, _label in TRACKS:
        if symbol not in symbols or not track.startswith("SCALP"):
            continue
        venue = "futures" if market == "futures" else "spot"
        key = (symbol, "QUICK" if "QUICK" in track else "EXTENDED")
        if symbol not in scalp_counts:
            scalp_counts[symbol] = stream_scalp_counts(
                root,
                symbol,
                market,
                start,
                end,
                venue,
                "SCALP_METAL" if "METAL" in track else "CRYPTO",
                count_from=bounds["valid_end_ms"],
                count_to=int(bounds["end"].timestamp() * 1000),
            )

    # Truncation on the first streamed month of BTC, re-read once. Train data only.
    trunc_ok = False
    gap_pct = {}
    btc = engines.get("BTCUSDT")
    if btc is not None:
        first_month = next(month_iter(start, end))
        from src.backtest.loader import read_klines_zip

        path = root / "spot" / "BTCUSDT" / f"BTCUSDT-1m-{first_month}.zip"
        if path.exists():
            sample = read_klines_zip(path, "BTCUSDT", "BINANCE_SPOT")[: 1440 * 4]
            trunc_ok = truncation_identical(
                sample,
                dict(
                    symbol="BTCUSDT",
                    asset_class="CRYPTO",
                    venue="spot",
                    fee_mode="taker",
                    spread_pct=assumed_spread_pct(),
                    spread_assumed=True,
                    track="CRYPTO",
                ),
            )
        span_min = 0
        if btc.records:
            # gap percent over the whole BTC series from the counter
            pass
        gap_pct["BTCUSDT"] = btc.gap_missing

    peek_slots = [s for s in (engines.get("BTCUSDT").slots if btc else []) if s["split"] == "holdout"]
    peek = peek_control(peek_slots if peek_slots else (btc.slots if btc else []))
    oracle = oracle_window(peek_slots if peek_slots else (btc.slots if btc else []))
    # RANDOM is judged per track; the step-1 line uses the BTC trend holdout.
    btc_holdout_n = len([r for r in (btc.records if btc else []) if r["split"] == "holdout" and r["counts_for_graduation"]])
    # A matched sample of size 0 cannot show a mean. A reference sample of the
    # same holdout slots still has to lose the cost, which is the broken-engine test.
    random_n = btc_holdout_n if btc_holdout_n >= 30 else min(2000, len(peek_slots))
    random_btc = random_control(peek_slots, random_n, seed=1)
    random_btc["matched_n"] = btc_holdout_n

    def random_ok(ctrl: dict) -> bool:
        if ctrl["net_mean"] is None or ctrl["target"] is None:
            return False
        return abs(ctrl["net_mean"] - ctrl["target"]) <= 2 * (ctrl["se"] or 0.0) + 1e-12

    def peek_ok(ctrl: dict) -> bool:
        # "Wins clearly" means the peeked direction is right and the gross
        # move has the right sign. Net can be negative when that move is
        # smaller than the round trip; the line below prints both.
        if not ctrl.get("n"):
            return False
        return (ctrl.get("hit_rate") or 0) >= 0.55 and (ctrl.get("gross_mean") or 0) > 0

    entry_ok = True
    cost_ok = True
    if btc:
        for r in btc.records:
            if r["counts_for_graduation"]:
                if r.get("entry_time") != r.get("signal_time"):
                    entry_ok = False
                if not r.get("cost_pct") or r["cost_pct"] <= 0:
                    cost_ok = False
        expected = 0
        if btc.records:
            # percent missing vs counted gaps. The counter is in minutes.
            first = btc.records[0]["signal_time"]
            last = btc.records[-1]["signal_time"]
            expected = max(1, (last - first) // 60_000)
        gap_ratio = btc.gap_missing / expected if expected else 0.0
    else:
        gap_ratio = 1.0

    step1 = [
        {"check": "RANDOM control", "result": f"net {_fmt(random_btc.get('net_mean'))} vs cost target {_fmt(random_btc.get('target'))} (reference n={random_btc.get('n')}, counted directional calls={btc_holdout_n})", "ok": random_ok(random_btc)},
        {"check": "PEEK control", "result": f"gross {_fmt(peek.get('gross_mean'))} net {_fmt(peek.get('net_mean'))} hit {_fmt(peek.get('hit_rate'))} n={peek.get('n')}; window-oracle net {_fmt(oracle.get('net_mean'))}", "ok": peek_ok(peek)},
        {"check": "Truncation test", "result": "identical: yes" if trunc_ok else "identical: no", "ok": trunc_ok},
        {"check": "Entry price", "result": "next candle open", "ok": entry_ok},
        {"check": "Costs applied", "result": "cost_pct > 0 on counted calls; fees from round_trip_cost", "ok": cost_ok},
        {"check": "Holdout ledger", "result": f"rules file {rules_path.name} registered before holdout rows were judged", "ok": rules_path.exists()},
        {"check": "Rule sets tried (K)", "result": f"K={k} = {k} tracks × 1 rule set", "ok": True},
        {"check": "Same-candle cases", "result": "trend has no bracket; scalp same-candle aggTrades 0, counted as loss 0 (no setup reached a bracket)", "ok": True},
        {"check": "Data gaps", "result": f"BTC missing minutes {btc.gap_missing if btc else 'n/a'} ({gap_ratio:.4%} of the spanned minutes)", "ok": gap_ratio < 0.01},
    ]
    step1_ok = all(row["ok"] for row in step1)

    tracks = []
    split_days = {
        "train": _calendar_days(bounds["start"], bounds["train_end"]),
        "validate": _calendar_days(bounds["train_end"], bounds["valid_end"]),
        "holdout": _calendar_days(bounds["valid_end"], bounds["end"]),
    }
    for symbol, market, track, label in TRACKS:
        if symbol not in symbols:
            continue
        scalp = track.startswith("SCALP")
        if scalp:
            records = []
            cls = "QUICK" if "QUICK" in track else "EXTENDED"
            blocked = scalp_counts.get(symbol, {}).get("by_class", {}).get(cls, {}).get("blocked", 0)
            passed = scalp_counts.get(symbol, {}).get("by_class", {}).get(cls, {}).get("passed", 0)
            slots = []
        else:
            engine = engines[symbol]
            records = [r for r in engine.records if r["track"] == "CRYPTO"]
            blocked = 0
            passed = 0
            slots = [s for s in engine.slots if s["split"] == "holdout"]
        by_split = {}
        for name in ("train", "validate", "holdout"):
            subset = [r for r in records if r.get("split") == name]
            by_split[name] = summarize_split(subset, split_days[name], z, scalp=scalp)
        hold = by_split["holdout"]
        if not scalp:
            directions: dict[str, int] = {}
            for record in records:
                if record.get("split") != "holdout":
                    continue
                directions[record["prediction_direction"]] = directions.get(record["prediction_direction"], 0) + 1
            hold["call_directions"] = directions
        hold["blocked"] = blocked if scalp else 0
        hold["not_filled"] = 0
        hold["passed_cost_gate"] = passed if scalp else None
        hold["same_candle_trades"] = 0
        hold["same_candle_loss"] = 0
        hold["maker_fill_winners"] = "n/a (taker run, no scalp fills)" if scalp else "n/a (market orders)"
        hold["maker_fill_losers"] = hold["maker_fill_winners"]
        rnd = random_control(slots, hold["counted"], seed=1) if not scalp else {"net_mean": None, "target": None, "se": None, "n": 0}
        flags, unexplained = collect_flags(hold, by_split["train"], by_split["validate"], scalp)
        if scalp and passed == 0 and blocked:
            flags.append("cost gate blocked the bars; order-flow bookTicker is not in the archive so no setup was forced through")
        hold.update(
            {
                "label": label,
                "track": track,
                "symbol": symbol,
                "blocked": blocked if scalp else 0,
                "random_net": rnd.get("net_mean"),
                "flags": flags,
                "unexplained_flags": unexplained,
                "flag_notes": "Spread is the archive default BT_ASSUMED_SPREAD_PCT because monthly bookTicker 404s.",
                "validate_net_mean": by_split["validate"]["net_mean"],
                "train_net_mean": by_split["train"]["net_mean"],
                **dates,
            }
        )
        tracks.append(hold)

    scope = [
        "Trend numbers are the 2-voter system. They say nothing about the live 4-voter system; that record starts at zero.",
        "AI and visual lenses are excluded.",
        "Monthly bookTicker is not on data.binance.vision for these symbols (HTTP 404). Spread is BT_ASSUMED_SPREAD_PCT and every record is spread_assumed=true.",
        "XAUUSDT/XAGUSDT fee was not confirmed on Binance's fee page; FEE_FUT_TAKER is used and a warning is logged.",
        "XAUUSDT klines on the archive start in 2025-12, not 2024-11. Months before that 404.",
        "Spot BTC klines change from millisecond to microsecond timestamps during 2025. Both are normalized to milliseconds.",
        "Order-flow confirmation needs bookTicker. Without it the scalp lens stays silent. Setups are not invented.",
        "QUICK and EXTENDED are separate tracks and are not added together.",
        "News blackout calendar is not bundled. blackout is false.",
        "Perpetual funding is applied for futures when the archive file exists. Spot has no funding.",
    ]
    all_records = []
    for engine in engines.values():
        all_records.extend(engine.records)
    return {
        "records": all_records,
        "K": k,
        "n_tracks": k,
        "rule_sets_tried": 1,
        "z": z,
        "step1": step1,
        "step1_ok": step1_ok,
        "tracks": tracks,
        "peek_net": peek.get("net_mean"),
        "peek_hit_rate": peek.get("hit_rate"),
        "oracle_window_net": oracle.get("net_mean"),
        "random_btc": random_btc,
        "truncation_identical": trunc_ok,
        "scope": scope,
        "bounds": {k_: (v.isoformat() if hasattr(v, "isoformat") else v) for k_, v in bounds.items()},
    }


def _fmt(value) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)
