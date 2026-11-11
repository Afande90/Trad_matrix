"""Optional MT5 adapter. Blank credentials skip it with no error."""

from __future__ import annotations

import os


def mt5_configured() -> bool:
    return bool(os.getenv("MT5_LOGIN") and os.getenv("MT5_PASSWORD") and os.getenv("MT5_SERVER"))


def fetch_mt5_candles(symbol: str, asset_class: str, count: int = 500) -> list[dict]:
    if not mt5_configured():
        return []
    from metatrader_client import MetatraderClient  # type: ignore

    client = MetatraderClient(
        login=os.environ["MT5_LOGIN"],
        password=os.environ["MT5_PASSWORD"],
        server=os.environ["MT5_SERVER"],
        path=os.getenv("MT5_PATH") or None,
    )
    frame = client.market.get_candles_latest(symbol, timeframe="M1", count=count)
    out = []
    for ts, row in frame.iterrows():
        out.append(
            {
                "symbol": symbol,
                "asset_class": asset_class,
                "timestamp": int(ts.timestamp() * 1000),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume", 0.0)),
                "source": "MT5",
            }
        )
    return out
