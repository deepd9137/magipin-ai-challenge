from __future__ import annotations

from .state import StateStore


class SuppressionTracker:
    """Thin wrapper around StateStore.suppressed_keys for clean suppression API."""

    def __init__(self, store: StateStore) -> None:
        self._store = store

    def is_suppressed(self, key: str) -> bool:
        return bool(key) and key in self._store.suppressed_keys

    def mark_fired(self, key: str) -> None:
        if key:
            self._store.suppressed_keys.add(key)
