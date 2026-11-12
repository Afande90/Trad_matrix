from src.prediction.schemas import LensResult


async def predict_with_failover(providers, candles, indicators) -> LensResult:
    """Gemini → Groq → OpenRouter. Any exception moves to the next provider."""
    for provider in providers:
        try:
            result = await provider.predict(candles, indicators)
            result.raw_data["model_used"] = provider.name
            return result
        except Exception:
            continue
    return LensResult(
        "ai_model",
        "SIDEWAYS",
        0.0,
        "All AI providers failed; abstaining",
        {"model_used": "none"},
    )
