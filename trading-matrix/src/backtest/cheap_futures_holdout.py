"""One frozen cheap-futures holdout. 2025 only. 2026 stays sealed.

The rules file and the ledger row are written by freeze() before any price
is read. The run refuses to start if that hash does not match.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from src.backtest.cheap_futures import (
    HOLD_MS,
    MINUTE_MS,
    RANDOM_SEED,
    WINDOW_MS,
    _exclusive_end,
    _ms,
    align_gaps,
    calendar_days,
    calendar_months,
    data_gaps,
    load_funding_range,
    load_klines,
    losing_streak,
    profit_spread_ok,
    rolling_thresholds,
)
from src.backtest.download import agg_url, ensure_file, ensure_funding, ensure_klines
from src.backtest.fee_limits import (
    FEES,
    WINDOW_FILL_MS,
    fill_rates,
    random_filled_orders,
    scan_limit_fills,
    slot_opens,
    walk_attempts,
)
from src.backtest.ledger import register_holdout, rules_hash
from src.backtest.loader import month_iter
from src.backtest.sentence import cumulative_net_drawdown
from src.verification.graduation import daily_net_lower_bound

ROOT = Path(__file__).resolve().parents[2]
HISTORY = ROOT / "data" / "history"
RULES = ROOT / "backtest" / "frozen_rules.json"
LEDGER = ROOT / "backtest" / "holdout_ledger.json"
REPORT = ROOT / "reports" / "cheap_futures_holdout_2026-11-13"
DUBAI = ZoneInfo("Asia/Dubai")

WARMUP_MONTH = "2024-12"
HOLD_MONTH_END = "2025-12"
SEAL = "2026-01"
HOLDOUT_START = "2025-01-01"
HOLDOUT_END = "2025-12-31"
Z = 3.09
HOLD = "4h"
# Seen-period P2 4h nets from reports/fees_and_markets_2026-11-13.json. Not recomputed.
SEEN_NET = {"F1": 0.00032145074998343276, "F2": 0.0006214507499834327, "F3": 0.0008214507499834329}

RULE_SET_5 = {
    "name": "cheap futures",
    "symbol": "BTCUSDT",
    "market": "USD-M perpetual",
    "gap": "perpetual close / spot close - 1",
    "signal": "gap below the 2nd percentile of the previous 30 days; the current minute is excluded",
    "entry": "limit at the signal minute's close; filled only if aggTrades trade through by one tick (0.10) within 3 minutes, else NOT_FILLED",
    "exit": "market order at the 1m open 4 hours after the fill",
    "one_position_at_a_time": True,
    "funding_applied": True,
    "stop": False,
    "fees": {
        "F1": "limit 0.0002, market 0.0005, spread 0.0001, slippage 0.0001",
        "F2": "limit 0, market 0.0004, spread 0.0001, slippage 0.0001",
        "F3": "limit 0, market 0.0002, spread 0.0001, slippage 0.0001",
    },
    "holdout_start": HOLDOUT_START,
    "holdout_end": HOLDOUT_END,
    "warmup": "2024-12",
    "sealed_from": "2026-01-01",
    "z": Z,
    "note": "Frozen before the 2025 holdout was loaded. One rule. No variant. Paper only if CONTINUE.",
}


def assert_sealed(start_month: str, end_month: str) -> None:
    if start_month >= SEAL or end_month >= SEAL:
        raise RuntimeError("2026-01-01 onward is sealed and was not loaded")
    for month in month_iter(start_month, end_month):
        if month >= SEAL:
            raise RuntimeError("2026-01-01 onward is sealed and was not loaded")


def nets_for(gross: float, funding: float, fee: float) -> tuple[float, float, float]:
    """Funding is charged once. Doubling or tripling the cost does not double the funding."""
    return gross - fee - funding, gross - 2.0 * fee - funding, gross - 3.0 * fee - funding


def freeze() -> dict:
    """Write the frozen rule and the ledger row. Does not read a price."""
    text = RULES.read_text()
    if '"rule_set_5"' not in text:
        if '"rule_sets_tried": 4' not in text:
            raise RuntimeError("frozen_rules.json is not at rule set 4")
        text = text.replace('"rule_sets_tried": 4', '"rule_sets_tried": 5', 1)
        block = json.dumps(RULE_SET_5, indent=2).replace("\n", "\n  ")
        if not text.rstrip().endswith("}"):
            raise RuntimeError("frozen_rules.json has no closing brace")
        body = text.rstrip()
        if body.endswith("}"):
            body = body[:-1].rstrip()
        if not body.endswith(","):
            body += ","
        text = body + '\n  "rule_set_5": ' + block + "\n}\n"
        RULES.write_text(text)
    data = json.loads(RULES.read_text())
    if data.get("rule_sets_tried") != 5 or data.get("rule_set_5", {}).get("z") != Z:
        raise RuntimeError("frozen rule was not written")
    return register_holdout(LEDGER, RULES, HOLDOUT_START, HOLDOUT_END, ["BTCUSDT"])


def require_frozen() -> dict:
    digest = rules_hash(RULES)
    ledger = json.loads(LEDGER.read_text())
    matches = [row for row in ledger["runs"] if row["holdout_start"] == HOLDOUT_START and row["holdout_end"] == HOLDOUT_END]
    if not matches:
        raise RuntimeError("the ledger row is missing; freeze the rule before loading 2025")
    if matches[-1]["rules_hash"] != digest:
        raise RuntimeError("frozen_rules.json changed after the ledger row was written")
    data = json.loads(RULES.read_text())
    if int(data["rule_sets_tried"]) != 5:
        raise RuntimeError("rule_sets_tried is not 5")
    if abs(float(data["rule_set_5"]["z"]) - Z) > 1e-12:
        raise RuntimeError("holdout z is not 3.09")
    return matches[-1]


def p2_signals(gap_ts: np.ndarray, gap: np.ndarray) -> np.ndarray:
    level = rolling_thresholds(gap_ts, gap, WINDOW_MS, (0.02,))[:, 0]
    return gap_ts[np.isfinite(level) & (gap < level)]


def _agg_paths() -> list[Path]:
    assert_sealed(WARMUP_MONTH, HOLD_MONTH_END)
    folder = HISTORY / "aggTrades" / "BTCUSDT"
    paths = []
    for month in month_iter(WARMUP_MONTH, HOLD_MONTH_END):
        dest = folder / f"BTCUSDT-aggTrades-{month}.zip"
        if not dest.exists() or dest.stat().st_size <= 0:
            print(f"download agg {month}", flush=True)
            ensure_file(agg_url("BTCUSDT", month), dest)
        paths.append(dest)
    return paths


def load_market() -> dict:
    assert_sealed(WARMUP_MONTH, HOLD_MONTH_END)
    ensure_klines(HISTORY, "BTCUSDT", "futures", WARMUP_MONTH, HOLD_MONTH_END)
    ensure_klines(HISTORY, "BTCUSDT", "spot", WARMUP_MONTH, HOLD_MONTH_END)
    ensure_funding(HISTORY, "BTCUSDT", WARMUP_MONTH, HOLD_MONTH_END)
    lo = _ms("2024-12-01")
    hi = _ms("2026-01-01")
    futures, fut_missing = load_klines(HISTORY, "futures", WARMUP_MONTH, HOLD_MONTH_END, lo, hi, True)
    spot, spot_missing = load_klines(HISTORY, "spot", WARMUP_MONTH, HOLD_MONTH_END, lo, hi, True)
    fund_ts, fund_rate, fund_missing = load_funding_range(HISTORY, WARMUP_MONTH, HOLD_MONTH_END, lo, hi, True)
    if fut_missing or spot_missing or fund_missing:
        raise RuntimeError(f"missing months futures={fut_missing} spot={spot_missing} funding={fund_missing}")
    gap_ts, gap = align_gaps(futures, spot)
    fut_ts = np.asarray([int(c["timestamp"]) for c in futures], dtype=np.int64)
    if len(fut_ts) and int(fut_ts.max()) >= hi:
        raise RuntimeError("a 2026 timestamp was read")
    if len(gap_ts) and int(gap_ts.max()) >= hi:
        raise RuntimeError("a 2026 gap was read")
    return {
        "fut_ts": fut_ts,
        "fut_open": np.asarray([float(c["open"]) for c in futures], dtype=float),
        "fut_close": np.asarray([float(c["close"]) for c in futures], dtype=float),
        "gap_ts": gap_ts,
        "gap": gap,
        "fund_ts": fund_ts,
        "fund_rate": fund_rate,
        "spot_ts": np.asarray([int(c["timestamp"]) for c in spot], dtype=np.int64),
    }


def _place(by_month: dict, counts: dict) -> dict:
    best = None
    for offset in range(20):
        chosen, short = random_filled_orders(by_month, counts, RANDOM_SEED + offset)
        if best is None or len(chosen) > len(best[0]):
            best = (chosen, short, RANDOM_SEED + offset)
        if not short:
            best = (chosen, short, RANDOM_SEED + offset)
            break
    assert best is not None
    return {"chosen": best[0], "short": best[1], "seed": best[2], "placed": len(best[0]), "requested": int(sum(counts.values()))}


def _candidates(base: int, open_at: np.ndarray, fill: np.ndarray, hold_ms: int, eval_start: int, eval_end: int) -> dict[str, list[tuple[int, int]]]:
    from src.backtest.cheap_futures import _month

    out: dict[str, list[tuple[int, int]]] = {}
    for slot in range(len(fill)):
        filled_at = int(fill[slot])
        if filled_at == 0:
            continue
        close_ts = (base + slot) * MINUTE_MS + MINUTE_MS
        if close_ts < eval_start or close_ts >= eval_end:
            continue
        target = filled_at + hold_ms
        rem = target % MINUTE_MS
        exit_ts = target if rem == 0 else target + (MINUTE_MS - rem)
        if exit_ts >= eval_end:
            continue
        slot_exit = exit_ts // MINUTE_MS - base
        if slot_exit < 0 or slot_exit >= len(open_at):
            continue
        px = float(open_at[slot_exit])
        if px != px or px <= 0.0:
            continue
        out.setdefault(_month(close_ts), []).append((close_ts, exit_ts))
    return out


def summarize(rows: list[dict], fee: float, days: list[str], months: list[str]) -> dict:
    counted = [row for row in rows if row["status"] == "filled" and row["gross"] is not None]
    rates = fill_rates(rows)
    nets, nets_x2, nets_x3, grosses = [], [], [], []
    by_month = {month: 0.0 for month in months}
    daily = {day: 0.0 for day in days}
    for row in counted:
        gross = float(row["gross"])
        funding = float(row["funding"])
        net, net_x2, net_x3 = nets_for(gross, funding, fee)
        grosses.append(gross)
        nets.append(net)
        nets_x2.append(net_x2)
        nets_x3.append(net_x3)
        by_month[row["month"]] = by_month.get(row["month"], 0.0) + net
        daily[row["day"]] = daily.get(row["day"], 0.0) + net
    totals = [daily[day] for day in days]
    trades = len(counted)
    cumulative = float(sum(nets)) if nets else 0.0
    drawdown = cumulative_net_drawdown(nets) if nets else 0.0
    return {
        "trades": trades,
        "days_with_trades": len({row["day"] for row in counted}),
        "not_filled": sum(1 for row in rows if row["status"] == "not_filled"),
        "unscored": sum(1 for row in rows if row["status"] == "unscored"),
        "fill_rate_winners": rates["winners"],
        "fill_rate_losers": rates["losers"],
        "gross_mean": (sum(grosses) / trades) if trades else None,
        "net_mean": (sum(nets) / trades) if trades else None,
        "net_lb": daily_net_lower_bound(totals, Z) if totals else None,
        "net_mean_x2": (sum(nets_x2) / trades) if trades else None,
        "net_mean_x3": (sum(nets_x3) / trades) if trades else None,
        "net_by_month": by_month,
        "daily_totals": totals,
        "worst_trade": min(nets) if nets else None,
        "losing_streak": losing_streak(nets) if nets else 0,
        "cumulative_net_percent": cumulative * 100.0,
        "max_drop_percent": drawdown * 100.0,
        "cumulative": cumulative,
        "max_dd": drawdown,
        "hit_rate": (sum(1 for gross in grosses if gross > 0) / trades) if trades else None,
        "fee": fee,
    }


def _flags(summary: dict, fee_name: str, all_rows: list[dict]) -> list[str]:
    flags = []
    hit = summary["hit_rate"]
    if hit is not None and hit > 0.60:
        flags.append(f"hit rate {hit:.3f} is above 60%")
    net = summary["net_mean"]
    if net is not None and net > summary["fee"]:
        flags.append("net mean per trade is larger than the fee")
    seen = SEEN_NET[fee_name]
    if summary["trades"] >= 300 and net is not None and net > seen:
        flags.append("holdout net mean is better than the seen period")
    if summary["trades"] >= 300 and summary["cumulative"] > 0 and summary["max_dd"] < 0.05 * summary["cumulative"]:
        flags.append("the cumulative path gives back less than 5% of its gain")
    if not profit_spread_ok(summary["net_by_month"]):
        flags.append("more than half the positive net sits in one month")
    by_name = {row["fee_name"]: row for row in all_rows}
    if fee_name == "F3" and "F1" in by_name:
        ordinary = by_name["F1"]["net_mean"]
        cheap = summary["net_mean"]
        filled = summary["trades"]
        attempted = filled + summary["not_filled"]
        fill = filled / attempted if attempted else 0.0
        if ordinary is not None and ordinary <= 0 and cheap is not None and cheap > 0 and fill > 0.80:
            flags.append("profit only at the cheap limit fee while the ordinary fee loses, and the fill rate is above 80%")
    return flags


def verdict(summary: dict, controls: dict, flags: list[str]) -> str:
    """Checklist Step 4. The first matching row wins. CONTINUE is paper only."""
    gaps = controls["missing_futures_share"]
    if controls["truncation"] != "identical: yes":
        return "RERUN"
    if controls["peek_net_mean"] is None or controls["peek_net_mean"] <= 0:
        return "RERUN"
    if gaps is None or gaps >= 0.01:
        return "RERUN"
    if summary["trades"] < 300 or summary["days_with_trades"] < 60:
        return "TOO EARLY"
    gross = summary["gross_mean"]
    net = summary["net_mean"]
    if gross is None or gross <= 0:
        return "STOP this track"
    if net is None or net <= 0:
        return "STOP as built"
    if summary["net_lb"] is None or summary["net_lb"] <= 0:
        return "NOT PROVEN"
    if summary["net_mean_x2"] is None or summary["net_mean_x2"] <= 0 or flags:
        return "NOT PROVEN"
    if not controls["clearly_better"]:
        return "NOT PROVEN"
    if not profit_spread_ok(summary["net_by_month"]):
        return "NOT PROVEN"
    return "CONTINUE"


def _better(rule_daily: list[float], random_daily: list[float], rule_net: float | None, random_net: float | None, matched: bool) -> dict:
    diff = [a - b for a, b in zip(rule_daily, random_daily)]
    bound = daily_net_lower_bound(diff, Z) if diff else None
    higher = rule_net is not None and random_net is not None and rule_net > random_net
    clear = bool(matched and higher and bound is not None and bound > 0)
    return {"difference_net_lb": bound, "rule_higher": higher, "matched_count": matched, "clearly_better": clear}


def _peek(base: int, open_at: np.ndarray, close_at: np.ndarray, fill: np.ndarray, fund_ts: np.ndarray, fund_rate: np.ndarray, hold_ms: int, eval_start: int, eval_end: int, fee: float, days: list[str], months: list[str]) -> dict:
    """Oracle over every filled minute. A trade is taken only when its future net is positive."""
    from src.backtest.cheap_futures import _day, _month, funding_between

    closes, exits, limits, prices, filled_at = [], [], [], [], []
    for slot in range(len(fill)):
        stamp = int(fill[slot])
        if stamp == 0:
            continue
        close_ts = (base + slot) * MINUTE_MS + MINUTE_MS
        if close_ts < eval_start or close_ts >= eval_end:
            continue
        limit = float(close_at[slot])
        if limit != limit or limit <= 0.0:
            continue
        target = stamp + hold_ms
        rem = target % MINUTE_MS
        exit_ts = target if rem == 0 else target + (MINUTE_MS - rem)
        if exit_ts >= eval_end:
            continue
        slot_exit = exit_ts // MINUTE_MS - base
        if slot_exit < 0 or slot_exit >= len(open_at):
            continue
        px = float(open_at[slot_exit])
        if px != px or px <= 0.0:
            continue
        closes.append(close_ts)
        exits.append(exit_ts)
        limits.append(limit)
        prices.append(px)
        filled_at.append(stamp)
    if not closes:
        return summarize([], fee, days, months)
    funding = funding_between(
        fund_ts,
        fund_rate,
        np.asarray(filled_at, dtype=np.int64),
        np.asarray(exits, dtype=np.int64),
    )
    next_free = 0
    kept = []
    for i, close_ts in enumerate(closes):
        if close_ts < next_free:
            continue
        gross = prices[i] / limits[i] - 1.0
        net, _doubled, _tripled = nets_for(gross, float(funding[i]), fee)
        if net <= 0.0:
            continue
        kept.append(
            {
                "status": "filled",
                "gross": gross,
                "funding": float(funding[i]),
                "day": _day(close_ts),
                "month": _month(close_ts),
                "close_ts": close_ts,
                "exit_ts": exits[i],
                "would_gross": gross,
            }
        )
        next_free = exits[i]
    return summarize(kept, fee, days, months)


def _truncation(train: dict, base: int, fill: np.ndarray, signals: np.ndarray) -> dict:
    cut = _ms("2025-12-30")
    later_cut = _ms("2025-12-31")
    early = p2_signals(train["gap_ts"][train["gap_ts"] < cut], train["gap"][train["gap_ts"] < cut])
    later = p2_signals(train["gap_ts"][train["gap_ts"] < later_cut], train["gap"][train["gap_ts"] < later_cut])

    def before(ts: np.ndarray) -> np.ndarray:
        return ts[ts + MINUTE_MS + WINDOW_FILL_MS <= cut]

    early_b, later_b = before(early), before(later)
    signal_mismatch = 0 if len(early_b) == len(later_b) and np.array_equal(early_b, later_b) else abs(len(early_b) - len(later_b)) + 1
    december = HISTORY / "aggTrades" / "BTCUSDT" / "BTCUSDT-aggTrades-2025-12.zip"
    _base, cut_fill, _closes = scan_limit_fills([december], train["fut_ts"], train["fut_close"], stop_ts=cut)
    minute_open = (base + np.arange(len(fill))) * MINUTE_MS
    close_ts = minute_open + MINUTE_MS
    safe = (close_ts >= _ms("2025-12-01")) & (close_ts + WINDOW_FILL_MS <= cut)
    mismatched = int(np.sum(fill[safe] != cut_fill[safe])) if _base == base and len(cut_fill) == len(fill) else 10**9
    identical = signal_mismatch == 0 and mismatched == 0
    return {
        "identical": identical,
        "text": "identical: yes" if identical else "identical: no",
        "signal_mismatches": int(signal_mismatch),
        "fill_mismatches": mismatched,
        "safe_minutes": int(np.sum(safe)),
    }


def _num(value, digits: int = 6) -> str:
    if value is None:
        return "—"
    return f"{float(value):.{digits}g}"


def _pct(value) -> str:
    if value is None:
        return "—"
    return f"{float(value):.3f}"


def _plain(rows: list[dict], truncation_text: str) -> list[str]:
    lines = ["This is the one holdout of the frozen cheap-futures rule. Nothing was traded."]
    stopped = rows and all(row["verdict"] == "STOP as built" for row in rows)
    gross = rows[0]["gross_mean"] if rows else None
    fees = [row["fee"] for row in rows]
    if stopped and gross is not None and gross > 0 and all((row["net_mean"] or 0) <= 0 for row in rows) and fees and gross < min(fees):
        lines.append("All three fee levels are STOP as built.")
        lines.append("No fee case is cleared for paper tracking.")
        lines.append("The futures were a bit cheap, and the next four hours rose on average, but that rise was smaller than every fee.")
    else:
        lines.append("Decisions: " + ", ".join(f"{row['fee_name']} {row['verdict']}" for row in rows) + ".")
        if any(row["verdict"] == "CONTINUE" for row in rows):
            lines.append("CONTINUE means paper tracking only, never real money.")
        else:
            lines.append("No fee case is cleared for paper tracking.")
        lines.append(
            ", ".join(f"{row['fee_name']} net {_num(row['net_mean'])} on {row['trades']} trades" for row in rows) + "."
        )
    random_worse = all(
        row["random_net"] is not None and row["net_mean"] is not None and row["random_net"] < row["net_mean"] for row in rows
    )
    if truncation_text == "identical: yes" and random_worse:
        lines.append("Buying the same number of times at random minutes lost more. Ending the data one day earlier changed nothing.")
    else:
        lines.append(f"Random buys are in the table. Cutting the tape one day earlier was {truncation_text}.")
    lines.append("Nothing from 2026 was loaded.")
    return lines[:6]


def _table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        out.append("| " + " | ".join(row) + " |")
    return "\n".join(out)


def render(payload: dict) -> str:
    rows = payload["fees"]
    lines = _plain(rows, payload["truncation"]["text"])
    fee_rows = []
    for row in rows:
        fee_rows.append(
            [
                row["fee_name"],
                str(row["trades"]),
                str(row["days_with_trades"]),
                str(row["not_filled"]),
                _pct(row["fill_rate_winners"]),
                _pct(row["fill_rate_losers"]),
                _num(row["gross_mean"]),
                _num(row["net_mean"]),
                _num(row["net_lb"]),
                _num(row["net_mean_x2"]),
                _num(row["net_mean_x3"]),
                _num(row["random_net"]),
                f"{row['random_placed']} of {row['random_requested']}",
                _num(row["cumulative_net_percent"]),
                _num(row["max_drop_percent"]),
                _num(row["worst_trade"]),
                str(row["losing_streak"]),
                row["verdict"],
            ]
        )
    months = payload["months"]
    month_rows = []
    for month in months:
        month_rows.append([month] + [_num(row["net_by_month"].get(month, 0.0)) for row in rows])
    when = datetime.now(timezone.utc).astimezone(DUBAI).strftime("%Y-%m-%d %H:%M")
    written = datetime.fromisoformat(payload["ledger"]["written_at"]).astimezone(DUBAI).strftime("%Y-%m-%d %H:%M")
    body = []
    body.extend(lines)
    body.append("")
    body.append(
        f"Holdout {HOLDOUT_START} to {HOLDOUT_END}. December 2024 is warm-up for the 30-day window only. "
        f"K = 1 frozen rule × {payload['rule_sets_tried']} rule sets = {payload['rule_sets_tried']}. z = {Z}. "
        "The same trades are shown at three fees. Funding is charged once and is not doubled."
    )
    body.append("")
    body.append(
        _table(
            [
                "fee",
                "trades",
                "days",
                "NOT_FILLED",
                "fill winners",
                "fill losers",
                "gross mean",
                "net mean",
                "net_lb",
                "net at double cost",
                "net at triple cost",
                "RANDOM net",
                "RANDOM placed",
                "cumulative net %",
                "largest drop from a peak %",
                "worst trade",
                "longest losing streak",
                "verdict",
            ],
            fee_rows,
        )
    )
    body.append("")
    body.append("Net by month. A month with no trades is 0.")
    body.append("")
    body.append(_table(["month"] + [row["fee_name"] for row in rows], month_rows))
    body.append("")
    body.append(
        f"Truncation test: {payload['truncation']['text']}. "
        f"Signal mismatches {payload['truncation']['signal_mismatches']}, "
        f"fill mismatches {payload['truncation']['fill_mismatches']} "
        f"on {payload['truncation']['safe_minutes']} minutes whose three-minute window ends before 2025-12-30."
    )
    body.append(
        f"RANDOM LONG uses the same number of filled limits per month, seed {payload['random_seed']}. "
        "Clearly better means the rule's net is higher and the daily difference stays positive after z = 3.09."
    )
    for row in rows:
        better = row["random_comparison"]
        body.append(
            f"{row['fee_name']} versus random: higher={better['rule_higher']}, "
            f"difference net_lb={_num(better['difference_net_lb'])}, matched={better['matched_count']}, "
            f"clearly better={better['clearly_better']}."
        )
        if row["flags"]:
            body.append(f"{row['fee_name']} flags: " + "; ".join(row["flags"]) + ".")
        else:
            body.append(f"{row['fee_name']} flags: none.")
        body.append(f"{row['fee_name']} peek net {_num(row['peek_net_mean'])} on {row['peek_trades']} oracle trades.")
    gaps = payload["gaps"]
    body.append(
        f"Missing futures minutes {gaps['missing_futures_minutes']} of {gaps['expected_minutes']} "
        f"({_num(gaps['missing_futures_share'])}). Futures minutes without a spot close: {gaps['futures_minutes_without_spot']}."
    )
    body.append(
        "Entry is a limit at the signal close. It counts only when a later trade prints at least one tick through that price within 3 minutes. "
        "Same-candle cases: 0. The exit is the open four hours after the fill."
    )
    body.append(
        f"Costs are above zero on every counted trade. F1 is 0.0009, F2 is 0.0006, F3 is 0.0004, each including spread 0.0001 and slippage 0.0001. "
        f"Ledger row written {written} Asia/Dubai before any 2025 price was read. Rules hash {payload['ledger']['rules_hash'][:12]}."
    )
    body.append(
        "Step 4 is read from the top. CONTINUE needs at least 300 trades over 60 days, net_lb > 0, a positive average after the fee is doubled, "
        "and a clear win over buying at random minutes, with no unexplained flag and the profit not piled in one month. "
        "CONTINUE is paper tracking only, never real money."
    )
    body.append(f"rule_sets_tried is 5. Written {when} Asia/Dubai.")
    return "\n".join(body) + "\n"


def run(record: dict) -> dict:
    print("loading 2024-12 warm-up and 2025 holdout", flush=True)
    market = load_market()
    print(f"futures minutes {len(market['fut_ts'])} gaps {len(market['gap_ts'])}", flush=True)
    paths = _agg_paths()
    base, fill, close_at = scan_limit_fills(paths, market["fut_ts"], market["fut_close"])
    open_at = slot_opens(market["fut_ts"], market["fut_open"], base, len(fill))
    eval_start = _ms(HOLDOUT_START)
    eval_end = _exclusive_end(HOLDOUT_END)
    days = calendar_days(HOLDOUT_START, HOLDOUT_END)
    months = calendar_months(HOLDOUT_START, HOLDOUT_END)
    print("P2 signals", flush=True)
    signals = p2_signals(market["gap_ts"], market["gap"])
    attempts = walk_attempts(
        signals,
        base,
        close_at,
        open_at,
        fill,
        market["fund_ts"],
        market["fund_rate"],
        HOLD_MS[HOLD],
        eval_start,
        eval_end,
    )
    print(f"attempts {len(attempts)}", flush=True)
    print("random minutes", flush=True)
    pool = _candidates(base, open_at, fill, HOLD_MS[HOLD], eval_start, eval_end)
    from src.backtest.fee_limits import month_fill_counts

    drawn = _place(pool, month_fill_counts(attempts))
    random_attempts = walk_attempts(
        np.asarray(sorted(ts - MINUTE_MS for ts in drawn["chosen"]), dtype=np.int64),
        base,
        close_at,
        open_at,
        fill,
        market["fund_ts"],
        market["fund_rate"],
        HOLD_MS[HOLD],
        eval_start,
        eval_end,
    )
    print("truncation", flush=True)
    cut = _truncation(market, base, fill, signals)
    print(cut["text"], flush=True)
    gaps = data_gaps(market["fut_ts"], market["spot_ts"], eval_start, eval_end)
    fee_rows = []
    for name, fee in FEES.items():
        summary = summarize(attempts, fee, days, months)
        random_summary = summarize(random_attempts, fee, days, months)
        peek = _peek(
            base,
            open_at,
            close_at,
            fill,
            market["fund_ts"],
            market["fund_rate"],
            HOLD_MS[HOLD],
            eval_start,
            eval_end,
            fee,
            days,
            months,
        )
        matched = drawn["placed"] == drawn["requested"] and not drawn["short"] and random_summary["trades"] == summary["trades"]
        comparison = _better(summary["daily_totals"], random_summary["daily_totals"], summary["net_mean"], random_summary["net_mean"], matched)
        summary["fee_name"] = name
        summary["random_net"] = random_summary["net_mean"]
        summary["random_placed"] = drawn["placed"]
        summary["random_requested"] = drawn["requested"]
        summary["random_comparison"] = comparison
        summary["peek_net_mean"] = peek["net_mean"]
        summary["peek_trades"] = peek["trades"]
        controls = {
            "truncation": cut["text"],
            "peek_net_mean": peek["net_mean"],
            "missing_futures_share": gaps["missing_futures_share"],
            "clearly_better": comparison["clearly_better"],
        }
        fee_rows.append(summary)
        print(f"  {name} trades {summary['trades']} net {_num(summary['net_mean'])} x2 {_num(summary['net_mean_x2'])}", flush=True)
    for summary in fee_rows:
        summary["flags"] = _flags(summary, summary["fee_name"], fee_rows)
        controls = {
            "truncation": cut["text"],
            "peek_net_mean": summary["peek_net_mean"],
            "missing_futures_share": gaps["missing_futures_share"],
            "clearly_better": summary["random_comparison"]["clearly_better"],
        }
        summary["verdict"] = verdict(summary, controls, summary["flags"])
        print(f"  {summary['fee_name']} {summary['verdict']}", flush=True)
    return {
        "fees": fee_rows,
        "months": months,
        "truncation": cut,
        "gaps": gaps,
        "random_seed": drawn["seed"],
        "random_short": drawn["short"],
        "ledger": record,
        "rule_sets_tried": 5,
        "z": Z,
        "sealed_from": "2026-01-01",
    }


def main() -> None:
    record = require_frozen()
    print(f"ledger {record['written_at']} hash {record['rules_hash'][:12]}", flush=True)
    payload = run(record)
    text = render(payload)
    REPORT.with_suffix(".md").write_text(text)
    REPORT.with_suffix(".json").write_text(json.dumps(payload, indent=2, default=float) + "\n")
    print(f"wrote {REPORT.with_suffix('.md')}", flush=True)


if __name__ == "__main__":
    main()
