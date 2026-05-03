from __future__ import annotations

import copy

import pytest

from bot.main import tick_service
from bot.state import store
from tests.conftest import (
    FakeLLMProvider,
    SAMPLE_CATEGORY,
    SAMPLE_MERCHANT,
    SAMPLE_TRIGGER,
    VALID_LLM_RESPONSE,
)


def push_ctx(client, scope, ctx_id, version, payload):
    resp = client.post("/v1/context", json={
        "scope": scope, "context_id": ctx_id,
        "version": version, "payload": payload,
    })
    assert resp.status_code == 200


CUSTOMER_WITH_RECALL_CONSENT = {
    "customer_id": "c_001",
    "identity": {"name": "Priya", "age_band": "25-34", "language_pref": "en"},
    "state": "recall_due",
    "lapse_days": 150,
    "consent": {"scope": ["recall_reminders"]},
    "visit_history": [],
}

CUSTOMER_WITH_RECALL_CONSENT_2 = {
    "customer_id": "c_002",
    "identity": {"name": "Anita", "age_band": "30-40", "language_pref": "en"},
    "state": "recall_due",
    "lapse_days": 180,
    "consent": {"scope": ["recall_reminders"]},
    "visit_history": [],
}

CUSTOMER_VALID_RESPONSE = (
    '{"body": "Hi Priya, Dr. Meera\'s clinic here! Time for your 6-month cleaning. '
    'Reply YES to book.", '
    '"cta": "binary_yes_no", "rationale": "Customer recall."}'
)

CUSTOMER_VALID_RESPONSE_2 = (
    '{"body": "Hi Anita, Dr. Meera\'s clinic here! Time for your 6-month cleaning. '
    'Reply YES to book.", '
    '"cta": "binary_yes_no", "rationale": "Customer recall."}'
)


# ── Expired trigger guard ─────────────────────────────────────────────────

def test_expired_trigger_skipped(client):
    """Trigger with expires_at in the past → no action, no LLM call."""
    expired_trigger = {**SAMPLE_TRIGGER, "expires_at": "2020-01-01T00:00:00Z"}
    push_ctx(client, "category", "dentists", 1, SAMPLE_CATEGORY)
    push_ctx(client, "merchant", "m_001_drmeera_dentist_delhi", 1, SAMPLE_MERCHANT)
    push_ctx(client, "trigger", "trg_expired", 1, expired_trigger)

    call_count = 0
    class CountingLLM(FakeLLMProvider):
        def complete(self, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            return VALID_LLM_RESPONSE

    old_llm = tick_service.llm
    tick_service.llm = CountingLLM()
    try:
        resp = client.post("/v1/tick", json={
            "now": "2026-04-26T10:00:00Z",
            "available_triggers": ["trg_expired"],
        })
        assert resp.json()["actions"] == []
        assert call_count == 0, "LLM should not be called for expired triggers"
    finally:
        tick_service.llm = old_llm


def test_trigger_not_yet_expired_fires(client):
    """Trigger with expires_at in the future → fires normally."""
    future_trigger = {**SAMPLE_TRIGGER, "expires_at": "2099-12-31T00:00:00Z"}
    push_ctx(client, "category", "dentists", 1, SAMPLE_CATEGORY)
    push_ctx(client, "merchant", "m_001_drmeera_dentist_delhi", 1, SAMPLE_MERCHANT)
    push_ctx(client, "trigger", "trg_future", 1, future_trigger)

    old_llm = tick_service.llm
    tick_service.llm = FakeLLMProvider(VALID_LLM_RESPONSE)
    try:
        resp = client.post("/v1/tick", json={
            "now": "2026-04-26T10:00:00Z",
            "available_triggers": ["trg_future"],
        })
        assert len(resp.json()["actions"]) == 1
    finally:
        tick_service.llm = old_llm


def test_trigger_with_no_expires_at_fires(client):
    """Trigger without expires_at field → fires (no expiry constraint)."""
    trigger_no_expiry = {k: v for k, v in SAMPLE_TRIGGER.items() if k != "expires_at"}
    push_ctx(client, "category", "dentists", 1, SAMPLE_CATEGORY)
    push_ctx(client, "merchant", "m_001_drmeera_dentist_delhi", 1, SAMPLE_MERCHANT)
    push_ctx(client, "trigger", "trg_no_expiry", 1, trigger_no_expiry)

    old_llm = tick_service.llm
    tick_service.llm = FakeLLMProvider(VALID_LLM_RESPONSE)
    try:
        resp = client.post("/v1/tick", json={
            "now": "2026-04-26T10:00:00Z",
            "available_triggers": ["trg_no_expiry"],
        })
        assert len(resp.json()["actions"]) == 1
    finally:
        tick_service.llm = old_llm


# ── Per-customer suppression ───────────────────────────────────────────────

def test_suppression_per_customer_both_fire(client):
    """Two triggers for different customers have different suppression keys → both fire."""
    push_ctx(client, "category", "dentists", 1, SAMPLE_CATEGORY)
    push_ctx(client, "merchant", "m_001_drmeera_dentist_delhi", 1, SAMPLE_MERCHANT)

    push_ctx(client, "customer", "c_001", 1, CUSTOMER_WITH_RECALL_CONSENT)
    push_ctx(client, "customer", "c_002", 1, CUSTOMER_WITH_RECALL_CONSENT_2)

    trg_c001 = {
        **SAMPLE_TRIGGER,
        "id": "trg_recall_c001",
        "scope": "customer",
        "kind": "recall_due",
        "customer_id": "c_001",
        "suppression_key": "recall:c_001:6mo",  # per-customer key
    }
    trg_c002 = {
        **SAMPLE_TRIGGER,
        "id": "trg_recall_c002",
        "scope": "customer",
        "kind": "recall_due",
        "customer_id": "c_002",
        "suppression_key": "recall:c_002:6mo",  # different per-customer key
    }
    push_ctx(client, "trigger", "trg_recall_c001", 1, trg_c001)
    push_ctx(client, "trigger", "trg_recall_c002", 1, trg_c002)

    responses = [CUSTOMER_VALID_RESPONSE, CUSTOMER_VALID_RESPONSE_2]
    call_idx = [0]

    class MultiResponseLLM(FakeLLMProvider):
        def complete(self, *args, **kwargs):
            idx = call_idx[0] % len(responses)
            call_idx[0] += 1
            return responses[idx]

    old_llm = tick_service.llm
    tick_service.llm = MultiResponseLLM()
    try:
        resp = client.post("/v1/tick", json={
            "now": "2026-04-26T10:00:00Z",
            "available_triggers": ["trg_recall_c001", "trg_recall_c002"],
        })
        actions = resp.json()["actions"]
        assert len(actions) == 2, (
            f"Both customers should fire (different suppression keys). Got {len(actions)} actions."
        )
        customer_ids = {a["customer_id"] for a in actions}
        assert "c_001" in customer_ids
        assert "c_002" in customer_ids
    finally:
        tick_service.llm = old_llm


def test_same_suppression_key_fires_once(client):
    """Two triggers with the same suppression key → only first fires."""
    push_ctx(client, "category", "dentists", 1, SAMPLE_CATEGORY)
    push_ctx(client, "merchant", "m_001_drmeera_dentist_delhi", 1, SAMPLE_MERCHANT)

    trg_a = {**SAMPLE_TRIGGER, "id": "trg_dup_a", "suppression_key": "shared_key"}
    trg_b = {**SAMPLE_TRIGGER, "id": "trg_dup_b", "suppression_key": "shared_key"}
    push_ctx(client, "trigger", "trg_dup_a", 1, trg_a)
    push_ctx(client, "trigger", "trg_dup_b", 1, trg_b)

    old_llm = tick_service.llm
    tick_service.llm = FakeLLMProvider(VALID_LLM_RESPONSE)
    try:
        resp = client.post("/v1/tick", json={
            "now": "2026-04-26T10:00:00Z",
            "available_triggers": ["trg_dup_a", "trg_dup_b"],
        })
        # First fires, second is suppressed
        assert len(resp.json()["actions"]) == 1
    finally:
        tick_service.llm = old_llm


# ── Unknown merchant in trigger ───────────────────────────────────────────

def test_unknown_merchant_in_trigger_skips_no_crash(client):
    """Trigger references merchant not in store → skip, no crash, no 500."""
    push_ctx(client, "category", "dentists", 1, SAMPLE_CATEGORY)
    trigger_bad_merchant = {**SAMPLE_TRIGGER, "merchant_id": "m_nonexistent_merchant"}
    push_ctx(client, "trigger", "trg_bad_merchant", 1, trigger_bad_merchant)

    old_llm = tick_service.llm
    tick_service.llm = FakeLLMProvider(VALID_LLM_RESPONSE)
    try:
        resp = client.post("/v1/tick", json={
            "now": "2026-04-26T10:00:00Z",
            "available_triggers": ["trg_bad_merchant"],
        })
        assert resp.status_code == 200
        assert resp.json()["actions"] == []
    finally:
        tick_service.llm = old_llm


# ── Malformed / missing trigger fields ────────────────────────────────────

def test_trigger_missing_merchant_id_skips(client):
    push_ctx(client, "category", "dentists", 1, SAMPLE_CATEGORY)
    push_ctx(client, "merchant", "m_001_drmeera_dentist_delhi", 1, SAMPLE_MERCHANT)

    trigger_no_mid = {k: v for k, v in SAMPLE_TRIGGER.items() if k != "merchant_id"}
    push_ctx(client, "trigger", "trg_no_mid", 1, trigger_no_mid)

    resp = client.post("/v1/tick", json={
        "now": "2026-04-26T10:00:00Z",
        "available_triggers": ["trg_no_mid"],
    })
    assert resp.json()["actions"] == []


def test_trigger_empty_payload_no_crash(client):
    """Trigger with empty payload dict must not crash."""
    push_ctx(client, "category", "dentists", 1, SAMPLE_CATEGORY)
    push_ctx(client, "merchant", "m_001_drmeera_dentist_delhi", 1, SAMPLE_MERCHANT)

    trigger_empty = {**SAMPLE_TRIGGER, "id": "trg_empty_payload", "payload": {},
                     "suppression_key": "empty_payload_key"}
    push_ctx(client, "trigger", "trg_empty_payload", 1, trigger_empty)

    old_llm = tick_service.llm
    tick_service.llm = FakeLLMProvider(VALID_LLM_RESPONSE)
    try:
        resp = client.post("/v1/tick", json={
            "now": "2026-04-26T10:00:00Z",
            "available_triggers": ["trg_empty_payload"],
        })
        assert resp.status_code == 200
        # May return 0 or 1 actions; must not crash
    finally:
        tick_service.llm = old_llm


def test_tick_handles_empty_available_triggers(client):
    resp = client.post("/v1/tick", json={"now": "2026-04-26T10:00:00Z", "available_triggers": []})
    assert resp.status_code == 200
    assert resp.json()["actions"] == []


def test_tick_unknown_trigger_id_no_crash(client):
    """Trigger ID in available_triggers list but not pushed → skip silently."""
    resp = client.post("/v1/tick", json={
        "now": "2026-04-26T10:00:00Z",
        "available_triggers": ["trg_never_pushed_xxx"],
    })
    assert resp.status_code == 200
    assert resp.json()["actions"] == []


# ── Customer scope missing customer_id ───────────────────────────────────

def test_customer_scope_trigger_without_customer_id_skips(client):
    """scope=customer but no customer_id in trigger → skip, no crash."""
    push_ctx(client, "category", "dentists", 1, SAMPLE_CATEGORY)
    push_ctx(client, "merchant", "m_001_drmeera_dentist_delhi", 1, SAMPLE_MERCHANT)

    trigger_no_cid = {
        **SAMPLE_TRIGGER,
        "id": "trg_no_cid",
        "scope": "customer",
        "customer_id": None,
        "suppression_key": "no_cid_key",
    }
    push_ctx(client, "trigger", "trg_no_cid", 1, trigger_no_cid)

    resp = client.post("/v1/tick", json={
        "now": "2026-04-26T10:00:00Z",
        "available_triggers": ["trg_no_cid"],
    })
    assert resp.status_code == 200
    assert resp.json()["actions"] == []
