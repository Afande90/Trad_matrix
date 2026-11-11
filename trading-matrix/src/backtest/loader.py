"""Binance public archive reader. URLs checked against data.binance.vision.

Spot klines:  https://data.binance.vision/data/spot/monthly/klines/{SYM}/1m/{SYM}-1m-{YYYY-MM}.zip
UM futures:   https://data.binance.vision/data/futures/um/monthly/klines/{SYM}/1m/{SYM}-1m-{YYYY-MM}.zip
UM funding:   https://data.binance.vision/data/futures/um/monthly/fundingRate/{SYM}/{SYM}-fundingRate-{YYYY-MM}.zip

Monthly bookTicker for BTCUSDT returns 404, so spread is assumed.
Spot files switched from millisecond to microsecond open times in 2025; both are accepted.
"""

from __future__ import annotations

import zipfile
from pathlib import Path


def to_ms(value: int) -> int:
    if value > 10**14:
        return int(value // 1000)
    return int(value)


def month_iter(start: str, end: str):
    """Inclusive months, 'YYYY-MM'."""
    sy, sm = (int(x) for x in start.split("-"))
    ey, em = (int(x) for x in end.split("-"))
    y, m = sy, sm
    while (y, m) <= (ey, em):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m == 13:
            y, m = y + 1, 1


def kline_url(symbol: str, market: str, month: str) -> str:
    if market == "futures":
        return (
            "https://data.binance.vision/data/futures/um/monthly/klines/"
            f"{symbol}/1m/{symbol}-1m-{month}.zip"
        )
    return (
        "https://data.binance.vision/data/spot/monthly/klines/"
        f"{symbol}/1m/{symbol}-1m-{month}.zip"
    )


def funding_url(symbol: str, month: str) -> str:
    return (
        "https://data.binance.vision/data/futures/um/monthly/fundingRate/"
        f"{symbol}/{symbol}-fundingRate-{month}.zip"
    )


def read_klines_zip(path: Path, symbol: str, source: str) -> list[dict]:
    candles = []
    with zipfile.ZipFile(path) as zf:
        name = zf.namelist()[0]
        with zf.open(name) as fh:
            for raw in fh:
                line = raw.decode().strip()
                if not line:
                    continue
                parts = line.split(",")
                if not parts[0][:1].isdigit():
                    continue
                ts = to_ms(int(float(parts[0])))
                candles.append(
                    {
                        "symbol": symbol,
                        "timestamp": ts,
                        "open": float(parts[1]),
                        "high": float(parts[2]),
                        "low": float(parts[3]),
                        "close": float(parts[4]),
                        "volume": float(parts[5]),
                        "source": source,
                    }
                )
    return candles


def read_funding_zip(path: Path) -> list[tuple[int, float]]:
    rows = []
    with zipfile.ZipFile(path) as zf:
        with zf.open(zf.namelist()[0]) as fh:
            for raw in fh:
                parts = raw.decode().strip().split(",")
                if not parts or not parts[0][:1].isdigit():
                    continue
                rows.append((to_ms(int(float(parts[0]))), float(parts[2])))
    rows.sort()
    return rows


def iter_symbol_months(root: Path, symbol: str, market: str, start: str, end: str):
    """Yield (month, candles) one month at a time. Missing months are skipped."""
    folder = root / ("futures" if market == "futures" else "spot") / symbol
    source = "BINANCE_UM" if market == "futures" else "BINANCE_SPOT"
    for month in month_iter(start, end):
        path = folder / f"{symbol}-1m-{month}.zip"
        if not path.exists():
            continue
        yield month, read_klines_zip(path, symbol, source)


def load_funding(root: Path, symbol: str, start: str, end: str) -> list[tuple[int, float]]:
    folder = root / "funding" / symbol
    rows: list[tuple[int, float]] = []
    for month in month_iter(start, end):
        path = folder / f"{symbol}-fundingRate-{month}.zip"
        if path.exists():
            rows.extend(read_funding_zip(path))
    rows.sort()
    return rows
