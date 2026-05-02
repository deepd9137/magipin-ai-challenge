from __future__ import annotations

import anthropic

from .adapter import LLMProvider


class AnthropicAdapter(LLMProvider):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6") -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 800,
        temperature: float = 0.0,
        timeout: int = 25,
    ) -> str:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
            timeout=float(timeout),
        )
        return resp.content[0].text  # type: ignore[union-attr]

    def name(self) -> str:
        return f"anthropic:{self._model}"
