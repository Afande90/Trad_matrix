"""MT5 if connected and the symbol is available, else Binance for crypto, else yfinance."""

from __future__ import annotations

from src.ingestion.mt5_adapter import mt5_configured


def choose_source(symbol: str, asset_class: str, mt5_symbols: set[str] | None = None) -> str:
    if mt5_configured() and mt5_symbols and symbol in mt5_symbols and asset_class in ("FOREX", "STOCK", "COMMODITY"):
        return "MT5"
    if asset_class == "CRYPTO":
        return "BINANCE_WS"
    return "YFINANCE"
