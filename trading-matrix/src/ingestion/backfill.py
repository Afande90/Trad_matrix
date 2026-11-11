from src.ingestion.candle_store import store_candle
from src.ingestion.yfinance_poller import fetch_candles


async def backfill_symbol(symbol: str, asset_class: str, period: str = "5d", interval: str = "1m") -> int:
    candles = fetch_candles(symbol, asset_class, period=period, interval=interval)
    for c in candles:
        await store_candle(
            c["symbol"],
            c["asset_class"],
            c["timestamp"],
            c["open"],
            c["high"],
            c["low"],
            c["close"],
            c["volume"],
            c["source"],
        )
    return len(candles)
