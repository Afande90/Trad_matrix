from datetime import datetime, timezone

import pytest

from src.charts.renderer import render_chart_image
from src.ingestion.backfill import backfill_symbol
from src.ingestion.binance_ws import connect_binance, parse_kline_message, stream_url
from src.ingestion.candle_store import get_candles, store_candle
from src.ingestion.market_hours import is_market_open


def _candle(symbol, asset, ts, close=1.0):
    return dict(symbol=symbol, asset_class=asset, timestamp=ts, open_=close, high=close, low=close, close=close, volume=1.0, source="TEST")


@pytest.mark.asyncio
async def test_candle_store_insert():
    await store_candle("BTCUSDT", "CRYPTO", 1, 10, 11, 9, 10.5, 3, "BINANCE_WS")
    rows = get_candles("BTCUSDT")
    assert rows[0]["close"] == 10.5
    assert rows[0]["volume"] == 3
    assert rows[0]["asset_class"] == "CRYPTO"


@pytest.mark.asyncio
async def test_candle_store_upsert():
    await store_candle("BTCUSDT", "CRYPTO", 1, 10, 11, 9, 10.5, 3, "BINANCE_WS")
    await store_candle("BTCUSDT", "CRYPTO", 1, 10, 12, 8, 11.5, 4, "BINANCE_WS")
    rows = get_candles("BTCUSDT")
    assert len(rows) == 1
    assert rows[0]["close"] == 11.5


@pytest.mark.asyncio
async def test_candle_store_multi_asset():
    await store_candle("BTCUSDT", "CRYPTO", 1, 1, 1, 1, 1, 1, "BINANCE_WS")
    await store_candle("AAPL", "STOCK", 2, 2, 2, 2, 2, 2, "YFINANCE")
    await store_candle("EURUSD=X", "FOREX", 3, 3, 3, 3, 3, 3, "YFINANCE")
    stocks = get_candles(asset_class="STOCK")
    assert [r["symbol"] for r in stocks] == ["AAPL"]


def test_market_hours_crypto():
    assert is_market_open("CRYPTO", datetime(2026, 11, 14, 15, tzinfo=timezone.utc)) is True


def test_market_hours_stock_weekend():
    assert is_market_open("STOCK", datetime(2026, 11, 14, 15, tzinfo=timezone.utc)) is False


def test_market_hours_forex_weekday():
    # Tuesday 16:00 UTC is 11:00 ET in November (EST).
    assert is_market_open("FOREX", datetime(2026, 11, 10, 16, tzinfo=timezone.utc)) is True


@pytest.mark.asyncio
async def test_backfill_yfinance(monkeypatch):
    def fake_fetch(symbol, asset_class, period="1d", interval="1m"):
        return [
            {
                "symbol": symbol,
                "asset_class": asset_class,
                "timestamp": 5,
                "open": 1,
                "high": 2,
                "low": 1,
                "close": 2,
                "volume": 9,
                "source": "YFINANCE",
            }
        ]

    monkeypatch.setattr("src.ingestion.backfill.fetch_candles", fake_fetch)
    n = await backfill_symbol("AAPL", "STOCK")
    assert n == 1
    assert get_candles("AAPL")[0]["asset_class"] == "STOCK"


@pytest.mark.asyncio
async def test_reconnection():
    sleeps = []

    class Boom(Exception):
        pass

    attempts = {"n": 0}

    def connect(url):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise Boom("drop")

        class WS:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

        return WS()

    async def sleeper(delay):
        sleeps.append(delay)

    await connect_binance(
        "BTCUSDT",
        connect=connect,
        sleep=sleeper,
        max_attempts=3,
        stop_after_success=True,
    )
    assert sleeps[:2] == [1.0, 2.0]


def test_chart_render():
    candles = [
        {"open": 100 + i, "high": 101 + i, "low": 99 + i, "close": 100.5 + i, "volume": 1}
        for i in range(100)
    ]
    png = render_chart_image(candles, "BTC")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_parse_kline_only_when_closed():
    assert parse_kline_message({"e": "kline", "k": {"x": False, "s": "BTCUSDT", "t": 1, "o": "1", "h": "1", "l": "1", "c": "1", "v": "1"}}) is None
    candle = parse_kline_message({"e": "kline", "k": {"x": True, "s": "BTCUSDT", "t": 1, "o": "1", "h": "2", "l": "1", "c": "2", "v": "3"}})
    assert candle["close"] == 2.0


def test_futures_stream_url():
    assert stream_url("XAUUSDT", market="futures") == "wss://fstream.binance.com/ws/xauusdt@kline_1m"
    assert stream_url("BTCUSDT", market="spot").startswith("wss://stream.binance.com:9443/ws/btcusdt@kline_1m")
