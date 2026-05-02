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


def push(client, scope, ctx_id, version, payload):
    resp = client.post("/v1/context", json={
        "scope": scope,
        "context_id": ctx_id,
        "version": version,
        "payload": payload,
    })
    assert resp.status_code == 200, resp.text


def setup_full(client):
    push(client, "category", "dentists", 1, SAMPLE_CATEGORY)
    push(client, "merchant", "m_001_drmeera_dentist_delhi", 1, SAMPLE_MERCHANT)
    push(client, "trigger", "trg_001_research_digest_dentists", 1, SAMPLE_TRIGGER)


# ── Suppression across ticks ──────────────────────────────────────────────

def test_tick_suppresses_repeated_trigger(client):
    """Firing the same trigger twice → second tick returns no actions."""
    setup_full(client)
    old_llm = tick_service.llm
    tick_service.llm = FakeLLMProvider(VALID_LLM_RESPONSE)
    try:
        r1 = client.post("/v1/tick", json={
            "now": "2026-04-26T10:00:00Z",
            "available_triggers": ["trg_001_research_digest_dentists"],
        })
        assert len(r1.json()["actions"]) == 1

        r2 = client.post("/v1/tick", json={
            "now": "2026-04-26T11:00:00Z",
            "available_triggers": ["trg_001_research_digest_dentists"],
        })
        assert r2.json()["actions"] == [], "Second tick on same trigger must be suppressed"
    finally:
        tick_service.llm = old_llm


def test_tick_skips_expired_trigger(client):
    """Trigger with expires_at in the past must be skipped without LLM call."""
    expired = {**SAMPLE_TRIGGER, "expires_at": "2020-01-01T00:00:00Z"}
    push(client, "category", "dentists", 1, SAMPLE_CATEGORY)
    push(client, "merchant", "m_001_drmeera_dentist_delhi", 1, SAMPLE_MERCHANT)
    push(client, "trigger", "trg_001_research_digest_dentists", 1, expired)

    fake_llm = FakeLLMProvider(VALID_LLM_RESPONSE)
    old_llm = tick_service.llm
    tick_service.llm = fake_llm
    try:
        resp = client.post("/v1/tick", json={
            "now": "2026-04-26T10:00:00Z",
            "available_triggers": ["trg_001_research_digest_dentists"],
        })
        assert resp.json()["actions"] == []
        assert fake_llm.calls == [], "LLM must not be called for expired trigger"
    finally:
        tick_service.llm = old_llm


# ── Voice pack injected into system prompt ────────────────────────────────

def test_tick_system_prompt_contains_voice_instructions(client):
    """The system prompt sent to LLM must include dentist voice instructions."""
    setup_full(client)
    fake_llm = FakeLLMProvider(VALID_LLM_RESPONSE)
    old_llm = tick_service.llm
    tick_service.llm = fake_llm
    try:
        resp = client.post("/v1/tick", json={
            "now": "2026-04-26T10:00:00Z",
            "available_triggers": ["trg_001_research_digest_dentists"],
        })
        assert len(resp.json()["actions"]) == 1
        system_prompt = fake_llm.calls[0]["system"]
        assert "clinical" in system_prompt.lower(), (
            "Dentist voice instructions must appear in system prompt"
        )
    finally:
        tick_service.llm = old_llm


def test_tick_system_prompt_contains_trigger_framing(client):
    """The system prompt must include framing guidance for research_digest."""
    setup_full(client)
    fake_llm = FakeLLMProvider(VALID_LLM_RESPONSE)
    old_llm = tick_service.llm
    tick_service.llm = fake_llm
    try:
        resp = client.post("/v1/tick", json={
            "now": "2026-04-26T10:00:00Z",
            "available_triggers": ["trg_001_research_digest_dentists"],
        })
        assert len(resp.json()["actions"]) == 1
        system_prompt = fake_llm.calls[0]["system"]
        assert "cite" in system_prompt.lower() or "source" in system_prompt.lower(), (
            "research_digest framing (cite source) must appear in system prompt"
        )
    finally:
        tick_service.llm = old_llm


# ── Compose retry on validation failure ──────────────────────────────────

def test_compose_retry_on_url_failure_via_tick(client):
    """First LLM response has URL → validation fails → retries → second response succeeds."""
    setup_full(client)

    responses = [
        '{"body": "Check https://bad.example.com for details", "cta": "open_ended", "rationale": "r"}',
        VALID_LLM_RESPONSE,
    ]
    call_index = 0

    class RetryLLM(FakeLLMProvider):
        def complete(self, system, user, **kwargs):
            nonlocal call_index
            resp = responses[min(call_index, len(responses) - 1)]
            call_index += 1
            self.calls.append({"system": system, "user": user})
            return resp

    old_llm = tick_service.llm
    tick_service.llm = RetryLLM()
    try:
        resp = client.post("/v1/tick", json={
            "now": "2026-04-26T10:00:00Z",
            "available_triggers": ["trg_001_research_digest_dentists"],
        })
        actions = resp.json()["actions"]
        assert len(actions) == 1, "Should succeed on retry"
        assert call_index == 2, "Should have called LLM exactly twice"
    finally:
        tick_service.llm = old_llm


# ── Prior bot bodies stored and passed ───────────────────────────────────

def test_tick_stores_vera_turn_in_conversation(client):
    """After a successful tick, Vera's message is stored in the conversation."""
    setup_full(client)
    old_llm = tick_service.llm
    tick_service.llm = FakeLLMProvider(VALID_LLM_RESPONSE)
    try:
        resp = client.post("/v1/tick", json={
            "now": "2026-04-26T10:00:00Z",
            "available_triggers": ["trg_001_research_digest_dentists"],
        })
        action = resp.json()["actions"][0]
        conv_id = action["conversation_id"]
        turns = store.conversations.get(conv_id, [])
        assert len(turns) == 1
        assert turns[0].from_role == "vera"
        assert turns[0].body == action["body"]
    finally:
        tick_service.llm = old_llm


# ── Different trigger kinds route to different framings ───────────────────

def test_perf_dip_trigger_kind_routes_correctly(client):
    """A perf_dip trigger must result in a system prompt containing diagnosis guidance."""
    perf_dip_trigger = {
        "id": "trg_perf_dip_test",
        "scope": "merchant",
        "kind": "perf_dip",
        "source": "internal",
        "merchant_id": "m_001_drmeera_dentist_delhi",
        "customer_id": None,
        "payload": {"metric": "calls", "delta_pct": -0.50, "window": "7d"},
        "urgency": 4,
        "suppression_key": "perf_dip:test:unique",
        "expires_at": "2099-12-31T00:00:00Z",
    }
    push(client, "category", "dentists", 1, SAMPLE_CATEGORY)
    push(client, "merchant", "m_001_drmeera_dentist_delhi", 1, SAMPLE_MERCHANT)
    push(client, "trigger", "trg_perf_dip_test", 1, perf_dip_trigger)

    fake_llm = FakeLLMProvider(VALID_LLM_RESPONSE)
    old_llm = tick_service.llm
    tick_service.llm = fake_llm
    try:
        resp = client.post("/v1/tick", json={
            "now": "2026-04-26T10:00:00Z",
            "available_triggers": ["trg_perf_dip_test"],
        })
        assert len(resp.json()["actions"]) == 1
        system_prompt = fake_llm.calls[0]["system"]
        # perf_dip framing contains "diagnose" or "reframe"
        assert "diagnose" in system_prompt.lower() or "reframe" in system_prompt.lower(), (
            "perf_dip framing must appear in system prompt"
        )
    finally:
        tick_service.llm = old_llm
