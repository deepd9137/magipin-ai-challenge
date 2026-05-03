from __future__ import annotations

import pytest

from bot.consent import has_consent, TRIGGER_KIND_TO_CONSENT_SCOPE
from bot.main import tick_service
from tests.conftest import FakeLLMProvider, SAMPLE_CATEGORY, SAMPLE_MERCHANT, VALID_LLM_RESPONSE


# ── Fixtures ──────────────────────────────────────────────────────────────

CUSTOMER_FULL_CONSENT = {
    "customer_id": "c_001_priya_for_m001",
    "identity": {
        "name": "Priya Sharma",
        "age_band": "25-34",
        "language_pref": "hi-en mix",
    },
    "relationship": {
        "first_visit": "2026-03-15",
        "last_visit": "2026-05-01",
        "services_received": ["dental_cleaning"],
    },
    "state": "recall_due",
    "lapse_days": 150,
    "consent": {
        "scope": ["recall_reminders", "appointment_reminders"],
        "opted_in_at": "2026-03-15",
    },
    "visit_history": [{"date": "2026-03-15", "service": "dental_cleaning"}],
}

CUSTOMER_WRONG_CONSENT = {
    **CUSTOMER_FULL_CONSENT,
    "consent": {
        "scope": ["appointment_reminders"],   # recall_reminders NOT present
        "opted_in_at": "2026-03-15",
    },
}

CUSTOMER_NO_CONSENT = {
    **CUSTOMER_FULL_CONSENT,
    "consent": {"scope": [], "opted_in_at": "2026-03-15"},
}

RECALL_TRIGGER = {
    "id": "trg_recall_c001_m001",
    "scope": "customer",
    "kind": "recall_due",
    "source": "platform",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "customer_id": "c_001_priya_for_m001",
    "payload": {
        "service_due": "6_month_cleaning",
        "available_slots": [
            {"label": "Wed 5 Nov, 6pm", "slot_id": "s001"},
        ],
    },
    "urgency": 3,
    "suppression_key": "recall:c_001_priya_for_m001:6mo",
    "expires_at": "2099-12-31T00:00:00Z",
}


def push_ctx(client, scope, ctx_id, version, payload):
    resp = client.post("/v1/context", json={
        "scope": scope, "context_id": ctx_id,
        "version": version, "payload": payload,
    })
    assert resp.status_code == 200


# ── has_consent unit tests ─────────────────────────────────────────────────

def test_has_consent_recall_present():
    assert has_consent(CUSTOMER_FULL_CONSENT, "recall_due") is True


def test_has_consent_recall_missing():
    assert has_consent(CUSTOMER_WRONG_CONSENT, "recall_due") is False


def test_has_consent_empty_scope():
    assert has_consent(CUSTOMER_NO_CONSENT, "recall_due") is False


def test_has_consent_none_customer_always_true():
    """Merchant-facing triggers: customer=None → always allowed."""
    assert has_consent(None, "recall_due") is True
    assert has_consent(None, "research_digest") is True


def test_has_consent_appointment_reminder():
    assert has_consent(CUSTOMER_FULL_CONSENT, "appointment_reminder") is True


def test_has_consent_appointment_reminder_missing():
    no_appt = {**CUSTOMER_FULL_CONSENT, "consent": {"scope": ["recall_reminders"]}}
    assert has_consent(no_appt, "appointment_reminder") is False


def test_has_consent_chronic_refill():
    med_consent = {
        **CUSTOMER_FULL_CONSENT,
        "consent": {"scope": ["medication_reminders"]},
    }
    assert has_consent(med_consent, "chronic_refill_due") is True


def test_has_consent_unknown_trigger_kind_requires_any_scope():
    """Unknown trigger kind → allowed only if customer has any consent at all."""
    assert has_consent(CUSTOMER_FULL_CONSENT, "unknown_kind") is True
    assert has_consent(CUSTOMER_NO_CONSENT, "unknown_kind") is False


def test_consent_mapping_completeness():
    """Verify all expected trigger kinds are mapped."""
    expected = {
        "recall_due", "appointment_tomorrow", "appointment_reminder",
        "chronic_refill_due", "wedding_package_followup", "bridal_followup",
        "customer_lapsed_soft", "customer_lapsed_hard", "promotional_campaign",
    }
    assert expected.issubset(set(TRIGGER_KIND_TO_CONSENT_SCOPE.keys()))


# ── Tick integration: consent gate blocks action ──────────────────────────

def test_consent_missing_skips_recall_action(client):
    """customer.consent.scope = [appointment_reminders], recall_due → no action."""
    push_ctx(client, "category", "dentists", 1, SAMPLE_CATEGORY)
    push_ctx(client, "merchant", "m_001_drmeera_dentist_delhi", 1, SAMPLE_MERCHANT)
    push_ctx(client, "customer", "c_001_priya_for_m001", 1, CUSTOMER_WRONG_CONSENT)
    push_ctx(client, "trigger", "trg_recall_c001_m001", 1, RECALL_TRIGGER)

    old_llm = tick_service.llm
    tick_service.llm = FakeLLMProvider(VALID_LLM_RESPONSE)
    try:
        resp = client.post("/v1/tick", json={
            "now": "2026-04-26T10:00:00Z",
            "available_triggers": ["trg_recall_c001_m001"],
        })
        assert resp.status_code == 200
        assert resp.json()["actions"] == []
    finally:
        tick_service.llm = old_llm


def test_consent_present_allows_recall_action(client):
    """customer.consent.scope includes recall_reminders → action returned."""
    push_ctx(client, "category", "dentists", 1, SAMPLE_CATEGORY)
    push_ctx(client, "merchant", "m_001_drmeera_dentist_delhi", 1, SAMPLE_MERCHANT)
    push_ctx(client, "customer", "c_001_priya_for_m001", 1, CUSTOMER_FULL_CONSENT)
    push_ctx(client, "trigger", "trg_recall_c001_m001", 1, RECALL_TRIGGER)

    customer_response = (
        '{"body": "Hi Priya, Dr. Meera\'s clinic here! Time for your 6-month cleaning. '
        'Reply YES to book a slot.", '
        '"cta": "binary_yes_no", "rationale": "Customer recall reminder."}'
    )
    old_llm = tick_service.llm
    tick_service.llm = FakeLLMProvider(customer_response)
    try:
        resp = client.post("/v1/tick", json={
            "now": "2026-04-26T10:00:00Z",
            "available_triggers": ["trg_recall_c001_m001"],
        })
        assert resp.status_code == 200
        actions = resp.json()["actions"]
        assert len(actions) == 1
        assert actions[0]["send_as"] == "merchant_on_behalf"
        assert actions[0]["customer_id"] == "c_001_priya_for_m001"
    finally:
        tick_service.llm = old_llm


def test_consent_no_customer_merchant_trigger_not_blocked(client):
    """Merchant-facing trigger has no customer → consent gate never applies."""
    from tests.conftest import SAMPLE_TRIGGER
    push_ctx(client, "category", "dentists", 1, SAMPLE_CATEGORY)
    push_ctx(client, "merchant", "m_001_drmeera_dentist_delhi", 1, SAMPLE_MERCHANT)
    push_ctx(client, "trigger", "trg_001_research_digest_dentists", 1, SAMPLE_TRIGGER)

    old_llm = tick_service.llm
    tick_service.llm = FakeLLMProvider(VALID_LLM_RESPONSE)
    try:
        resp = client.post("/v1/tick", json={
            "now": "2026-04-26T10:00:00Z",
            "available_triggers": ["trg_001_research_digest_dentists"],
        })
        assert resp.status_code == 200
        assert len(resp.json()["actions"]) == 1
        assert resp.json()["actions"][0]["send_as"] == "vera"
    finally:
        tick_service.llm = old_llm


def test_customer_not_found_skips_trigger(client):
    """Trigger references customer not in store → skip, no crash."""
    push_ctx(client, "category", "dentists", 1, SAMPLE_CATEGORY)
    push_ctx(client, "merchant", "m_001_drmeera_dentist_delhi", 1, SAMPLE_MERCHANT)
    push_ctx(client, "trigger", "trg_recall_c001_m001", 1, RECALL_TRIGGER)
    # customer NOT pushed

    old_llm = tick_service.llm
    tick_service.llm = FakeLLMProvider(VALID_LLM_RESPONSE)
    try:
        resp = client.post("/v1/tick", json={
            "now": "2026-04-26T10:00:00Z",
            "available_triggers": ["trg_recall_c001_m001"],
        })
        assert resp.json()["actions"] == []
    finally:
        tick_service.llm = old_llm
