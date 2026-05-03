from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class StoredContext:
    scope: str
    context_id: str
    version: int
    payload: Dict[str, Any]
    stored_at: datetime


@dataclass
class Turn:
    ts: datetime
    from_role: str          # "vera" | "merchant" | "customer"
    body: str
    kind: str               # "send" | "wait" | "end" | "reply"
    cta: Optional[str] = None
    intent_classified: Optional[str] = None


@dataclass
class ComposedMessage:
    body: str
    cta: str
    send_as: str            # "vera" | "merchant_on_behalf"
    suppression_key: str
    rationale: str
    template_name: str
    template_params: List[str]


class StateStore:
    def __init__(self) -> None:
        self.contexts: Dict[Tuple[str, str], StoredContext] = {}
        self.conversations: Dict[str, List[Turn]] = {}
        self.suppressed_keys: Set[str] = set()
        self.ended_conversations: Set[str] = set()

    def counts_by_scope(self) -> Dict[str, int]:
        out: Dict[str, int] = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
        for scope, _ in self.contexts:
            out[scope] = out.get(scope, 0) + 1
        return out

    def reset(self) -> None:
        """Full in-memory reset — used in tests only."""
        self.contexts.clear()
        self.conversations.clear()
        self.suppressed_keys.clear()
        self.ended_conversations.clear()


store = StateStore()
