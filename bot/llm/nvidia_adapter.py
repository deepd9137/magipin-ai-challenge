from __future__ import annotations

import httpx

from .adapter import LLMProvider

_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"


class NvidiaAdapter(LLMProvider):
    """NVIDIA NIM API adapter — OpenAI-compatible endpoint via httpx."""

    def __init__(self, api_key: str, model: str = "openai/gpt-oss-20b") -> None:
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
        # Reasoning models consume tokens for CoT before writing content;
        # always request at least 4096 to ensure the final answer is produced.
        effective_max_tokens = max(max_tokens, 4096)
        resp = httpx.post(
            f"{_NVIDIA_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": temperature,
                "top_p": 1,
                "max_tokens": effective_max_tokens,
                "stream": False,
            },
            timeout=float(timeout),
        )
        resp.raise_for_status()
        message = resp.json()["choices"][0]["message"]
        content = message.get("content")
        if content is None:
            # Reasoning model exhausted tokens before completing content — treat as failure
            raise RuntimeError(
                f"NVIDIA model returned null content (finish_reason="
                f"{resp.json()['choices'][0].get('finish_reason')}); "
                "increase max_tokens or shorten prompt"
            )
        return content

    def name(self) -> str:
        return f"nvidia:{self._model}"
