from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional


@dataclass
class StoredContext:
    scope: str
    context_id: str
    version: int
    payload: dict[str, Any]
    stored_at: datetime


@dataclass
class Turn:
    ts: datetime
    from_role: str          # "vera" | "merchant" | "customer"
    body: str
    kind: str               # "send" | "wait" | "end" | "reply"
    cta: Optional[str] = None
    intent_classified: Optional[str] = None


class StateStore:
    def __init__(self) -> None:
        self.contexts: dict[tuple[str, str], StoredContext] = {}
        self.conversations: dict[str, list[Turn]] = {}
        self.suppressed_keys: set[str] = set()
        self.ended_conversations: set[str] = set()

    def counts_by_scope(self) -> dict[str, int]:
        out: dict[str, int] = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
        for scope, _ in self.contexts:
            if scope in out:
                out[scope] += 1
        return out

    def get_context(self, scope: str, context_id: str) -> Optional[StoredContext]:
        return self.contexts.get((scope, context_id))


store = StateStore()
