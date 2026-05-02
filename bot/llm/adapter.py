from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    @abstractmethod
    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 800,
        temperature: float = 0.0,
        timeout: int = 25,
    ) -> str: ...

    @abstractmethod
    def name(self) -> str: ...
