"""Rule set 2, frozen before the new holdout is read.

K is 6 because this run judges six tracks. rule_sets_tried is 2 so the second
try is visible. z is the pre-registered value for K = 6.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.backtest.ledger import register_holdout
from src.verification.graduation import z_for_k

TRACKS = [
    {"id": "T1", "label": "T1 MOMENTUM 1h", "kind": "trend", "voter": "markov", "window_min": 60, "bar_min": 5, "symbol": "BTCUSDT"},
    {"id": "T2", "label": "T2 MOMENTUM 4h", "kind": "trend", "voter": "markov", "window_min": 240, "bar_min": 15, "symbol": "BTCUSDT"},
    {"id": "T3", "label": "T3 REVERSION 1h", "kind": "trend", "voter": "technical", "window_min": 60, "bar_min": 5, "symbol": "BTCUSDT"},
    {"id": "T4", "label": "T4 REVERSION 4h", "kind": "trend", "voter": "technical", "window_min": 240, "bar_min": 15, "symbol": "BTCUSDT"},
    {"id": "X1", "label": "X1 BTC EXTENDED", "kind": "scalp", "symbol": "BTCUSDT", "asset_class": "CRYPTO", "window_min": 60},
    {"id": "X2", "label": "X2 GOLD EXTENDED", "kind": "scalp", "symbol": "XAUUSDT", "asset_class": "SCALP_METAL", "window_min": 60},
]

K = 6
RULE_SETS_TRIED = 2
Z = z_for_k(K)
HOLDOUT_START = "2022-11-01"
HOLDOUT_END = "2024-11-01"


def freeze_run2(rules_path: Path, ledger_path: Path, ticks: dict[str, float]) -> dict:
    payload = {
        "rule_sets_tried": RULE_SETS_TRIED,
        "K": K,
        "z": Z,
        "symbols": ["BTCUSDT", "XAUUSDT"],
        "holdout_start": HOLDOUT_START,
        "holdout_end": HOLDOUT_END,
        "develop_start": "2024-11-01",
        "develop_end": "2026-05-31",
        "seen_start": "2026-06-08",
        "seen_end": "2026-11-01",
        "seen_note": "SEEN PERIOD - not evidence. Never feeds a verdict.",
        "entry": "next candle open",
        "exit": "window end",
        "lookback_bars": 500,
        "resample": {"1h": "5m", "4h": "15m"},
        "trend_venue": "futures",
        "trend_fee_mode": "taker",
        "scalp_fee_mode": "maker",
        "scalp_trigger": "cost gate AND S1 score >= min AND (S2 agrees OR S5 agrees)",
        "s5": "aggTrade delta over the last 3 closed 1m candles; no bookTicker",
        "scalp_costs": {"WIN": "maker+maker", "LOSS": "maker+taker", "TIMEOUT": "maker+taker"},
        "fill": "limit at setup, trade through by one tick within 3 candles, else NOT_FILLED",
        "one_position": True,
        "sideways_not_counted": True,
        "min_calls": 300,
        "min_days": 60,
        "random_seed": 1,
        "ticks": ticks,
        "tick_note": "exchangeInfo returned HTTP 451. BTCUSDT tick 0.1 and XAUUSDT tick 0.01 were not tuned.",
        "tracks": TRACKS,
        "unchanged": [
            "markov window 20",
            "MARKOV_K 1.0",
            "RSI 14",
            "MACD 12/26/9",
            "Bollinger 20/2",
            "min score 4.5",
            "min reward/cost 3",
            "max breakeven 0.50",
            "SCALP_RR 1.5",
            "dead market ATR/AvgATR 0.6",
            "FEE_FUT_MAKER 0.0002",
            "FEE_FUT_TAKER 0.0005",
            "spread 0.0001",
            "slippage 0.0001",
        ],
    }
    rules_path = Path(rules_path)
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    register_holdout(Path(ledger_path), rules_path, HOLDOUT_START, HOLDOUT_END, ["BTCUSDT", "XAUUSDT"])
    return payload


def freeze_run2_rules(path: Path, tick_btc: str, tick_xau: str, tick_source: str | None = None) -> dict:
    """Write rule set 2. This function does not take a data root and does not read klines."""
    payload = {
        "rule_sets_tried": RULE_SETS_TRIED,
        "K": K,
        "z": Z,
        "z_source": "z_for_k(6)",
        "symbols": ["BTCUSDT", "XAUUSDT"],
        "tracks": [row["id"] for row in TRACKS],
        "btc_holdout_start": HOLDOUT_START,
        "btc_holdout_end": HOLDOUT_END,
        "btc_develop": "2024-11 to 2026-05",
        "seen_period_start": "2026-06-08",
        "seen_period_end": "2026-11-01",
        "gold_from": "2025-12",
        "gold_to": "2026-10",
        "gold_split": "60/20/20",
        "entry": "next candle open",
        "exit": "window end",
        "closed_candles_only": True,
        "ai_visual": "excluded",
        "trend_market": "USD-M perpetual",
        "trend_fee_mode": "taker",
        "trend_venue": "futures",
        "voters": {
            "T1_MOMENTUM_1H": "markov",
            "T2_MOMENTUM_4H": "markov",
            "T3_REVERSION_1H": "technical",
            "T4_REVERSION_4H": "technical",
        },
        "lens_lookback": 500,
        "markov_window": 20,
        "markov_k": 1.0,
        "resample": {"1h": "5m", "4h": "15m"},
        "scalp_fee_mode": "maker",
        "scalp_class": "EXTENDED",
        "scalp_trigger": "either",
        "s5": "aggTrade delta only",
        "book_confirmation": False,
        "extended_max_min": 60,
        "scalp_rr": 1.5,
        "min_reward_cost_ratio": 3.0,
        "max_breakeven_wr": 0.5,
        "min_signal_score": 4.5,
        "min_vol_ratio": 0.6,
        "outcome_cost": {
            "WIN": "maker+maker+spread+slippage",
            "LOSS": "maker+taker+spread+slippage",
            "TIMEOUT": "maker+taker+spread+slippage",
        },
        "assumed_spread_pct": 0.0001,
        "slippage_pct": 0.0001,
        "fee_fut_maker": 0.0002,
        "fee_fut_taker": 0.0005,
        "tick_size": {"BTCUSDT": str(tick_btc), "XAUUSDT": str(tick_xau)},
        "tick_source": tick_source or "https://testnet.binancefuture.com/fapi/v1/exchangeInfo",
        "random_seed": 1,
        "one_position_at_a_time": True,
        "sideways_counted": False,
        "note": (
            "Rule set 2. No parameter was tuned. Reported K is 6, the six tracks. "
            "z is z_for_k(6) = 3.09. rule_sets_tried is 2 so the second try is visible."
        ),
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return payload


def evaluate_step1(
    *,
    random_ctrl: dict,
    oracles: list[dict],
    truncation_ok: bool,
    entry_ok: bool,
    cost_ok: bool,
    ledger_ok: bool,
    same_candle_reported: bool,
    gap_ratio: float,
    rule_sets_tried: int,
    k: int,
    z: float,
) -> dict:
    """Honesty checks. Any failure makes every track RERUN."""

    def _random_ok(ctrl: dict) -> bool:
        if ctrl.get("net_mean") is None or ctrl.get("target") is None or not ctrl.get("n"):
            return False
        if ctrl["net_mean"] > 0:
            return False
        return abs(ctrl["net_mean"] - ctrl["target"]) <= 2 * (ctrl.get("se") or 0.0) + 1e-12

    def _oracle_ok(rows: list[dict]) -> bool:
        if not rows:
            return False
        for row in rows:
            if not row.get("wiring_ok"):
                return False
            gross = row.get("gross")
            if gross is None or gross <= 0:
                return False
        return True

    random_ok = _random_ok(random_ctrl)
    oracle_ok = _oracle_ok(oracles)
    gap_ok = gap_ratio < 0.01
    rows = [
        {
            "check": "RANDOM control",
            "result": f"net {random_ctrl.get('net_mean')} vs cost target {random_ctrl.get('target')} (n={random_ctrl.get('n')})",
            "ok": random_ok,
        },
        {
            "check": "WINDOW ORACLE",
            "result": "wiring ok" if oracle_ok else "wiring failed",
            "ok": oracle_ok,
        },
        {
            "check": "Truncation test",
            "result": "identical: yes" if truncation_ok else "identical: no",
            "ok": bool(truncation_ok),
        },
        {"check": "Entry price", "result": "next candle open" if entry_ok else "not next open", "ok": bool(entry_ok)},
        {"check": "Costs applied", "result": "cost_pct > 0 on counted calls" if cost_ok else "cost missing", "ok": bool(cost_ok)},
        {"check": "Holdout ledger", "result": "registered before the holdout was read" if ledger_ok else "missing", "ok": bool(ledger_ok)},
        {
            "check": "Rule sets tried (K)",
            "result": f"rule_sets_tried = {rule_sets_tried}. Reported K = {k}. z = {z}.",
            "ok": rule_sets_tried == 2 and k == 6 and z == 3.09,
        },
        {
            "check": "Same-candle cases",
            "result": "count shown; resolved by aggTrades or counted as loss",
            "ok": bool(same_candle_reported),
        },
        {
            "check": "Data gaps",
            "result": f"missing minutes {gap_ratio:.4%} of the spanned minutes",
            "ok": gap_ok,
        },
    ]
    return {"step1_ok": all(row["ok"] for row in rows), "step1": rows}


def main() -> None:
    import logging

    logging.basicConfig(level=logging.WARNING)
    from src.backtest.run2_job import run

    run()


if __name__ == "__main__":
    main()
