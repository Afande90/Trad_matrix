from abc import ABC, abstractmethod


class RateLimitError(Exception):
    pass


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def predict(self, candles: list[dict], indicators: dict):
        ...
