from __future__ import annotations

import logging
from typing import List

import httpx

from .adapter import LLMProvider

log = logging.getLogger(__name__)

# HTTP status codes that mean "this provider can't serve me right now"
_TRANSIENT_STATUSES = {429, 503, 529}

# Anthropic's credit-exhausted error string (comes back as 400)
_CREDIT_MESSAGES = ("credit balance is too low", "insufficient_quota", "billing")


def _is_fallback_worthy(exc: Exception) -> bool:
    """True when the error is a provider-side capacity/billing issue, not a bad request."""
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code in _TRANSIENT_STATUSES:
            return True
        if exc.response.status_code == 400:
            body = exc.response.text.lower()
            return any(msg in body for msg in _CREDIT_MESSAGES)
    # Anthropic SDK raises anthropic.APIStatusError (not httpx); catch by message string
    msg = str(exc).lower()
    return any(phrase in msg for phrase in _CREDIT_MESSAGES + ("rate limit", "too many requests"))


class FallbackLLMProvider(LLMProvider):
    """
    Tries each provider in order. Falls through to the next on credit exhaustion,
    rate limits, or service unavailability. Raises the last exception if all fail.
    """

    def __init__(self, providers: List[LLMProvider]) -> None:
        if not providers:
            raise ValueError("FallbackLLMProvider requires at least one provider")
        self._providers = providers

    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 800,
        temperature: float = 0.0,
        timeout: int = 25,
    ) -> str:
        last_exc: Exception = RuntimeError("No providers configured")
        for provider in self._providers:
            try:
                result = provider.complete(system, user, max_tokens, temperature, timeout)
                log.info("llm_provider_used provider=%s", provider.name())
                return result
            except Exception as exc:
                if _is_fallback_worthy(exc):
                    log.warning(
                        "llm_fallback provider=%s reason=%s next=%s",
                        provider.name(),
                        type(exc).__name__,
                        self._providers[self._providers.index(provider) + 1].name()
                        if self._providers.index(provider) + 1 < len(self._providers)
                        else "none",
                    )
                    last_exc = exc
                    continue
                raise  # non-transient error (bad prompt, auth failure) — don't fall through
        raise last_exc

    def name(self) -> str:
        return f"fallback({','.join(p.name() for p in self._providers)})"
