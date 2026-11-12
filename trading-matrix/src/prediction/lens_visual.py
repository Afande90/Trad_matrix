"""Visual lens. Five charts, oldest timeframe first. Failure abstains."""

from __future__ import annotations

import base64

from src.charts.renderer import render_chart_image
from src.prediction.schemas import LensResult
from src.providers.base import RateLimitError
from src.providers.gemini import _from_json

TIMEFRAMES = [
    ("6 months", "1d", 180),
    ("1 month", "4h", 180),
    ("1 week", "1h", 168),
    ("24 hours", "15m", 96),
    ("4 hours", "5m", 48),
]


def adjust_visual_confidence(confidence: float, agreement: int) -> float:
    if agreement >= 5:
        return min(1.0, confidence * 1.2)
    if agreement < 3:
        return confidence * 0.6
    return confidence


def resample_ohlcv(candles: list[dict], rule: str) -> list[dict]:
    import pandas as pd

    if not candles:
        return []
    frame = pd.DataFrame(candles)
    frame["dt"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
    frame = frame.set_index("dt").sort_index()
    agg = frame.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    agg = agg.dropna(subset=["open", "close"])
    # Drop the still-forming last bucket when the source does not end on a boundary.
    if len(agg) > 1:
        agg = agg.iloc[:-1]
    out = []
    for ts, row in agg.iterrows():
        out.append(
            {
                "timestamp": int(ts.timestamp() * 1000),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            }
        )
    return out


async def run_visual(candles: list[dict], client, renderer=None) -> LensResult:
    """Send the five PNGs oldest-timeframe first. Any failure abstains."""
    draw = render_chart_image if renderer is None else renderer
    try:
        parts = []
        labels = []
        for label, rule, count in TIMEFRAMES:
            series = resample_ohlcv(candles, rule)[-count:]
            if len(series) < 2:
                series = candles[-count:]
            png = draw(series, label)
            labels.append(label)
            parts.append({"inline_data": {"mime_type": "image/png", "data": base64.b64encode(png).decode()}})
        prompt = (
            "Charts are in temporal order from the oldest timeframe to the newest "
            f"({', '.join(labels)}). Reply with EXACT JSON: "
            '{"direction": "UP|DOWN|SIDEWAYS", "confidence": 0.0, "reasoning": "...", '
            '"surprise_factors": [], "timeframe_agreement": 0}'
        )
        parts.append({"text": prompt})
        response = await client.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
            json={"contents": [{"parts": parts}], "generationConfig": {"temperature": 0.1}},
        )
        if getattr(response, "status_code", 200) == 429:
            raise RateLimitError("visual 429")
        if getattr(response, "status_code", 200) >= 400:
            raise RuntimeError("visual http")
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        result = _from_json(text, "gemini-vision")
        result.lens_name = "visual"
        parsed_agreement = 0
        surprise = []
        try:
            import json

            raw_text = text
            from src.providers.parse import parse_llm_json

            blob = parse_llm_json(raw_text)
            parsed_agreement = int(blob.get("timeframe_agreement") or 0)
            surprise = blob.get("surprise_factors") or []
        except Exception:
            parsed_agreement = 0
        result.confidence = adjust_visual_confidence(result.confidence, parsed_agreement)
        result.raw_data = {
            "model_used": "gemini-vision",
            "timeframes_analyzed": labels,
            "timeframe_agreement": parsed_agreement,
            "surprise_factors": surprise,
            "method": "jepa_backward_forward_scan",
        }
        return result
    except Exception:
        return LensResult(
            "visual",
            "SIDEWAYS",
            0.0,
            "Visual lens abstained",
            {
                "model_used": "gemini-vision",
                "timeframes_analyzed": [t[0] for t in TIMEFRAMES],
                "timeframe_agreement": 0,
                "surprise_factors": [],
                "method": "jepa_backward_forward_scan",
            },
        )
