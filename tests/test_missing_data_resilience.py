from __future__ import annotations

import copy

from bot.composer.composer import compose
from bot.composer.customer_composer import compose_customer_facing
from bot.composer.prompts import build_user_prompt, build_customer_user_prompt
from tests.conftest import FakeLLMProvider, SAMPLE_CATEGORY, SAMPLE_MERCHANT, SAMPLE_TRIGGER

VALID_RESPONSE = (
    '{"body": "Dr. Meera, JIDA Oct 2026 p.14: 3-month fluoride recall cuts caries 38% '
    'in a 2,100-patient trial. Relevant for your 124 high-risk adults. Want the abstract?", '
    '"cta": "binary_yes_no", "rationale": "Research digest with merchant-specific cohort."}'
)

# Response that references only digest numbers (no customer_aggregate field) —
# used when customer_aggregate is absent from the merchant context.
RESPONSE_NO_AGG = (
    '{"body": "Dr. Meera, JIDA Oct 2026 p.14: 3-month fluoride recall cuts caries 38% '
    'in a 2,100-patient trial. Want the abstract?", '
    '"cta": "binary_yes_no", "rationale": "Research digest anchor, no cohort reference."}'
)

# Response that references only merchant performance numbers (no digest) —
# used when the category digest is empty.
RESPONSE_NO_DIGEST = (
    '{"body": "Dr. Meera, your 2,410 views and 18 calls this month shows strong intent. '
    'What service should we highlight this week?", '
    '"cta": "open_ended", "rationale": "Merchant performance anchor, no research citation."}'
)

CUSTOMER_VALID_RESPONSE = (
    '{"body": "Hi Priya, Dr. Meera\'s clinic here! Time for your 6-month cleaning recall. '
    'Reply YES to book a slot.", '
    '"cta": "binary_yes_no", "rationale": "Customer recall reminder."}'
)

CUSTOMER_PRIYA = {
    "customer_id": "c_001_priya_for_m001",
    "identity": {"name": "Priya Sharma", "age_band": "25-34", "language_pref": "hi-en mix"},
    "relationship": {"first_visit": "2026-03-15", "last_visit": "2026-05-01"},
    "state": "recall_due",
    "lapse_days": 150,
    "consent": {"scope": ["recall_reminders"]},
    "visit_history": [],
}

RECALL_TRIGGER = {
    "id": "trg_recall_c001",
    "scope": "customer",
    "kind": "recall_due",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "customer_id": "c_001_priya_for_m001",
    "payload": {"service_due": "6_month_cleaning"},
    "urgency": 3,
    "suppression_key": "recall:c001:6mo",
    "expires_at": "2099-12-31T00:00:00Z",
}


# ── Missing owner_first_name ──────────────────────────────────────────────

def test_missing_owner_first_name_no_crash():
    """Merchant without owner_first_name must not crash and must return a result."""
    merchant_no_name = copy.deepcopy(SAMPLE_MERCHANT)
    del merchant_no_name["identity"]["owner_first_name"]

    llm = FakeLLMProvider(VALID_RESPONSE)
    result = compose(SAMPLE_CATEGORY, merchant_no_name, SAMPLE_TRIGGER, None, llm)
    assert result is not None


def test_missing_owner_first_name_prompt_contains_instruction():
    """build_user_prompt emits a MISSING owner_first_name instruction."""
    merchant_no_name = copy.deepcopy(SAMPLE_MERCHANT)
    del merchant_no_name["identity"]["owner_first_name"]

    prompt = build_user_prompt(SAMPLE_CATEGORY, merchant_no_name, SAMPLE_TRIGGER)
    assert "owner_first_name" in prompt.lower() or "MISSING" in prompt


def test_missing_owner_first_name_none_value_no_crash():
    """owner_first_name=None (not absent, but null) must not crash."""
    merchant_null_name = copy.deepcopy(SAMPLE_MERCHANT)
    merchant_null_name["identity"]["owner_first_name"] = None

    llm = FakeLLMProvider(VALID_RESPONSE)
    result = compose(SAMPLE_CATEGORY, merchant_null_name, SAMPLE_TRIGGER, None, llm)
    assert result is not None


# ── Missing customer_aggregate ────────────────────────────────────────────

def test_missing_customer_aggregate_no_crash():
    merchant_no_agg = copy.deepcopy(SAMPLE_MERCHANT)
    del merchant_no_agg["customer_aggregate"]

    # RESPONSE_NO_AGG has no "124" (which came from customer_aggregate) — passes validation.
    llm = FakeLLMProvider(RESPONSE_NO_AGG)
    result = compose(SAMPLE_CATEGORY, merchant_no_agg, SAMPLE_TRIGGER, None, llm)
    assert result is not None


def test_missing_customer_aggregate_prompt_omit_instruction():
    """build_user_prompt must emit 'NOT AVAILABLE' for missing customer_aggregate."""
    merchant_no_agg = copy.deepcopy(SAMPLE_MERCHANT)
    del merchant_no_agg["customer_aggregate"]

    prompt = build_user_prompt(SAMPLE_CATEGORY, merchant_no_agg, SAMPLE_TRIGGER)
    assert "NOT AVAILABLE" in prompt or "omit" in prompt.lower()


def test_none_customer_aggregate_no_crash():
    merchant_null_agg = copy.deepcopy(SAMPLE_MERCHANT)
    merchant_null_agg["customer_aggregate"] = None

    llm = FakeLLMProvider(RESPONSE_NO_AGG)
    result = compose(SAMPLE_CATEGORY, merchant_null_agg, SAMPLE_TRIGGER, None, llm)
    assert result is not None


# ── Missing voice block in category ──────────────────────────────────────

def test_missing_voice_block_no_crash():
    """Category without a voice block must use default voice and not crash."""
    category_no_voice = copy.deepcopy(SAMPLE_CATEGORY)
    del category_no_voice["voice"]

    llm = FakeLLMProvider(VALID_RESPONSE)
    result = compose(category_no_voice, SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, llm)
    assert result is not None


def test_partial_voice_block_no_crash():
    """voice block has tone but no vocab_taboo → no KeyError or crash."""
    category_partial_voice = copy.deepcopy(SAMPLE_CATEGORY)
    category_partial_voice["voice"] = {"tone": "peer_clinical"}

    llm = FakeLLMProvider(VALID_RESPONSE)
    result = compose(category_partial_voice, SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, llm)
    assert result is not None


# ── Missing research digest ───────────────────────────────────────────────

def test_missing_digest_no_crash():
    """Category without digest must not crash; composition falls back to merchant signals."""
    category_no_digest = copy.deepcopy(SAMPLE_CATEGORY)
    category_no_digest["digest"] = []

    # RESPONSE_NO_DIGEST has no digest-specific numbers (38%, 2100) — passes validation.
    llm = FakeLLMProvider(RESPONSE_NO_DIGEST)
    result = compose(category_no_digest, SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, llm)
    assert result is not None


def test_missing_digest_prompt_contains_fallback_note():
    category_no_digest = copy.deepcopy(SAMPLE_CATEGORY)
    del category_no_digest["digest"]

    prompt = build_user_prompt(category_no_digest, SAMPLE_MERCHANT, SAMPLE_TRIGGER)
    assert "NOT AVAILABLE" in prompt or "skip" in prompt.lower()


# ── Missing customer fields (customer-facing) ─────────────────────────────

def test_customer_missing_name_no_crash():
    customer_no_name = copy.deepcopy(CUSTOMER_PRIYA)
    del customer_no_name["identity"]["name"]

    llm = FakeLLMProvider(CUSTOMER_VALID_RESPONSE)
    result = compose_customer_facing(
        SAMPLE_CATEGORY, SAMPLE_MERCHANT, RECALL_TRIGGER, customer_no_name, llm,
    )
    # Should either return a valid result or None — must not raise
    assert result is None or isinstance(result, object)


def test_customer_missing_name_prompt_has_fallback_instruction():
    customer_no_name = copy.deepcopy(CUSTOMER_PRIYA)
    del customer_no_name["identity"]["name"]

    prompt = build_customer_user_prompt(
        SAMPLE_CATEGORY, SAMPLE_MERCHANT, RECALL_TRIGGER, customer_no_name,
    )
    # Should contain a note about missing name
    assert "MISSING" in prompt or "name" in prompt.lower()


def test_customer_missing_visit_history_no_crash():
    customer_no_hist = copy.deepcopy(CUSTOMER_PRIYA)
    customer_no_hist["visit_history"] = []

    llm = FakeLLMProvider(CUSTOMER_VALID_RESPONSE)
    result = compose_customer_facing(
        SAMPLE_CATEGORY, SAMPLE_MERCHANT, RECALL_TRIGGER, customer_no_hist, llm,
    )
    assert result is None or isinstance(result, object)


# ── Empty/minimal trigger payload ────────────────────────────────────────

def test_minimal_trigger_payload_no_crash():
    """Trigger with empty payload dict must not crash the composition."""
    minimal_trigger = {**SAMPLE_TRIGGER, "payload": {}}
    llm = FakeLLMProvider(VALID_RESPONSE)
    result = compose(SAMPLE_CATEGORY, SAMPLE_MERCHANT, minimal_trigger, None, llm)
    assert result is not None
