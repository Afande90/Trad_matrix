import os

from src.prediction.schemas import LensResult
from src.providers.base import RateLimitError
from src.providers.parse import build_prompt, parse_llm_json


class GeminiProvider:
    name = "gemini"

    def __init__(self, client=None, api_key: str | None = None):
        self.client = client
        self.api_key = api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "")

    async def predict(self, candles: list[dict], indicators: dict) -> LensResult:
        prompt = build_prompt(candles, indicators)
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.0-flash:generateContent?key={self.api_key}"
        )
        body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.1}}
        response = await self.client.post(url, json=body)
        if response.status_code == 429:
            raise RateLimitError("gemini 429")
        if response.status_code >= 400:
            raise RuntimeError(f"gemini http {response.status_code}")
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return _from_json(text, "gemini")


def _from_json(text: str, model: str) -> LensResult:
    parsed = parse_llm_json(text)
    direction = str(parsed["direction"]).upper()
    if direction not in ("UP", "DOWN", "SIDEWAYS"):
        raise ValueError(f"bad direction {direction}")
    conf = float(parsed["confidence"])
    return LensResult(
        "ai_model",
        direction,
        max(0.0, min(1.0, conf)),
        str(parsed.get("reasoning", "")),
        {"model_used": model},
    )
