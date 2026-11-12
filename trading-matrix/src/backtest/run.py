"""python -m src.backtest.run --symbols BTCUSDT,XAUUSDT --from 2024-11 --to 2026-10"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from src.backtest.report import write_report
from src.backtest.runner import build_result, frozen_rules, write_frozen, write_sqlite


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.WARNING)
    parser = argparse.ArgumentParser(description="Walk-forward backtest. Does not write to the live database.")
    parser.add_argument("--symbols", default="BTCUSDT,XAUUSDT")
    parser.add_argument("--from", dest="start", default="2024-11")
    parser.add_argument("--to", dest="end", default="2026-10")
    parser.add_argument("--history", default="data/history")
    parser.add_argument("--rules", default="backtest/frozen_rules.json")
    parser.add_argument("--ledger", default="backtest/holdout_ledger.json")
    parser.add_argument("--sqlite", default="backtest/results.sqlite")
    parser.add_argument("--report-dir", default="reports")
    args = parser.parse_args(argv)
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    rules_path = Path(args.rules)
    # Frozen before any holdout candle is judged. Nothing was tuned.
    write_frozen(rules_path, frozen_rules(args.start, args.end, symbols))
    result = build_result(
        Path(args.history),
        args.start,
        args.end,
        symbols,
        rules_path,
        Path(args.ledger),
    )
    write_sqlite(Path(args.sqlite), result.pop("records", []))
    today = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%d")
    md, js = write_report(result, Path(args.report_dir), f"backtest_{today}")
    print(md)
    print(js)


if __name__ == "__main__":
    main()
