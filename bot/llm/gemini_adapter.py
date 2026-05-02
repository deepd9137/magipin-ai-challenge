from __future__ import annotations

import time

import httpx

from .adapter import LLMProvider

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_RATE_LIMIT_BACKOFF = 5  # seconds to wait on 429 before one retry


class GeminiAdapter(LLMProvider):
    """Gemini adapter using the REST API via httpx (no SDK dependency)."""

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        self._api_key = api_key
        self._model = model

    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 800,
        temperature: float = 0.0,
        timeout: int = 25,
    ) -> str:
        url = _GEMINI_URL.format(model=self._model)
        body = {
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        deadline = time.time() + timeout
        for attempt in range(2):
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError("Gemini call exceeded budget before sending")
            resp = httpx.post(
                url,
                params={"key": self._api_key},
                json=body,
                timeout=min(remaining, float(timeout)),
            )
            if resp.status_code == 429 and attempt == 0:
                wait = min(_RATE_LIMIT_BACKOFF, max(0, deadline - time.time() - 2))
                if wait > 0:
                    time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        resp.raise_for_status()  # will raise the last 429
        return ""  # unreachable

    def name(self) -> str:
        return f"gemini:{self._model}"
