from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from bot.state import StateStore, StoredContext

VALID_SCOPES = frozenset({"category", "merchant", "customer", "trigger"})


class ContextService:
    def __init__(self, store: StateStore) -> None:
        self.store = store

    def put(self, scope: str, context_id: str, version: int, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        if scope not in VALID_SCOPES:
            return 400, {
                "accepted": False,
                "reason": "invalid_scope",
                "details": f"scope must be one of: category, customer, merchant, trigger",
            }

        key = (scope, context_id)
        current = self.store.contexts.get(key)

        if current is not None and current.version >= version:
            return 409, {
                "accepted": False,
                "reason": "stale_version",
                "current_version": current.version,
            }

        now = datetime.now(timezone.utc)
        self.store.contexts[key] = StoredContext(
            scope=scope,
            context_id=context_id,
            version=version,
            payload=payload,
            stored_at=now,
        )
        return 200, {
            "accepted": True,
            "ack_id": f"ack_{context_id}_v{version}",
            "stored_at": now.isoformat().replace("+00:00", "Z"),
        }
