from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bot.main import app, tick_service
from bot.state import store
from tests.conftest import (
    FakeLLMProvider,
    SAMPLE_CATEGORY,
    SAMPLE_MERCHANT,
    SAMPLE_TRIGGER,
    VALID_LLM_RESPONSE,
)


# ── Helpers ───────────────────────────────────────────────────────────────

def push_context(client, scope, ctx_id, version, payload):
    resp = client.post("/v1/context", json={
        "scope": scope,
        "context_id": ctx_id,
        "version": version,
        "payload": payload,
    })
    assert resp.status_code == 200


def setup_full_context(client):
    """Push category + merchant + trigger so tick can compose."""
    push_context(client, "category", "dentists", 1, SAMPLE_CATEGORY)
    push_context(client, "merchant", "m_001_drmeera_dentist_delhi", 1, SAMPLE_MERCHANT)
    push_context(client, "trigger", "trg_001_research_digest_dentists", 1, SAMPLE_TRIGGER)


# ── Tests ─────────────────────────────────────────────────────────────────

def test_tick_empty_triggers(client):
    resp = client.post("/v1/tick", json={"now": "2026-04-26T10:00:00Z", "available_triggers": []})
    assert resp.status_code == 200
    assert resp.json()["actions"] == []


def test_tick_skips_unknown_trigger(client):
    resp = client.post("/v1/tick", json={
        "now": "2026-04-26T10:00:00Z",
        "available_triggers": ["trg_nonexistent"],
    })
    assert resp.json()["actions"] == []


def test_tick_skips_when_merchant_missing(client):
    push_context(client, "category", "dentists", 1, SAMPLE_CATEGORY)
    push_context(client, "trigger", "trg_001_research_digest_dentists", 1, SAMPLE_TRIGGER)
    # merchant NOT pushed

    old_llm = tick_service.llm
    tick_service.llm = FakeLLMProvider(VALID_LLM_RESPONSE)
    try:
        resp = client.post("/v1/tick", json={
            "now": "2026-04-26T10:00:00Z",
            "available_triggers": ["trg_001_research_digest_dentists"],
        })
        assert resp.json()["actions"] == []
    finally:
        tick_service.llm = old_llm


def test_tick_skips_when_category_missing(client):
    # No category pushed
    push_context(client, "merchant", "m_001_drmeera_dentist_delhi", 1, SAMPLE_MERCHANT)
    push_context(client, "trigger", "trg_001_research_digest_dentists", 1, SAMPLE_TRIGGER)

    old_llm = tick_service.llm
    tick_service.llm = FakeLLMProvider(VALID_LLM_RESPONSE)
    try:
        resp = client.post("/v1/tick", json={
            "now": "2026-04-26T10:00:00Z",
            "available_triggers": ["trg_001_research_digest_dentists"],
        })
        assert resp.json()["actions"] == []
    finally:
        tick_service.llm = old_llm


def test_tick_skips_expired_trigger(client):
    expired_trigger = {**SAMPLE_TRIGGER, "expires_at": "2020-01-01T00:00:00Z"}
    push_context(client, "category", "dentists", 1, SAMPLE_CATEGORY)
    push_context(client, "merchant", "m_001_drmeera_dentist_delhi", 1, SAMPLE_MERCHANT)
    push_context(client, "trigger", "trg_001_research_digest_dentists", 1, expired_trigger)

    resp = client.post("/v1/tick", json={
        "now": "2026-04-26T10:00:00Z",
        "available_triggers": ["trg_001_research_digest_dentists"],
    })
    assert resp.json()["actions"] == []


def test_tick_skips_suppressed_trigger(client):
    setup_full_context(client)
    store.suppressed_keys.add("research:dentists:2026-W17")

    old_llm = tick_service.llm
    tick_service.llm = FakeLLMProvider(VALID_LLM_RESPONSE)
    try:
        resp = client.post("/v1/tick", json={
            "now": "2026-04-26T10:00:00Z",
            "available_triggers": ["trg_001_research_digest_dentists"],
        })
        assert resp.json()["actions"] == []
    finally:
        tick_service.llm = old_llm


def test_tick_returns_full_action_schema(client):
    setup_full_context(client)

    old_llm = tick_service.llm
    tick_service.llm = FakeLLMProvider(VALID_LLM_RESPONSE)
    try:
        resp = client.post("/v1/tick", json={
            "now": "2026-04-26T10:00:00Z",
            "available_triggers": ["trg_001_research_digest_dentists"],
        })
        assert resp.status_code == 200
        actions = resp.json()["actions"]
        assert len(actions) == 1
        action = actions[0]

        required = [
            "conversation_id", "merchant_id", "send_as", "trigger_id",
            "template_name", "template_params", "body", "cta",
            "suppression_key", "rationale",
        ]
        for field in required:
            assert field in action, f"missing field: {field}"

        assert action["trigger_id"] == "trg_001_research_digest_dentists"
        assert action["merchant_id"] == "m_001_drmeera_dentist_delhi"
        assert action["send_as"] == "vera"
        assert action["cta"] in {"open_ended", "binary_yes_no", "binary_confirm_cancel", "multi_choice_slot", "none"}
        assert len(action["body"]) >= 10
    finally:
        tick_service.llm = old_llm


def test_tick_marks_suppression_key_fired(client):
    setup_full_context(client)

    old_llm = tick_service.llm
    tick_service.llm = FakeLLMProvider(VALID_LLM_RESPONSE)
    try:
        client.post("/v1/tick", json={
            "now": "2026-04-26T10:00:00Z",
            "available_triggers": ["trg_001_research_digest_dentists"],
        })
        assert "research:dentists:2026-W17" in store.suppressed_keys
    finally:
        tick_service.llm = old_llm


def test_tick_does_not_fire_same_suppression_key_twice(client):
    setup_full_context(client)

    old_llm = tick_service.llm
    tick_service.llm = FakeLLMProvider(VALID_LLM_RESPONSE)
    try:
        # First tick
        resp1 = client.post("/v1/tick", json={
            "now": "2026-04-26T10:00:00Z",
            "available_triggers": ["trg_001_research_digest_dentists"],
        })
        assert len(resp1.json()["actions"]) == 1

        # Second tick same trigger
        resp2 = client.post("/v1/tick", json={
            "now": "2026-04-26T11:00:00Z",
            "available_triggers": ["trg_001_research_digest_dentists"],
        })
        assert len(resp2.json()["actions"]) == 0
    finally:
        tick_service.llm = old_llm


def test_tick_caps_at_20_actions(client):
    """25 triggers → at most 20 actions returned."""
    push_context(client, "category", "dentists", 1, SAMPLE_CATEGORY)
    push_context(client, "merchant", "m_001_drmeera_dentist_delhi", 1, SAMPLE_MERCHANT)

    trigger_ids = []
    for i in range(25):
        trg_id = f"trg_bulk_{i:03d}"
        trg = {
            **SAMPLE_TRIGGER,
            "id": trg_id,
            "suppression_key": f"bulk_{i}",
        }
        push_context(client, "trigger", trg_id, 1, trg)
        trigger_ids.append(trg_id)

    old_llm = tick_service.llm
    tick_service.llm = FakeLLMProvider(VALID_LLM_RESPONSE)
    try:
        resp = client.post("/v1/tick", json={
            "now": "2026-04-26T10:00:00Z",
            "available_triggers": trigger_ids,
        })
        assert resp.status_code == 200
        assert len(resp.json()["actions"]) <= 20
    finally:
        tick_service.llm = old_llm


def test_tick_conversation_id_format(client):
    setup_full_context(client)

    old_llm = tick_service.llm
    tick_service.llm = FakeLLMProvider(VALID_LLM_RESPONSE)
    try:
        resp = client.post("/v1/tick", json={
            "now": "2026-04-26T10:00:00Z",
            "available_triggers": ["trg_001_research_digest_dentists"],
        })
        action = resp.json()["actions"][0]
        assert "m_001_drmeera_dentist_delhi" in action["conversation_id"]
    finally:
        tick_service.llm = old_llm
