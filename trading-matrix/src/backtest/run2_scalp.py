"""Compact aggTrade tape. Prices stay in arrays so one month fits in memory.

Fill checks use the minute's high and low trade. Delta uses buy and sell
volume. The ordered prices are expanded only for a candle that hits both
brackets.
"""

from __future__ import annotations

import zipfile
from array import array
from pathlib import Path

from src.backtest.loader import to_ms


class MinuteTape:
    def __init__(self):
        self.minutes: dict[int, dict] = {}

    def add(self, ts_ms: int, price: float, qty: float, is_buyer_maker: bool) -> None:
        minute = int(ts_ms) - (int(ts_ms) % 60_000)
        slot = self.minutes.get(minute)
        if slot is None:
            slot = {"buy": 0.0, "sell": 0.0, "lo": price, "hi": price, "prices": array("d")}
            self.minutes[minute] = slot
        if is_buyer_maker:
            slot["sell"] += qty
        else:
            slot["buy"] += qty
        if price < slot["lo"]:
            slot["lo"] = price
        if price > slot["hi"]:
            slot["hi"] = price
        slot["prices"].append(price)

    def through(self, minute: int, side: str, setup: float, tick: float) -> bool:
        slot = self.minutes.get(int(minute))
        if slot is None:
            return False
        if side == "UP":
            return slot["lo"] <= setup - tick
        return slot["hi"] >= setup + tick

    def price_rows(self, minute: int) -> list[tuple[int, float]]:
        slot = self.minutes.get(int(minute))
        if slot is None:
            return []
        return [(0, price) for price in slot["prices"]]

    def delta_rows(self, minute: int) -> list[tuple]:
        slot = self.minutes.get(int(minute))
        if slot is None:
            return []
        rows = []
        if slot["buy"] > 0:
            rows.append((0, 0.0, slot["buy"], False))
        if slot["sell"] > 0:
            rows.append((0, 0.0, slot["sell"], True))
        return rows


def read_aggtrade_zip(path: Path, tape: MinuteTape | None = None) -> MinuteTape:
    tape = tape or MinuteTape()
    with zipfile.ZipFile(path) as zf:
        with zf.open(zf.namelist()[0]) as fh:
            for raw in fh:
                line = raw.decode().strip()
                if not line:
                    continue
                parts = line.split(",")
                if not parts[0][:1].isdigit():
                    continue
                price = float(parts[1])
                qty = float(parts[2])
                ts = to_ms(int(float(parts[5])))
                maker = parts[6].strip().lower() in ("true", "1")
                tape.add(ts, price, qty, maker)
    return tape
