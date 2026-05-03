from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict

from ..state import StateStore, StoredContext

log = logging.getLogger(__name__)

VALID_SCOPES = {"category", "merchant", "customer", "trigger"}


class ContextService:
    def __init__(self, store: StateStore) -> None:
        self.store = store

    def put(self, scope: str, context_id: str, version: int, payload: Dict[str, Any]) -> dict:
        if scope not in VALID_SCOPES:
            return {
                "accepted": False,
                "reason": "invalid_scope",
                "details": f"scope must be one of {sorted(VALID_SCOPES)}",
            }

        key = (scope, context_id)
        existing = self.store.contexts.get(key)

        if existing is not None and existing.version == version:
            return {
                "accepted": True,
                "ack_id": f"ack_{context_id}_v{version}",
                "stored_at": existing.stored_at.isoformat() + "Z",
            }

        if existing is not None and existing.version > version:
            log.info(
                "context_reject_stale scope=%s id=%s incoming_v=%d current_v=%d",
                scope, context_id, version, existing.version,
            )
            return {
                "accepted": False,
                "reason": "stale_version",
                "current_version": existing.version,
            }

        now = datetime.utcnow()
        self.store.contexts[key] = StoredContext(
            scope=scope,
            context_id=context_id,
            version=version,
            payload=payload,
            stored_at=now,
        )
        log.info(
            "context_accept scope=%s id=%s version=%d",
            scope, context_id, version,
        )
        return {
            "accepted": True,
            "ack_id": f"ack_{context_id}_v{version}",
            "stored_at": now.isoformat() + "Z",
        }

    def get_payload(self, scope: str, context_id: str) -> dict | None:
        stored = self.store.contexts.get((scope, context_id))
        return stored.payload if stored else None
