import yfinance as yf

from src.ingestion.market_hours import is_market_open


def fetch_candles(symbol: str, asset_class: str, period: str = "1d", interval: str = "1m") -> list[dict]:
    df = yf.Ticker(symbol).history(period=period, interval=interval)
    out = []
    for ts, row in df.iterrows():
        out.append(
            {
                "symbol": symbol,
                "asset_class": asset_class,
                "timestamp": int(ts.timestamp() * 1000),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row["Volume"]),
                "source": "YFINANCE",
            }
        )
    return out


def poll_symbol(symbol: str, asset_class: str) -> list[dict]:
    if not is_market_open(asset_class):
        return []
    return fetch_candles(symbol, asset_class)
