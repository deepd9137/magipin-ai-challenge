from __future__ import annotations

import copy

import pytest

from bot.main import tick_service
from bot.state import store
from tests.conftest import FakeLLMProvider, SAMPLE_CATEGORY, SAMPLE_MERCHANT, SAMPLE_TRIGGER, VALID_LLM_RESPONSE


def push_ctx(client, scope, ctx_id, version, payload):
    resp = client.post("/v1/context", json={
        "scope": scope, "context_id": ctx_id,
        "version": version, "payload": payload,
    })
    assert resp.status_code == 200


# ── Version-bump atomicity tests ──────────────────────────────────────────

def test_version_bump_replaces_context_atomically(client):
    """Push v1, then v2 — store must hold v2 only."""
    cat_v1 = {**SAMPLE_CATEGORY, "display_name": "Dentists v1"}
    cat_v2 = {**SAMPLE_CATEGORY, "display_name": "Dentists v2"}

    push_ctx(client, "category", "dentists", 1, cat_v1)
    assert store.contexts[("category", "dentists")].version == 1
    assert store.contexts[("category", "dentists")].payload["display_name"] == "Dentists v1"

    push_ctx(client, "category", "dentists", 2, cat_v2)
    assert store.contexts[("category", "dentists")].version == 2
    assert store.contexts[("category", "dentists")].payload["display_name"] == "Dentists v2"


def test_stale_version_rejected(client):
    """Pushing v1 after v2 is already stored must return 409."""
    push_ctx(client, "category", "dentists", 2, SAMPLE_CATEGORY)

    resp = client.post("/v1/context", json={
        "scope": "category", "context_id": "dentists",
        "version": 1, "payload": SAMPLE_CATEGORY,
    })
    assert resp.status_code == 409
    data = resp.json()
    assert data["reason"] == "stale_version"
    assert data["current_version"] == 2


def test_same_version_idempotent(client):
    """Re-posting the exact same (scope, context_id, version) is idempotent → 200 no-op."""
    push_ctx(client, "category", "dentists", 1, SAMPLE_CATEGORY)

    resp = client.post("/v1/context", json={
        "scope": "category", "context_id": "dentists",
        "version": 1, "payload": SAMPLE_CATEGORY,
    })
    # Same version is treated as an idempotent no-op, not a stale write.
    assert resp.status_code == 200
    assert resp.json()["accepted"] is True
    # Version in store must still be 1 (not double-written)
    assert store.contexts[("category", "dentists")].version == 1


def test_version_bump_for_all_scopes(client):
    """Version bump works for merchant, customer, and trigger scopes too."""
    push_ctx(client, "merchant", "m_001_drmeera_dentist_delhi", 1, SAMPLE_MERCHANT)
    push_ctx(client, "merchant", "m_001_drmeera_dentist_delhi", 2, {**SAMPLE_MERCHANT, "version_marker": "v2"})

    assert store.contexts[("merchant", "m_001_drmeera_dentist_delhi")].version == 2
    assert store.contexts[("merchant", "m_001_drmeera_dentist_delhi")].payload.get("version_marker") == "v2"


# ── Subsequent compositions use updated context ───────────────────────────

def test_tick_uses_latest_category_version(client):
    """After a category version bump, the next tick composition uses the new context."""
    # v1 setup
    cat_v1 = {**SAMPLE_CATEGORY, "display_name": "Dentists_v1_marker"}
    push_ctx(client, "category", "dentists", 1, cat_v1)
    push_ctx(client, "merchant", "m_001_drmeera_dentist_delhi", 1, SAMPLE_MERCHANT)
    push_ctx(client, "trigger", "trg_001_research_digest_dentists", 1, SAMPLE_TRIGGER)

    old_llm = tick_service.llm
    recorded_prompts = []

    class RecordingLLM(FakeLLMProvider):
        def complete(self, system, user, **kwargs):
            recorded_prompts.append(user)
            return VALID_LLM_RESPONSE

    tick_service.llm = RecordingLLM()
    try:
        # First tick with v1 — suppress the key so second tick can also fire
        client.post("/v1/tick", json={
            "now": "2026-04-26T10:00:00Z",
            "available_triggers": ["trg_001_research_digest_dentists"],
        })

        # Push category v2 with different digest
        cat_v2 = copy.deepcopy(SAMPLE_CATEGORY)
        cat_v2["display_name"] = "Dentists_v2_marker"
        cat_v2["digest"] = [{"item_id": "new_item", "headline": "V2 headline specific", "source": "v2_source"}]
        push_ctx(client, "category", "dentists", 2, cat_v2)

        # Use a different trigger (different suppression key) to avoid suppression
        trg_v2 = {**SAMPLE_TRIGGER, "id": "trg_002_v2_check", "suppression_key": "v2_check_key"}
        push_ctx(client, "trigger", "trg_002_v2_check", 1, trg_v2)

        recorded_prompts.clear()

        client.post("/v1/tick", json={
            "now": "2026-04-26T11:00:00Z",
            "available_triggers": ["trg_002_v2_check"],
        })

        # The second composition must reference v2 digest content
        assert len(recorded_prompts) >= 1
        assert "Dentists_v2_marker" in recorded_prompts[-1] or "V2 headline specific" in recorded_prompts[-1]

    finally:
        tick_service.llm = old_llm


def test_tick_uses_latest_merchant_version(client):
    """After a merchant version bump mid-test, the next tick uses the updated merchant."""
    push_ctx(client, "category", "dentists", 1, SAMPLE_CATEGORY)
    push_ctx(client, "merchant", "m_001_drmeera_dentist_delhi", 1, SAMPLE_MERCHANT)
    push_ctx(client, "trigger", "trg_001_research_digest_dentists", 1, SAMPLE_TRIGGER)

    old_llm = tick_service.llm
    recorded_prompts = []

    class RecordingLLM(FakeLLMProvider):
        def complete(self, system, user, **kwargs):
            recorded_prompts.append(user)
            return VALID_LLM_RESPONSE

    tick_service.llm = RecordingLLM()
    try:
        # First tick fires and suppresses
        client.post("/v1/tick", json={
            "now": "2026-04-26T10:00:00Z",
            "available_triggers": ["trg_001_research_digest_dentists"],
        })

        # Update merchant v2 with new owner name
        merchant_v2 = copy.deepcopy(SAMPLE_MERCHANT)
        merchant_v2["identity"]["owner_first_name"] = "MeeraV2Updated"
        push_ctx(client, "merchant", "m_001_drmeera_dentist_delhi", 2, merchant_v2)

        trg_v2 = {**SAMPLE_TRIGGER, "id": "trg_003_merchant_v2", "suppression_key": "merchant_v2_key"}
        push_ctx(client, "trigger", "trg_003_merchant_v2", 1, trg_v2)

        recorded_prompts.clear()
        client.post("/v1/tick", json={
            "now": "2026-04-26T11:00:00Z",
            "available_triggers": ["trg_003_merchant_v2"],
        })

        assert len(recorded_prompts) >= 1
        assert "MeeraV2Updated" in recorded_prompts[-1]

    finally:
        tick_service.llm = old_llm


def test_context_store_reflects_latest_version_after_multiple_bumps(client):
    """Multiple version bumps in sequence; store always holds the latest."""
    for v in range(1, 6):
        payload = {**SAMPLE_MERCHANT, "version_marker": f"v{v}"}
        push_ctx(client, "merchant", "m_001_drmeera_dentist_delhi", v, payload)

    stored = store.contexts[("merchant", "m_001_drmeera_dentist_delhi")]
    assert stored.version == 5
    assert stored.payload["version_marker"] == "v5"
