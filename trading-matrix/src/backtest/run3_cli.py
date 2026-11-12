"""Walk-forward run 3. The ledger row is written before the holdout is read."""

from __future__ import annotations


def main(argv: list[str] | None = None) -> None:
    from src.backtest.run3 import execute

    execute()


if __name__ == "__main__":
    main()
