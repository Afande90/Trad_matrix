"""Binance kline streams. Spot and USD-M futures use different hosts.

Spot base (TECHNICAL_SPEC): wss://stream.binance.com:9443/ws/
USD-M futures base (Binance USD-M docs, same product as data.binance.vision
futures/um): wss://fstream.binance.com/ws/
"""

from __future__ import annotations

import asyncio
import json

import websockets

from src.ingestion.candle_store import store_candle

SPOT_WS = "wss://stream.binance.com:9443/ws"
FUTURES_WS = "wss://fstream.binance.com/ws"


def stream_url(symbol: str, market: str = "spot", stream: str = "kline_1m") -> str:
    host = FUTURES_WS if market == "futures" else SPOT_WS
    return f"{host}/{symbol.lower()}@{stream}"


def parse_kline_message(payload: dict) -> dict | None:
    if payload.get("e") != "kline" or not payload.get("k", {}).get("x"):
        return None
    k = payload["k"]
    return {
        "symbol": k["s"],
        "timestamp": int(k["t"]),
        "open": float(k["o"]),
        "high": float(k["h"]),
        "low": float(k["l"]),
        "close": float(k["c"]),
        "volume": float(k["v"]),
    }


def next_delay(delay: float) -> float:
    return min(delay * 2, 60)


async def connect_binance(
    symbol: str,
    *,
    market: str = "spot",
    connect=None,
    store=None,
    sleep=None,
    max_attempts: int | None = None,
    stop_after_success: bool = False,
):
    url = stream_url(symbol, market=market)
    connector = connect or websockets.connect
    saver = store or _default_store
    sleeper = sleep or asyncio.sleep
    delay = 1.0
    attempt = 0
    while True:
        attempt += 1
        try:
            async with connector(url) as ws:
                delay = 1.0
                async for msg in ws:
                    if isinstance(msg, bytes):
                        msg = msg.decode()
                    payload = json.loads(msg)
                    candle = parse_kline_message(payload)
                    if candle is None:
                        continue
                    asset = "SCALP_METAL" if market == "futures" and symbol.upper() in ("XAUUSDT", "XAGUSDT") else "CRYPTO"
                    await saver(
                        candle["symbol"],
                        asset,
                        candle["timestamp"],
                        candle["open"],
                        candle["high"],
                        candle["low"],
                        candle["close"],
                        candle["volume"],
                        "BINANCE_WS",
                    )
            if stop_after_success:
                return
        except Exception as exc:
            print(f"Binance WS error: {exc}; retry in {delay}s")
            await sleeper(delay)
            delay = next_delay(delay)
        if max_attempts is not None and attempt >= max_attempts:
            return


async def _default_store(symbol, asset_class, timestamp, open_, high, low, close, volume, source):
    await store_candle(symbol, asset_class, timestamp, open_, high, low, close, volume, source)
