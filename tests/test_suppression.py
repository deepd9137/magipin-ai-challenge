from __future__ import annotations

import pytest

from bot.state import StateStore
from bot.suppression import SuppressionTracker


@pytest.fixture
def tracker():
    store = StateStore()
    return SuppressionTracker(store)


def test_not_suppressed_initially(tracker):
    assert not tracker.is_suppressed("some_key")


def test_mark_fired_then_suppressed(tracker):
    tracker.mark_fired("research:dentists:2026-W17")
    assert tracker.is_suppressed("research:dentists:2026-W17")


def test_other_keys_not_affected(tracker):
    tracker.mark_fired("key_a")
    assert not tracker.is_suppressed("key_b")


def test_mark_fired_empty_key_is_noop(tracker):
    tracker.mark_fired("")
    assert not tracker.is_suppressed("")


def test_mark_fired_none_is_noop():
    store = StateStore()
    st = SuppressionTracker(store)
    st.mark_fired(None)  # type: ignore[arg-type]
    assert len(store.suppressed_keys) == 0


def test_is_suppressed_empty_key_returns_false(tracker):
    assert not tracker.is_suppressed("")


def test_mark_fired_multiple_keys(tracker):
    keys = ["k1", "k2", "k3"]
    for k in keys:
        tracker.mark_fired(k)
    for k in keys:
        assert tracker.is_suppressed(k)
    assert not tracker.is_suppressed("k4")


def test_suppression_reflects_underlying_store():
    """Writes via tracker are visible in store.suppressed_keys directly."""
    store = StateStore()
    st = SuppressionTracker(store)
    st.mark_fired("direct_check_key")
    assert "direct_check_key" in store.suppressed_keys
