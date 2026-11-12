"""Walk-forward run 2. The ledger row is written before any new-holdout read."""

from __future__ import annotations


def main(argv: list[str] | None = None) -> None:
    from src.backtest.run2_execute import execute

    execute(argv)


if __name__ == "__main__":
    main()
