import json


def parse_llm_json(text: str) -> dict:
    t = (text or "").strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
        if t.lower().startswith("json"):
            t = t[4:].strip()
    return json.loads(t)


def build_prompt(candles: list[dict], indicators: dict) -> str:
    tail = candles[-30:]
    summary = [
        {"t": c.get("timestamp"), "o": c.get("open"), "h": c.get("high"), "l": c.get("low"), "c": c.get("close"), "v": c.get("volume")}
        for c in tail
    ]
    return (
        "You are a market lens. Using only this candle summary and indicators, "
        "reply with EXACT JSON and nothing else: "
        '{"direction": "UP|DOWN|SIDEWAYS", "confidence": 0.0-1.0, "reasoning": "..."}\n'
        f"CANDLES={summary}\nINDICATORS={indicators}"
    )
