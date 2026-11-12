import os

from src.prediction.schemas import LensResult
from src.providers.base import RateLimitError
from src.providers.gemini import _from_json
from src.providers.parse import build_prompt


class OpenRouterProvider:
    name = "openrouter"

    def __init__(self, client=None, api_key: str | None = None, model: str | None = None):
        self.client = client
        self.api_key = api_key if api_key is not None else os.getenv("OPENROUTER_API_KEY", "")
        self.model = model or os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct:free")

    async def predict(self, candles: list[dict], indicators: dict) -> LensResult:
        prompt = build_prompt(candles, indicators)
        response = await self.client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
            },
        )
        if response.status_code == 429:
            raise RateLimitError("openrouter 429")
        if response.status_code >= 400:
            raise RuntimeError(f"openrouter http {response.status_code}")
        text = response.json()["choices"][0]["message"]["content"]
        return _from_json(text, self.model)
