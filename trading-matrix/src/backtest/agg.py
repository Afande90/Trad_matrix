"""Stream aggTrades one minute at a time. A month is never held in memory."""

from __future__ import annotations

import zipfile
from pathlib import Path

from src.backtest.loader import to_ms


class AggCursor:
    def __init__(self, path: Path):
        self._zf = zipfile.ZipFile(path)
        self._fh = self._zf.open(self._zf.namelist()[0])
        self._held: tuple | None = None
        self._minute: int | None = None
        self._eof = False

    def close(self) -> None:
        self._fh.close()
        self._zf.close()

    def _read(self) -> tuple | None:
        if self._held is not None:
            row = self._held
            self._held = None
            return row
        while True:
            raw = self._fh.readline()
            if not raw:
                self._eof = True
                return None
            if not raw[:1] or not (48 <= raw[0] <= 57):
                continue
            parts = raw.split(b",")
            if len(parts) < 7:
                continue
            ts = to_ms(int(float(parts[5])))
            price = float(parts[1])
            qty = float(parts[2])
            maker = parts[6][:1] in (b"t", b"T", b"1")
            return ts, price, qty, maker

    def peek_minute(self) -> int | None:
        if self._minute is not None:
            return self._minute
        row = self._read()
        if row is None:
            return None
        self._held = row
        self._minute = int(row[0]) - (int(row[0]) % 60_000)
        return self._minute

    def consume(self, keep_prices: bool = False) -> dict | None:
        minute = self.peek_minute()
        if minute is None:
            return None
        buy = 0.0
        sell = 0.0
        lo = None
        hi = None
        prices: list[tuple[int, float]] = []
        bins: dict[float, float] = {}
        while True:
            row = self._read()
            if row is None:
                break
            ts, price, qty, maker = row
            row_minute = ts - (ts % 60_000)
            if row_minute != minute:
                self._held = row
                self._minute = row_minute
                break
            if maker:
                sell += qty
            else:
                buy += qty
            lo = price if lo is None else min(lo, price)
            hi = price if hi is None else max(hi, price)
            binkey = round(price * 10.0) / 10.0
            bins[binkey] = bins.get(binkey, 0.0) + qty
            if keep_prices:
                prices.append((ts, price))
        else:
            self._minute = None
        if self._eof and self._held is None:
            self._minute = None
        return {"minute": minute, "buy": buy, "sell": sell, "min": lo, "max": hi, "prices": prices, "bins": bins}
