from src.db import get_db


async def store_candle(
    symbol: str,
    asset_class: str,
    timestamp: int,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float,
    source: str,
) -> None:
    payload = {
        "symbol": symbol,
        "asset_class": asset_class,
        "timestamp": int(timestamp),
        "open": float(open_),
        "high": float(high),
        "low": float(low),
        "close": float(close),
        "volume": float(volume),
        "source": source,
    }
    get_db().table("candles").upsert(payload, on_conflict="symbol,timestamp").execute()


def get_candles(symbol: str | None = None, limit: int = 500, asset_class: str | None = None) -> list[dict]:
    query = get_db().table("candles").select("*")
    if symbol is not None:
        query = query.eq("symbol", symbol)
    if asset_class is not None:
        query = query.eq("asset_class", asset_class)
    data = query.order("timestamp", desc=False).limit(limit).execute().data
    return list(data or [])
