"""Gemini embeddings. Failure is non-fatal: the prediction is stored with NULL."""

from __future__ import annotations

import logging
import os

log = logging.getLogger("trading_matrix.embedder")


async def embed_text(text: str, client=None) -> list[float] | None:
    key = os.getenv("GEMINI_API_KEY", "")
    if client is None:
        if not key:
            log.warning("embed skipped: no GEMINI_API_KEY")
            return None
        import httpx

        client = httpx.AsyncClient(timeout=30.0)
        close = True
    else:
        close = False
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"text-embedding-004:embedContent?key={key}"
    )
    try:
        response = await client.post(url, json={"content": {"parts": [{"text": text}]}})
        if getattr(response, "status_code", 200) >= 400:
            raise RuntimeError(f"embed http {response.status_code}")
        data = response.json()
        values = data["embedding"]["values"]
        return [float(v) for v in values]
    except Exception as exc:  # noqa: BLE001 — non-fatal by spec
        log.warning("embedding failed, storing NULL: %s", exc)
        return None
    finally:
        if close:
            await client.aclose()
