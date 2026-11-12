"""Archive downloads. Holdout months are fetched only after the ledger row exists."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from src.backtest.loader import funding_url, kline_url, month_iter


def agg_url(symbol: str, month: str) -> str:
    return (
        "https://data.binance.vision/data/futures/um/monthly/aggTrades/"
        f"{symbol}/{symbol}-aggTrades-{month}.zip"
    )


def fetch(url: str, dest: Path, tries: int = 4) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    last = None
    for attempt in range(tries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "trading-matrix-backtest"})
            with urllib.request.urlopen(request, timeout=600) as handle, tmp.open("wb") as out:
                while True:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            if tmp.stat().st_size <= 0:
                raise RuntimeError("empty download")
            tmp.replace(dest)
            return
        except Exception as exc:  # noqa: BLE001 - retry the public archive
            last = exc
            if tmp.exists():
                tmp.unlink()
            if attempt + 1 == tries:
                break
    raise RuntimeError(f"download failed {url}: {last}")


def ensure_file(url: str, dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    fetch(url, dest)
    return dest


def ensure_klines(root: Path, symbol: str, market: str, start: str, end: str) -> None:
    folder = root / ("futures" if market == "futures" else "spot") / symbol
    for month in month_iter(start, end):
        dest = folder / f"{symbol}-1m-{month}.zip"
        ensure_file(kline_url(symbol, market, month), dest)


def ensure_funding(root: Path, symbol: str, start: str, end: str) -> None:
    folder = root / "funding" / symbol
    for month in month_iter(start, end):
        dest = folder / f"{symbol}-fundingRate-{month}.zip"
        ensure_file(funding_url(symbol, month), dest)


def fetch_ticks(symbols: list[str]) -> dict:
    """Public USD-M exchangeInfo. Production fapi is geo-blocked from some hosts;
    the testnet host is the fallback and the source string is returned with the ticks.
    """
    urls = [
        "https://fapi.binance.com/fapi/v1/exchangeInfo",
        "https://testnet.binancefuture.com/fapi/v1/exchangeInfo",
    ]
    last_error = "no response"
    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=30) as handle:
                payload = json.loads(handle.read().decode())
        except Exception as exc:  # noqa: BLE001 - try the next public host
            last_error = str(exc)
            continue
        found = {}
        for row in payload.get("symbols") or []:
            if row.get("symbol") not in symbols:
                continue
            for filt in row.get("filters") or []:
                if filt.get("filterType") == "PRICE_FILTER":
                    found[row["symbol"]] = str(filt["tickSize"])
        if all(symbol in found for symbol in symbols):
            return {"ticks": found, "source": url}
        last_error = "symbols missing from " + url
    raise RuntimeError("USD-M exchangeInfo ticks were not found: " + last_error)
