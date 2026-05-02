from __future__ import annotations

import json

import httpx

from .adapter import LLMProvider

_OPENAI_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIAdapter(LLMProvider):
    """OpenAI adapter using the REST API via httpx (no SDK dependency)."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
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
        body = {
            "model": self._model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        resp = httpx.post(
            _OPENAI_URL,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json=body,
            timeout=float(timeout),
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def name(self) -> str:
        return f"openai:{self._model}"
