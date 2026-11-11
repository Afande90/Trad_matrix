import os

from src.prediction.schemas import LensResult
from src.providers.base import RateLimitError
from src.providers.gemini import _from_json
from src.providers.parse import build_prompt


class GroqProvider:
    name = "groq"

    def __init__(self, client=None, api_key: str | None = None):
        self.client = client
        self.api_key = api_key if api_key is not None else os.getenv("GROQ_API_KEY", "")

    async def predict(self, candles: list[dict], indicators: dict) -> LensResult:
        prompt = build_prompt(candles, indicators)
        response = await self.client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": "llama-3.1-8b-instant",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
            },
        )
        if response.status_code == 429:
            raise RateLimitError("groq 429")
        if response.status_code >= 400:
            raise RuntimeError(f"groq http {response.status_code}")
        text = response.json()["choices"][0]["message"]["content"]
        return _from_json(text, "groq")
