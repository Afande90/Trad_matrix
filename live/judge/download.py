"""Daily public files from data.binance.vision. A missing file is a wait, not a guess."""

from __future__ import annotations

import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from signals import days_between, months_between, shift_day

BASE = "https://data.binance.vision/data"
USER_AGENT = "paper-ladder"


def to_ms(value: int) -> int:
    if value > 10**14:
        return int(value // 1000)
    return int(value)


def url_for(key: tuple) -> str:
    kind = key[0]
    if kind == "funding":
        _kind, symbol, month = key
        return (
            f"{BASE}/futures/um/monthly/fundingRate/{symbol}/"
            f"{symbol}-fundingRate-{month}.zip"
        )
    if kind == "fut":
        _kind, symbol, day = key
        return f"{BASE}/futures/um/daily/klines/{symbol}/1m/{symbol}-1m-{day}.zip"
    if kind == "spot":
        _kind, symbol, day = key
        return f"{BASE}/spot/daily/klines/{symbol}/1m/{symbol}-1m-{day}.zip"
    if kind == "index":
        _kind, symbol, day = key
        return (
            f"{BASE}/futures/um/daily/indexPriceKlines/{symbol}/1m/"
            f"{symbol}-1m-{day}.zip"
        )
    if kind == "metrics":
        _kind, day = key
        return f"{BASE}/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-{day}.zip"
    if kind == "agg":
        _kind, day = key
        return f"{BASE}/futures/um/daily/aggTrades/BTCUSDT/BTCUSDT-aggTrades-{day}.zip"
    raise ValueError(kind)


def cache_path(root: Path, key: tuple) -> Path:
    kind = key[0]
    if kind == "funding":
        return root / "funding" / key[1] / f"{key[1]}-fundingRate-{key[2]}.zip"
    if kind in ("fut", "spot", "index"):
        return root / kind / key[1] / f"{key[1]}-1m-{key[2]}.zip"
    if kind == "metrics":
        return root / "metrics" / f"BTCUSDT-metrics-{key[1]}.zip"
    if kind == "agg":
        return root / "agg" / f"BTCUSDT-aggTrades-{key[1]}.zip"
    raise ValueError(kind)


def plain_name(key: tuple) -> str:
    kind = key[0]
    if kind == "funding":
        return f"{key[1]} funding for {key[2]}"
    if kind == "fut":
        return f"{key[1]} futures 1-minute prices for {key[2]}"
    if kind == "spot":
        return f"{key[1]} spot 1-minute prices for {key[2]}"
    if kind == "index":
        return f"{key[1]} index 1-minute prices for {key[2]}"
    if kind == "metrics":
        return f"BTC open interest for {key[1]}"
    if kind == "agg":
        return f"BTC aggTrades for {key[1]}"
    return str(key)


def needed(spec: dict, day: str) -> list[tuple]:
    kind = spec["rule"]["kind"]
    symbol = spec["symbol"]
    if kind == "funding_below_percentile":
        start = shift_day(day, -int(spec["rule"]["lookback_days"]))
        files = [("funding", symbol, month) for month in months_between(start, day)]
        files.append(("fut", symbol, day))
        return files
    if kind == "crowding_score":
        start = shift_day(day, -int(spec["rule"]["feature_lookback_days"]))
        files = [("funding", symbol, month) for month in months_between(start, day)]
        for older in days_between(start, day):
            files.append(("fut", symbol, older))
            files.append(("spot", symbol, older))
            files.append(("metrics", older))
        return files
    if kind == "quarter_hour_flow":
        return [("agg", day), ("fut", symbol, day)]
    if kind == "t4_reversion":
        start = shift_day(day, -6)
        return [("fut", symbol, older) for older in days_between(start, day)]
    if kind == "index_gap_below_percentile":
        start = shift_day(day, -int(spec["rule"]["lookback_days"]))
        files = []
        for older in days_between(start, day):
            files.append(("fut", symbol, older))
            files.append(("index", symbol, older))
        return files
    raise ValueError(kind)


def head_ok(url: str, timeout: int = 30) -> bool:
    req = Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=timeout) as response:
            return response.status == 200
    except HTTPError as exc:
        if exc.code == 404:
            return False
        raise
    except URLError:
        raise


def fetch(url: str, dest: Path, timeout: int = 120) -> bool:
    """Download a zip. Return False when the archive answers 404."""
    if dest.exists() and dest.stat().st_size > 0:
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = Request(url, headers={"User-Agent": USER_AGENT})
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with urlopen(req, timeout=timeout) as response:
            tmp.write_bytes(response.read())
    except HTTPError as exc:
        if tmp.exists():
            tmp.unlink()
        if exc.code == 404:
            return False
        raise
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise
    tmp.replace(dest)
    return True


def ensure(cache: Path, key: tuple) -> Path | None:
    dest = cache_path(cache, key)
    if not fetch(url_for(key), dest):
        return None
    if not zipfile.is_zipfile(dest):
        dest.unlink(missing_ok=True)
        return None
    return dest


def read_klines(path: Path) -> dict[int, tuple[float, float]]:
    candles: dict[int, tuple[float, float]] = {}
    with zipfile.ZipFile(path) as zf:
        with zf.open(zf.namelist()[0]) as handle:
            for raw in handle:
                line = raw.decode().strip()
                if not line or not line[0].isdigit():
                    continue
                parts = line.split(",")
                ts = to_ms(int(float(parts[0])))
                candles[ts] = (float(parts[1]), float(parts[4]))
    return candles


def read_funding_interval(path: Path) -> int:
    """Hours between prints, from the first data row of a monthly funding file."""
    with zipfile.ZipFile(path) as zf:
        with zf.open(zf.namelist()[0]) as handle:
            for raw in handle:
                parts = raw.decode().strip().split(",")
                if not parts or not parts[0][:1].isdigit():
                    continue
                interval = int(float(parts[1]))
                if interval <= 0 or 24 % interval != 0:
                    raise ValueError(interval)
                return interval
    raise ValueError(path)


def shift_month(month: str, delta: int) -> str:
    year, mon = (int(part) for part in month.split("-"))
    mon += delta
    while mon < 1:
        year -= 1
        mon += 12
    while mon > 12:
        year += 1
        mon -= 12
    return f"{year:04d}-{mon:02d}"


def read_funding(path: Path) -> list[tuple[int, float]]:
    rows = []
    with zipfile.ZipFile(path) as zf:
        with zf.open(zf.namelist()[0]) as handle:
            for raw in handle:
                parts = raw.decode().strip().split(",")
                if not parts or not parts[0][:1].isdigit():
                    continue
                rows.append((to_ms(int(float(parts[0]))), float(parts[2])))
    rows.sort()
    return rows


def read_metrics(path: Path) -> list[tuple[int, float]]:
    rows = []
    with zipfile.ZipFile(path) as zf:
        with zf.open(zf.namelist()[0]) as handle:
            for raw in handle:
                line = raw.decode().strip()
                if not line or not line[0].isdigit():
                    continue
                parts = line.split(",")
                ts = int(
                    datetime.strptime(parts[0], "%Y-%m-%d %H:%M:%S")
                    .replace(tzinfo=timezone.utc)
                    .timestamp()
                    * 1000
                )
                rows.append((ts, float(parts[2])))
    rows.sort()
    return rows


def read_flow(path: Path, quarter_ms: int = 900_000, window_ms: int = 10_000) -> list[dict]:
    buy: dict[int, float] = {}
    sell: dict[int, float] = {}
    with zipfile.ZipFile(path) as zf:
        with zf.open(zf.namelist()[0]) as handle:
            for raw in handle:
                if not raw or raw[0] < 48 or raw[0] > 57:
                    continue
                parts = raw.split(b",")
                if len(parts) < 7:
                    continue
                ts = to_ms(int(float(parts[5])))
                boundary = ts - (ts % quarter_ms)
                if ts < boundary or ts >= boundary + window_ms:
                    continue
                qty = float(parts[2])
                maker = parts[6][:1] in (b"t", b"T", b"1")
                slot = sell if maker else buy
                slot[boundary] = slot.get(boundary, 0.0) + qty
    rows = []
    for boundary in sorted(set(buy) | set(sell)):
        bought = buy.get(boundary, 0.0)
        sold = sell.get(boundary, 0.0)
        total = bought + sold
        if total <= 0.0:
            continue
        rows.append({"boundary": boundary, "share": bought / total})
    return rows
