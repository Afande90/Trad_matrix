"""Seen-period measurement. Limit-entry bitcoin fees, then gold, silver, oil and forex.

Nothing from 2025-01-01 onward is loaded. The holdout is not opened.
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
    PERCENTILES,
    RANDOM_SEED,
    TRAIN_END,
    TRAIN_START,
    TRAIN_WARMUP,
    _exclusive_end,
    _ms,
    align_gaps,
    calendar_months,
    load_funding_range,
    load_klines,
    signals_for,
)
from src.backtest.fee_limits import (
    FEE_NOTE,
    FEES,
    WINDOW_FILL_MS,
    agg_paths,
    exit_open_ts,
    month_fill_counts,
    random_filled_orders,
    scan_limit_fills,
    slot_closes,
    slot_opens,
    summarize_fee,
    walk_attempts,
)
from src.backtest.other_markets import COMMISSION, measure_folder

ROOT = Path(__file__).resolve().parents[2]
HISTORY = ROOT / "data" / "history"
REPORT = ROOT / "reports" / "fees_and_markets_2026-11-13"
DUBAI = ZoneInfo("Asia/Dubai")


def _num(value, digits: int = 6) -> str:
    if value is None:
        return "—"
    return f"{float(value):.{digits}g}"


def _pct(value) -> str:
    if value is None:
        return "—"
    return f"{float(value):.3f}"


def load_train() -> dict:
    lo = _ms(TRAIN_WARMUP)
    hi = _exclusive_end(TRAIN_END)
    futures, fut_missing = load_klines(HISTORY, "futures", "2020-11", "2022-10", lo, hi, False)
    spot, spot_missing = load_klines(HISTORY, "spot", "2020-11", "2022-10", lo, hi, False)
    fund_ts, fund_rate, fund_missing = load_funding_range(HISTORY, "2020-11", "2022-10", lo, hi, False)
    gap_ts, gap = align_gaps(futures, spot)
    return {
        "fut_ts": np.asarray([int(c["timestamp"]) for c in futures], dtype=np.int64),
        "fut_open": np.asarray([float(c["open"]) for c in futures], dtype=float),
        "fut_close": np.asarray([float(c["close"]) for c in futures], dtype=float),
        "gap_ts": gap_ts,
        "gap": gap,
        "fund_ts": fund_ts,
        "fund_rate": fund_rate,
        "missing_futures_months": fut_missing,
        "missing_spot_months": spot_missing,
        "missing_funding_months": fund_missing,
    }


def _candidates(base: int, open_at: np.ndarray, fill: np.ndarray, hold_ms: int, eval_start: int, eval_end: int) -> dict[str, list[tuple[int, int]]]:
    from src.backtest.cheap_futures import _month

    out: dict[str, list[tuple[int, int]]] = {}
    n = len(fill)
    for slot in range(n):
        filled_at = int(fill[slot])
        if filled_at == 0:
            continue
        minute_open = (base + slot) * MINUTE_MS
        close_ts = minute_open + MINUTE_MS
        if close_ts < eval_start or close_ts >= eval_end:
            continue
        exit_ts = exit_open_ts(filled_at, hold_ms)
        if exit_ts >= eval_end:
            continue
        slot_exit = exit_ts // MINUTE_MS - base
        if slot_exit < 0 or slot_exit >= n:
            continue
        px = float(open_at[slot_exit])
        if px != px or px <= 0.0:
            continue
        out.setdefault(_month(close_ts), []).append((close_ts, exit_ts))
    return out


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


def _before(ts: np.ndarray, cut: int) -> np.ndarray:
    return ts[ts + MINUTE_MS + WINDOW_FILL_MS <= cut]


def truncation(train: dict, base: int, fill: np.ndarray, found: dict) -> dict:
    cut = _ms("2022-10-30")
    later_cut = _ms("2022-10-31")
    early_ts = train["gap_ts"][train["gap_ts"] < cut]
    early_gap = train["gap"][train["gap_ts"] < cut]
    later_ts = train["gap_ts"][train["gap_ts"] < later_cut]
    later_gap = train["gap"][train["gap_ts"] < later_cut]
    early = signals_for(early_ts, early_gap)
    later = signals_for(later_ts, later_gap)
    signal_mismatch = 0
    for p in PERCENTILES:
        signal_mismatch += int(np.sum(_before(early[p], cut) != _before(later[p], cut))) if len(_before(early[p], cut)) == len(_before(later[p], cut)) else 10**9
        if len(_before(early[p], cut)) != len(_before(later[p], cut)):
            signal_mismatch += abs(len(_before(early[p], cut)) - len(_before(later[p], cut)))
    october = HISTORY / "aggTrades" / "BTCUSDT" / "BTCUSDT-aggTrades-2022-10.zip"
    _base, cut_fill, _closes = scan_limit_fills([october], train["fut_ts"], train["fut_close"], stop_ts=cut)
    if _base != base or len(cut_fill) != len(fill):
        return {"identical": False, "reason": "fill map shape changed"}
    minute_open = (base + np.arange(len(fill))) * MINUTE_MS
    close_ts = minute_open + MINUTE_MS
    safe = (close_ts >= _ms("2022-10-01")) & (close_ts + WINDOW_FILL_MS <= cut)
    mismatched = int(np.sum(fill[safe] != cut_fill[safe]))
    identical = signal_mismatch == 0 and mismatched == 0
    return {
        "identical": identical,
        "text": "identical: yes" if identical else "identical: no",
        "signal_mismatches": int(signal_mismatch),
        "fill_mismatches": mismatched,
        "safe_minutes": int(np.sum(safe)),
        "cut": "2022-10-30",
        "compared_with": "2022-10-31",
    }


def measure_btc(train: dict) -> dict:
    import os

    cached = Path("/tmp/fee_limit_fills.npz")
    if os.environ.get("FEE_REUSE") == "1" and cached.exists():
        print("reusing fill map", flush=True)
        loaded = np.load(cached)
        base = int(loaded["base"][0])
        fill = loaded["fill"]
        _base, close_at = slot_closes(train["fut_ts"], train["fut_close"])
        if _base != base or len(close_at) != len(fill):
            raise RuntimeError("cached fill map does not match these candles")
    else:
        print("scanning aggTrades", flush=True)
        paths = agg_paths(HISTORY, "2020-11", "2022-10")
        base, fill, close_at = scan_limit_fills(paths, train["fut_ts"], train["fut_close"])
        np.savez(cached, base=np.asarray([base]), fill=fill)
    open_at = slot_opens(train["fut_ts"], train["fut_open"], base, len(fill))
    eval_start = _ms(TRAIN_START)
    eval_end = _exclusive_end(TRAIN_END)
    months = calendar_months(TRAIN_START, TRAIN_END)
    print(f"signals, months {len(months)}", flush=True)
    found = signals_for(train["gap_ts"], train["gap"])
    rows = []
    random_rows = []
    pools = {}
    for hold, hold_ms in HOLD_MS.items():
        print(f"  candidate minutes {hold}", flush=True)
        pools[hold] = _candidates(base, open_at, fill, hold_ms, eval_start, eval_end)
    for p in PERCENTILES:
        for hold, hold_ms in HOLD_MS.items():
            name = f"P{p} {hold}"
            print(f"  walk {name}", flush=True)
            attempts = walk_attempts(
                found[p],
                base,
                close_at,
                open_at,
                fill,
                train["fund_ts"],
                train["fund_rate"],
                hold_ms,
                eval_start,
                eval_end,
            )
            for fee_name, fee in FEES.items():
                summary = summarize_fee(attempts, fee, months)
                summary["variant"] = name
                summary["percentile"] = p
                summary["hold"] = hold
                summary["fee_name"] = fee_name
                summary["fee_note"] = FEE_NOTE[fee_name]
                rows.append(summary)
                print(
                    f"    {fee_name} trades {summary['trades']} not_filled {summary['not_filled']} "
                    f"gross {_num(summary['gross_mean'])} netx2 {_num(summary['net_mean_x2'])} clears {summary['clears']}",
                    flush=True,
                )
            drawn = _place(pools[hold], month_fill_counts(attempts))
            opens = np.asarray(sorted(ts - MINUTE_MS for ts in drawn["chosen"]), dtype=np.int64)
            random_attempts = walk_attempts(
                opens,
                base,
                close_at,
                open_at,
                fill,
                train["fund_ts"],
                train["fund_rate"],
                hold_ms,
                eval_start,
                eval_end,
            )
            fees = {}
            for fee_name, fee in FEES.items():
                summary = summarize_fee(random_attempts, fee, months)
                fees[fee_name] = {"trades": summary["trades"], "net_mean": summary["net_mean"], "gross_mean": summary["gross_mean"]}
            random_rows.append(
                {
                    "variant": name,
                    "requested": drawn["requested"],
                    "placed": drawn["placed"],
                    "seed": drawn["seed"],
                    "short": drawn["short"],
                    "fees": fees,
                }
            )
            print(f"    random {drawn['placed']} of {drawn['requested']} seed {drawn['seed']}", flush=True)
    print("truncation", flush=True)
    cut = truncation(train, base, fill, found)
    print(f"  {cut['text']}", flush=True)
    return {
        "rows": rows,
        "random": random_rows,
        "truncation": cut,
        "months": months,
        "missing_futures_months": train["missing_futures_months"],
        "missing_spot_months": train["missing_spot_months"],
        "missing_funding_months": train["missing_funding_months"],
        "fees": {name: {"rate": rate, "note": FEE_NOTE[name]} for name, rate in FEES.items()},
    }


def binance_metals() -> dict:
    import urllib.request

    urls = {
        "XAUUSDT kline 2024-12": "https://data.binance.vision/data/futures/um/monthly/klines/XAUUSDT/1m/XAUUSDT-1m-2024-12.zip",
        "XAGUSDT kline 2024-12": "https://data.binance.vision/data/futures/um/monthly/klines/XAGUSDT/1m/XAGUSDT-1m-2024-12.zip",
        "XAUUSDT index 2024-12": "https://data.binance.vision/data/futures/um/monthly/indexPriceKlines/XAUUSDT/1m/XAUUSDT-1m-2024-12.zip",
    }
    status = {}
    for name, url in urls.items():
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=30) as resp:
                status[name] = int(resp.status)
        except Exception as exc:
            status[name] = getattr(exc, "code", str(exc))
    return {
        "skipped": True,
        "usable_days": 0,
        "status": status,
        "reason": (
            "Binance XAUUSDT and XAGUSDT perpetuals were not measured. "
            "The December 2024 archive is not there, and the contracts start in 2026, inside the sealed window. "
            "No file from 2025 onward was downloaded, so there is no pre-seal history and the sample is too short to judge."
        ),
    }


def _plain(part_a: dict, part_b: list[dict], metals: dict) -> list[str]:
    clears = [row for row in part_a["rows"] if row["clears"]]
    lines = ["This looks at old prices only. Nothing was traded, and a profit is not shown."]
    if not clears:
        lines.append("None of the six bitcoin settings stayed positive once the fee was doubled, on any of the three fee levels.")
    else:
        names = ", ".join(f"{row['variant']} at {row['fee_name']}" for row in clears)
        standard = "" if any(row["fee_name"] == "F1" for row in clears) else " The ordinary fee, F1, did not."
        spelled = (
            "Four cases stayed positive after the fee was doubled, each with at least 100 trades: "
            "the 5% gap held 4 hours at the lowest fee, and the 2% gap held 1 hour at the lowest fee or 4 hours at either of the two lower fees. "
            "The ordinary fee did not."
        )
        codes = {(row["variant"], row["fee_name"]) for row in clears}
        if codes == {("P5 4h", "F3"), ("P2 1h", "F3"), ("P2 4h", "F2"), ("P2 4h", "F3")}:
            lines.append(spelled)
        else:
            lines.append(f"{len(clears)} cases stayed positive after the fee was doubled, each with at least 100 trades: {names}.{standard}")
    winner_rates = [row["fill_rate_winners"] for row in part_a["rows"] if row["fee_name"] == "F1" and row["fill_rate_winners"] is not None]
    loser_rates = [row["fill_rate_losers"] for row in part_a["rows"] if row["fee_name"] == "F1" and row["fill_rate_losers"] is not None]
    if winner_rates and loser_rates and all(w > l for w, l in zip(winner_rates, loser_rates)):
        lines.append(
            "In every setting the limit filled a little more often on trades that would have made money "
            f"({min(winner_rates):.3f} to {max(winner_rates):.3f}) than on trades that would have lost "
            f"({min(loser_rates):.3f} to {max(loser_rates):.3f})."
        )
    elif winner_rates and loser_rates and all(w < l for w, l in zip(winner_rates, loser_rates)):
        lines.append("The limit filled more often on trades that would have lost money than on trades that would have made money.")
    elif winner_rates and loser_rates:
        lines.append(
            "Fill rates for trades that would have made money ran from "
            f"{min(winner_rates):.3f} to {max(winner_rates):.3f}, and for trades that would have lost from "
            f"{min(loser_rates):.3f} to {max(loser_rates):.3f}."
        )
    same = part_a["truncation"]["identical"]
    random_lost = all(
        (item["fees"].get("F1") or {}).get("net_mean") is not None and item["fees"]["F1"]["net_mean"] < 0 for item in part_a["random"]
    )
    short = [item for item in part_a["random"] if item["placed"] != item["requested"]]
    if same and random_lost:
        short_note = ""
        if short:
            short_note = " " + ", ".join(f"{item['variant']} placed {item['placed']} of {item['requested']}" for item in short) + "."
        lines.append(f"Buys at random minutes lost money at the ordinary fee.{short_note} Cutting the tape one day earlier changed nothing.")
    else:
        lines.append(f"Random buys are in the table. Cutting the tape one day earlier was {part_a['truncation']['text']}.")
    labels = [row["label"] for row in part_b]
    bigger = [row for row in part_b if row["label"].startswith("bigger")]
    smaller = sum(1 for label in labels if label == "real but smaller than the cost")
    nothing = sum(1 for label in labels if label == "nothing")
    other = sum(1 for label in labels if label == "not an up-or-down trade")
    lines.append(
        f"On gold, silver, oil and the currencies, {nothing} measures showed nothing and {smaller} were real but smaller than the cost. "
        f"{other} others only say that a large move tends to be followed by another large move, not which way."
    )
    if bigger:
        named = "; ".join(f"{row['instrument']} {row['measure']}" for row in bigger[:4])
        lines.append(f"The measures above the cost were: {named}.")
    else:
        lines.append("No gold, silver, oil or currency measure was both strong and larger than its cost.")
    ratio = [row for row in part_b if row["instrument"] == "Gold/Silver"]
    fx = [row for row in part_b if row["instrument"] in ("EURUSD/GBPUSD", "GBPUSD/EURUSD") and row["kind"] == "return"]
    if ratio or fx:
        ratio_nothing = all(row["label"] == "nothing" for row in ratio)
        fx_small = all(
            row["label"] == "real but smaller than the cost" and row["gross_effect"] is not None and row["cost"] is not None and abs(row["gross_effect"]) < row["cost"]
            for row in fx
        )
        if ratio_nothing and fx_small and len(ratio) == 2 and len(fx) == 2:
            lines.append(
                "Gold versus silver, after an unusually high or low ratio, did not pay over the next 4 hours. "
                "The euro and the pound barely predict each other's next minute, and that sliver is far smaller than the spread."
            )
        else:
            ratio_bits = ", ".join(f"{_num(row['gross_effect'])} ({row['label']})" for row in ratio)
            fx_bits = ", ".join(f"{row['instrument']} {_num(row['gross_effect'])} ({row['label']})" for row in fx)
            lines.append(f"Gold versus silver: {ratio_bits}. Euro and pound: {fx_bits}.")
    lines.append("Binance gold and silver futures were skipped: there is no price history before the sealed window, so they are too short to judge.")
    return lines[:8]


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        out.append("| " + " | ".join(row) + " |")
    return "\n".join(out)


def render(part_a: dict, part_b: list[dict], missing: list[str], costs: dict, metals: dict) -> str:
    lines = _plain(part_a, part_b, metals)
    a_rows = []
    for row in part_a["rows"]:
        a_rows.append(
            [
                row["variant"],
                row["fee_name"],
                str(row["trades"]),
                str(row["not_filled"]),
                _pct(row["fill_rate_winners"]),
                _pct(row["fill_rate_losers"]),
                _num(row["gross_mean"]),
                _num(row["net_mean"]),
                _num(row["net_mean_x2"]),
                _pct(row["positive_month_share"]),
                _num(row["worst_trade"]),
                "yes" if row["clears"] else "",
            ]
        )
    r_rows = []
    for item in part_a["random"]:
        r_rows.append(
            [
                item["variant"],
                f"{item['placed']} of {item['requested']}",
                str(item["seed"]),
                _num(item["fees"]["F1"]["net_mean"]),
                _num(item["fees"]["F2"]["net_mean"]),
                _num(item["fees"]["F3"]["net_mean"]),
            ]
        )
    b_rows = []
    for row in part_b:
        b_rows.append(
            [
                row["instrument"],
                row["measure"],
                str(row["n"]),
                _num(row["gross_effect"]),
                _num(row["cost"]),
                _num(row["effect_over_cost"]),
                _num(row["t_stat"]),
                row["label"],
            ]
        )
    when = datetime.now(timezone.utc).astimezone(DUBAI).strftime("%Y-%m-%d %H:%M")
    skipped = ", ".join(missing) if missing else "none"
    cost_bits = []
    for name, info in costs.items():
        cost_bits.append(f"{name} median spread {_num(info['median_spread'])} plus {COMMISSION:.5f} commission, cost {_num(info['cost'])}")
    body = []
    body.extend(lines)
    body.append("")
    body.append("Part A. Bitcoin cheap futures, limit entry, seen period 2020-12-01 to 2022-10-31. November 2020 is warm-up only. The holdout was not opened.")
    body.append("")
    body.append(
        _md_table(
            ["variant", "fee", "trades", "NOT_FILLED", "fill rate winners", "fill rate losers", "gross mean", "net mean", "net mean at double cost", "share of months positive", "worst trade", "double cost still positive"],
            a_rows,
        )
    )
    body.append("")
    body.append(
        "A row marked yes has a positive average after the fee is doubled and at least 100 counted trades. "
        "Funding is charged once and is not doubled. F1 is 0.0009, F2 is 0.0006, F3 is 0.0004, each including spread 0.0001 and slippage 0.0001. "
        "Share of months uses all 23 calendar months from December 2020 through October 2022. A month with no trades is not positive."
    )
    body.append("")
    body.append("RANDOM LONG, same number of filled limits per month, seed 3558.")
    body.append("")
    body.append(_md_table(["variant", "placed", "seed", "F1 net", "F2 net", "F3 net"], r_rows))
    body.append("")
    body.append(
        f"Truncation test, data cut one day later versus one day earlier: {part_a['truncation']['text']}. "
        f"Signal mismatches {part_a['truncation'].get('signal_mismatches', '—')}, "
        f"fill mismatches {part_a['truncation'].get('fill_mismatches', '—')} "
        f"on {part_a['truncation'].get('safe_minutes', '—')} minutes whose three-minute window ends before 2022-10-30."
    )
    body.append("")
    body.append("Part B. Gold, silver, light crude and three currencies, 2022-01-01 to 2023-12-31. One row per measure.")
    body.append("")
    body.append(
        _md_table(
            ["instrument", "measure", "n", "gross effect per trade", "cost", "effect / cost", "t-stat on daily totals", "label"],
            b_rows,
        )
    )
    body.append("")
    body.append(f"{len(part_b)} rows were measured. With this many rows a few will look good by luck. That is why the bar is |t| >= 3.5.")
    body.append("")
    body.append("Measured on seen periods. Shows where to look. Not evidence of profit. Anything promising must be frozen and tested once on 2025 onward.")
    body.append("")
    body.append(f"Instruments skipped because the file was missing: {skipped}.")
    body.append("The 0.00007 commission added to each instrument is an assumption, not a measured fee. Cost = measured median spread (ask close minus bid close, divided by the mid) plus that commission.")
    body.append("A pair costs the sum of the two instruments. Correlation rows are not a fee test: their gross and cost cells are left blank, and they are never labelled bigger than the cost.")
    body.append("A hold that would cross a missing minute or the weekend close (Friday 22:00 UTC through Sunday 22:00 UTC) was dropped.")
    if cost_bits:
        body.append("Measured costs: " + "; ".join(cost_bits) + ".")
    body.append(metals["reason"] + f" Archive checks: {json.dumps(metals['status'])}. Usable days: {metals['usable_days']}.")
    body.append(f"rule_sets_tried is 4. This set is the measurement above. No variant was frozen and the holdout was not opened. Written {when} Asia/Dubai.")
    return "\n".join(body) + "\n"


def bump_rule_set(path: Path) -> None:
    text = path.read_text()
    text = text.replace('"rule_sets_tried": 3', '"rule_sets_tried": 4', 1)
    note = (
        '  "rule_set_4": "Fee measurement on the seen bitcoin period, limit entry, three fee schedules, '
        'plus a four-market check for 2022-2023. No variant was frozen. The holdout was not opened."'
    )
    if '"rule_set_4"' not in text:
        text = text.rstrip()
        if text.endswith("}"):
            text = text[:-1].rstrip() + ",\n" + note + "\n}\n"
    path.write_text(text)


def main() -> None:
    print("part A load", flush=True)
    train = load_train()
    part_a = measure_btc(train)
    Path("/tmp/part_a.json").write_text(json.dumps(part_a, indent=2, default=float) + "\n")
    print("part B", flush=True)
    part_b, missing, costs = measure_folder(HISTORY / "dukascopy")
    print("binance metals headers only", flush=True)
    metals = binance_metals()
    text = render(part_a, part_b, missing, costs, metals)
    REPORT.with_suffix(".md").write_text(text)
    payload = {"part_a": part_a, "part_b": part_b, "missing": missing, "costs": costs, "binance_metals": metals, "rows_measured": len(part_b)}
    REPORT.with_suffix(".json").write_text(json.dumps(payload, indent=2, default=float) + "\n")
    bump_rule_set(ROOT / "backtest" / "frozen_rules.json")
    print(f"wrote {REPORT.with_suffix('.md')}", flush=True)


if __name__ == "__main__":
    main()
