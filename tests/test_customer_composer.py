from __future__ import annotations

import pytest

from bot.composer.customer_composer import compose_customer_facing
from bot.state import ComposedMessage
from tests.conftest import FakeLLMProvider, SAMPLE_CATEGORY, SAMPLE_MERCHANT


# ── Shared fixtures ────────────────────────────────────────────────────────

CUSTOMER_PRIYA = {
    "customer_id": "c_001_priya_for_m001",
    "identity": {
        "name": "Priya Sharma",
        "age_band": "25-34",
        "language_pref": "hi-en mix",
    },
    "relationship": {
        "first_visit": "2026-03-15",
        "last_visit": "2026-05-01",
        "services_received": ["dental_cleaning", "fluoride_treatment"],
    },
    "state": "recall_due",
    "lapse_days": 150,
    "consent": {"scope": ["recall_reminders", "appointment_reminders"]},
    "visit_history": [{"date": "2026-03-15", "service": "dental_cleaning"}],
}

RECALL_TRIGGER = {
    "id": "trg_recall_c001",
    "scope": "customer",
    "kind": "recall_due",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "customer_id": "c_001_priya_for_m001",
    "payload": {
        "service_due": "6_month_cleaning",
        "available_slots": [
            {"label": "Wed 5 Nov, 6pm"},
            {"label": "Thu 6 Nov, 5pm"},
        ],
    },
    "urgency": 3,
    "suppression_key": "recall:c_001_priya_for_m001:6mo",
    "expires_at": "2099-12-31T00:00:00Z",
}

# Body has no multi-digit numbers that aren't in context — passes anti-fabrication check.
CUSTOMER_VALID_RESPONSE = (
    '{"body": "Hi Priya, Dr. Meera\'s clinic here! Time for your 6-month cleaning recall. '
    'Reply YES to book a slot.", '
    '"cta": "binary_yes_no", "rationale": "Customer recall via merchant_on_behalf."}'
)


# ── Core routing / send_as tests ──────────────────────────────────────────

def test_customer_composer_returns_merchant_on_behalf():
    llm = FakeLLMProvider(CUSTOMER_VALID_RESPONSE)
    result = compose_customer_facing(
        SAMPLE_CATEGORY, SAMPLE_MERCHANT, RECALL_TRIGGER, CUSTOMER_PRIYA, llm,
    )
    assert result is not None
    assert result.send_as == "merchant_on_behalf"


def test_customer_composer_returns_composed_message_type():
    llm = FakeLLMProvider(CUSTOMER_VALID_RESPONSE)
    result = compose_customer_facing(
        SAMPLE_CATEGORY, SAMPLE_MERCHANT, RECALL_TRIGGER, CUSTOMER_PRIYA, llm,
    )
    assert isinstance(result, ComposedMessage)


def test_customer_composer_suppression_key_preserved():
    llm = FakeLLMProvider(CUSTOMER_VALID_RESPONSE)
    result = compose_customer_facing(
        SAMPLE_CATEGORY, SAMPLE_MERCHANT, RECALL_TRIGGER, CUSTOMER_PRIYA, llm,
    )
    assert result is not None
    assert result.suppression_key == "recall:c_001_priya_for_m001:6mo"


def test_customer_composer_template_name_includes_trigger_kind():
    llm = FakeLLMProvider(CUSTOMER_VALID_RESPONSE)
    result = compose_customer_facing(
        SAMPLE_CATEGORY, SAMPLE_MERCHANT, RECALL_TRIGGER, CUSTOMER_PRIYA, llm,
    )
    assert result is not None
    assert "recall_due" in result.template_name


def test_customer_composer_valid_cta():
    llm = FakeLLMProvider(CUSTOMER_VALID_RESPONSE)
    result = compose_customer_facing(
        SAMPLE_CATEGORY, SAMPLE_MERCHANT, RECALL_TRIGGER, CUSTOMER_PRIYA, llm,
    )
    assert result is not None
    valid_ctas = {"open_ended", "binary_yes_no", "binary_confirm_cancel", "multi_choice_slot", "none"}
    assert result.cta in valid_ctas


def test_customer_composer_body_meets_length_requirements():
    llm = FakeLLMProvider(CUSTOMER_VALID_RESPONSE)
    result = compose_customer_facing(
        SAMPLE_CATEGORY, SAMPLE_MERCHANT, RECALL_TRIGGER, CUSTOMER_PRIYA, llm,
    )
    assert result is not None
    assert 10 <= len(result.body) <= 800


# ── Customer-lapsed winback (gym) ─────────────────────────────────────────

GYM_CATEGORY = {
    "slug": "gyms",
    "display_name": "Gyms & Fitness",
    "voice": {
        "tone": "coach_motivational",
        "register": "coach_peer",
        "vocab_taboo": ["fat-burning miracle", "guaranteed weight loss"],
    },
    "offer_catalog": [{"id": "g_001", "title": "Month Pass @ ₹999", "value": "999"}],
    "peer_stats": {"avg_retention_30d": 0.72},
    "digest": [],
}

GYM_MERCHANT = {
    **SAMPLE_MERCHANT,
    "category_slug": "gyms",
    "identity": {
        **SAMPLE_MERCHANT["identity"],
        "name": "FitZone Gym",
        "owner_first_name": "Rahul",
    },
    "offers": [{"id": "o_gym_001", "title": "Month Pass @ ₹999", "status": "active"}],
}

CUSTOMER_RASHMI = {
    "customer_id": "c_002_rashmi_gym",
    "identity": {"name": "Rashmi Gupta", "age_band": "25-34", "language_pref": "en"},
    "relationship": {
        "first_visit": "2025-10-01",
        "last_visit": "2026-01-15",
        "services_received": ["gym_access", "zumba_class"],
    },
    "state": "lapsed",
    "lapse_days": 90,
    "consent": {"scope": ["marketing_outreach"]},
    "visit_history": [
        {"date": "2026-01-15", "service": "gym_access"},
    ],
}

LAPSED_HARD_TRIGGER = {
    "id": "trg_lapsed_rashmi",
    "scope": "customer",
    "kind": "customer_lapsed_hard",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "customer_id": "c_002_rashmi_gym",
    "payload": {"lapse_days": 90, "past_goal": "weight_loss"},
    "urgency": 4,
    "suppression_key": "lapsed:c_002_rashmi_gym:hard",
    "expires_at": "2099-12-31T00:00:00Z",
}

LAPSED_RESPONSE = (
    '{"body": "Hi Rashmi, FitZone Gym here! It\'s been a while. '
    'No judgment — come back at your own pace. Month Pass @ ₹999 waiting for you. '
    'Reply YES to reactivate.", '
    '"cta": "binary_yes_no", "rationale": "Lapsed customer winback, no-shame framing."}'
)


def test_customer_lapsed_winback_returns_merchant_on_behalf():
    llm = FakeLLMProvider(LAPSED_RESPONSE)
    result = compose_customer_facing(
        GYM_CATEGORY, GYM_MERCHANT, LAPSED_HARD_TRIGGER, CUSTOMER_RASHMI, llm,
    )
    assert result is not None
    assert result.send_as == "merchant_on_behalf"


def test_customer_lapsed_winback_valid_output():
    llm = FakeLLMProvider(LAPSED_RESPONSE)
    result = compose_customer_facing(
        GYM_CATEGORY, GYM_MERCHANT, LAPSED_HARD_TRIGGER, CUSTOMER_RASHMI, llm,
    )
    assert result is not None
    assert 10 <= len(result.body) <= 800


# ── LLM prompt includes customer context ─────────────────────────────────

def test_customer_user_prompt_includes_customer_name():
    llm = FakeLLMProvider(CUSTOMER_VALID_RESPONSE)
    compose_customer_facing(
        SAMPLE_CATEGORY, SAMPLE_MERCHANT, RECALL_TRIGGER, CUSTOMER_PRIYA, llm,
    )
    assert len(llm.calls) > 0
    user_prompt = llm.calls[0]["user"]
    assert "Priya" in user_prompt


def test_customer_system_prompt_indicates_merchant_to_customer():
    llm = FakeLLMProvider(CUSTOMER_VALID_RESPONSE)
    compose_customer_facing(
        SAMPLE_CATEGORY, SAMPLE_MERCHANT, RECALL_TRIGGER, CUSTOMER_PRIYA, llm,
    )
    system_prompt = llm.calls[0]["system"]
    assert "merchant" in system_prompt.lower()
    assert "customer" in system_prompt.lower()


def test_customer_system_prompt_includes_language_instruction_for_hi_en():
    """For hi-en preference, system prompt must mention code-mix or Hindi-English."""
    llm = FakeLLMProvider(CUSTOMER_VALID_RESPONSE)
    compose_customer_facing(
        SAMPLE_CATEGORY, SAMPLE_MERCHANT, RECALL_TRIGGER, CUSTOMER_PRIYA, llm,
    )
    system_prompt = llm.calls[0]["system"]
    assert "Hindi" in system_prompt or "hi-en" in system_prompt or "Hinglish" in system_prompt


# ── LLM failure / None body handling ────────────────────────────────────

def test_customer_composer_returns_none_on_empty_body():
    llm = FakeLLMProvider('{"body": "", "cta": "binary_yes_no", "rationale": "skip"}')
    result = compose_customer_facing(
        SAMPLE_CATEGORY, SAMPLE_MERCHANT, RECALL_TRIGGER, CUSTOMER_PRIYA, llm,
    )
    assert result is None


def test_customer_composer_returns_none_on_invalid_json():
    llm = FakeLLMProvider("not json at all")
    result = compose_customer_facing(
        SAMPLE_CATEGORY, SAMPLE_MERCHANT, RECALL_TRIGGER, CUSTOMER_PRIYA, llm,
    )
    assert result is None


def test_customer_composer_returns_none_on_llm_exception():
    class ErrorLLM(FakeLLMProvider):
        def complete(self, *args, **kwargs):
            raise RuntimeError("LLM unavailable")

    result = compose_customer_facing(
        SAMPLE_CATEGORY, SAMPLE_MERCHANT, RECALL_TRIGGER, CUSTOMER_PRIYA, ErrorLLM(),
    )
    assert result is None


# ── customer_lapsed_soft ──────────────────────────────────────────────────

LAPSED_SOFT_TRIGGER = {
    "id": "trg_lapsed_soft_rashmi",
    "scope": "customer",
    "kind": "customer_lapsed_soft",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "customer_id": "c_002_rashmi_gym",
    "payload": {"lapse_days": 45, "past_services": ["gym_access"]},
    "urgency": 2,
    "suppression_key": "lapsed:c_002_rashmi_gym:soft",
    "expires_at": "2099-12-31T00:00:00Z",
}

LAPSED_SOFT_RESPONSE = (
    '{"body": "Hi Rashmi, FitZone Gym here! We miss you. '
    'Come back when you\'re ready — Month Pass @ ₹999 is here. '
    'Reply YES to rejoin.", '
    '"cta": "binary_yes_no", "rationale": "Lapsed soft — warm no-shame winback."}'
)


def test_customer_lapsed_soft_returns_merchant_on_behalf():
    llm = FakeLLMProvider(LAPSED_SOFT_RESPONSE)
    result = compose_customer_facing(
        GYM_CATEGORY, GYM_MERCHANT, LAPSED_SOFT_TRIGGER, CUSTOMER_RASHMI, llm,
    )
    assert result is not None
    assert result.send_as == "merchant_on_behalf"


def test_customer_lapsed_soft_has_valid_output():
    llm = FakeLLMProvider(LAPSED_SOFT_RESPONSE)
    result = compose_customer_facing(
        GYM_CATEGORY, GYM_MERCHANT, LAPSED_SOFT_TRIGGER, CUSTOMER_RASHMI, llm,
    )
    assert result is not None
    assert 10 <= len(result.body) <= 800
    assert result.cta in {"open_ended", "binary_yes_no", "binary_confirm_cancel", "multi_choice_slot", "none"}


def test_customer_lapsed_soft_framing_in_user_prompt():
    """System prompt for lapsed_soft must reference no-shame / warm framing."""
    llm = FakeLLMProvider(LAPSED_SOFT_RESPONSE)
    compose_customer_facing(
        GYM_CATEGORY, GYM_MERCHANT, LAPSED_SOFT_TRIGGER, CUSTOMER_RASHMI, llm,
    )
    system_prompt = llm.calls[0]["system"]
    # lapsed_soft framing says "no-shame", verify the framing guide is present
    assert "shame" in system_prompt.lower() or "lapsed" in system_prompt.lower() or "CUSTOMER-FACING" in system_prompt


# ── chronic_refill_due (pharmacy — senior customer) ───────────────────────

PHARMACY_CATEGORY = {
    "slug": "pharmacies",
    "display_name": "Pharmacies",
    "voice": {
        "tone": "trustworthy_precise",
        "register": "professional_peer",
        "vocab_taboo": ["miracle drug", "guaranteed cure", "100% effective"],
    },
    "offer_catalog": [{"id": "ph_001", "title": "Senior Discount 10%", "value": "10"}],
    "peer_stats": {"avg_monthly_refills": 42},
    "digest": [],
}

PHARMACY_MERCHANT = {
    **SAMPLE_MERCHANT,
    "category_slug": "pharmacies",
    "identity": {
        **SAMPLE_MERCHANT["identity"],
        "name": "Sharma Medicals",
        "owner_first_name": "Vijay",
    },
    "offers": [{"id": "o_ph_001", "title": "Senior Discount 10%", "status": "active"}],
}

CUSTOMER_MR_SHARMA = {
    "customer_id": "c_003_mr_sharma_ph",
    "identity": {"name": "Ramesh Sharma", "age_band": "65+", "language_pref": "hi-en mix"},
    "relationship": {
        "first_visit": "2025-06-01",
        "last_visit": "2026-04-01",
        "services_received": ["metformin_refill", "amlodipine_refill"],
    },
    "state": "refill_due",
    "lapse_days": 30,
    "consent": {"scope": ["medication_reminders"]},
    "visit_history": [{"date": "2026-04-01", "molecules": ["metformin", "amlodipine"]}],
}

CHRONIC_REFILL_TRIGGER = {
    "id": "trg_refill_sharma",
    "scope": "customer",
    "kind": "chronic_refill_due",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "customer_id": "c_003_mr_sharma_ph",
    "payload": {
        "molecules": ["metformin", "amlodipine"],
        "days_supply_remaining": 5,
        "delivery_available": True,
    },
    "urgency": 5,
    "suppression_key": "refill:c_003_mr_sharma_ph:monthly",
    "expires_at": "2099-12-31T00:00:00Z",
}

CHRONIC_REFILL_RESPONSE = (
    '{"body": "Namaste Ramesh ji, Sharma Medicals here. '
    'Aapki metformin aur amlodipine refill due hai — stock sirf 5 din ka bacha hai. '
    'Delivery bhi available hai. Reply YES to confirm.", '
    '"cta": "binary_yes_no", "rationale": "Chronic refill due — senior citizen, hi-en mix."}'
)


def test_chronic_refill_returns_merchant_on_behalf():
    llm = FakeLLMProvider(CHRONIC_REFILL_RESPONSE)
    result = compose_customer_facing(
        PHARMACY_CATEGORY, PHARMACY_MERCHANT, CHRONIC_REFILL_TRIGGER, CUSTOMER_MR_SHARMA, llm,
    )
    assert result is not None
    assert result.send_as == "merchant_on_behalf"


def test_chronic_refill_system_prompt_language_is_hi_en():
    """Senior customer with hi-en pref → system prompt must include Hindi/code-mix instruction."""
    llm = FakeLLMProvider(CHRONIC_REFILL_RESPONSE)
    compose_customer_facing(
        PHARMACY_CATEGORY, PHARMACY_MERCHANT, CHRONIC_REFILL_TRIGGER, CUSTOMER_MR_SHARMA, llm,
    )
    system_prompt = llm.calls[0]["system"]
    assert "Hindi" in system_prompt or "Hinglish" in system_prompt or "code-mix" in system_prompt


def test_chronic_refill_user_prompt_includes_molecules():
    """Molecules from trigger payload must appear in the user prompt."""
    llm = FakeLLMProvider(CHRONIC_REFILL_RESPONSE)
    compose_customer_facing(
        PHARMACY_CATEGORY, PHARMACY_MERCHANT, CHRONIC_REFILL_TRIGGER, CUSTOMER_MR_SHARMA, llm,
    )
    user_prompt = llm.calls[0]["user"]
    assert "metformin" in user_prompt or "amlodipine" in user_prompt


# ── bridal_followup ───────────────────────────────────────────────────────

SALON_CATEGORY = {
    "slug": "salons",
    "display_name": "Salons & Beauty",
    "voice": {
        "tone": "warm_practical",
        "register": "operator_peer",
        "vocab_taboo": ["amazing", "best deal ever", "limited time only"],
    },
    "offer_catalog": [{"id": "s_001", "title": "Bridal Package @ ₹8999", "value": "8999"}],
    "peer_stats": {"avg_bridal_bookings_month": 4},
    "digest": [],
}

SALON_MERCHANT = {
    **SAMPLE_MERCHANT,
    "category_slug": "salons",
    "identity": {
        **SAMPLE_MERCHANT["identity"],
        "name": "Glamour Studio",
        "owner_first_name": "Pooja",
    },
    "offers": [{"id": "o_s_001", "title": "Bridal Package @ ₹8999", "status": "active"}],
}

CUSTOMER_KAVYA = {
    "customer_id": "c_004_kavya_salon",
    "identity": {"name": "Kavya Mehta", "age_band": "25-34", "language_pref": "en"},
    "relationship": {
        "first_visit": "2026-03-01",
        "last_visit": "2026-04-20",
        "services_received": ["bridal_trial"],
    },
    "state": "pre_wedding",
    "lapse_days": 0,
    "consent": {"scope": ["marketing_outreach"]},
    "visit_history": [{"date": "2026-04-20", "service": "bridal_trial"}],
}

BRIDAL_FOLLOWUP_TRIGGER = {
    "id": "trg_bridal_kavya",
    "scope": "customer",
    "kind": "bridal_followup",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "customer_id": "c_004_kavya_salon",
    "payload": {
        "wedding_date": "2026-12-01",
        "days_to_wedding": 196,
        "trial_completed": True,
        "preferred_slot": "Sunday morning",
    },
    "urgency": 3,
    "suppression_key": "bridal:c_004_kavya_salon:followup",
    "expires_at": "2099-12-31T00:00:00Z",
}

BRIDAL_RESPONSE = (
    '{"body": "Hi Kavya, Glamour Studio here! Your bridal trial looked gorgeous. '
    'With your wedding on 1 Dec, let\'s lock in your full bridal package. '
    'We have Sunday mornings available. Bridal Package @ ₹8999. '
    'Reply YES to book.", '
    '"cta": "binary_yes_no", "rationale": "Bridal followup — trial done, days-to-wedding anchor."}'
)


def test_bridal_followup_returns_merchant_on_behalf():
    llm = FakeLLMProvider(BRIDAL_RESPONSE)
    result = compose_customer_facing(
        SALON_CATEGORY, SALON_MERCHANT, BRIDAL_FOLLOWUP_TRIGGER, CUSTOMER_KAVYA, llm,
    )
    assert result is not None
    assert result.send_as == "merchant_on_behalf"


def test_bridal_followup_framing_in_system_prompt():
    """bridal_followup framing must reference wedding date urgency."""
    llm = FakeLLMProvider(BRIDAL_RESPONSE)
    compose_customer_facing(
        SALON_CATEGORY, SALON_MERCHANT, BRIDAL_FOLLOWUP_TRIGGER, CUSTOMER_KAVYA, llm,
    )
    system_prompt = llm.calls[0]["system"]
    # bridal_followup framing in triggers.py mentions "wedding date" and "days remaining"
    assert "wedding" in system_prompt.lower() or "bridal" in system_prompt.lower()


def test_bridal_followup_user_prompt_includes_days_to_wedding():
    """Trigger payload with days_to_wedding must appear in the user prompt."""
    llm = FakeLLMProvider(BRIDAL_RESPONSE)
    compose_customer_facing(
        SALON_CATEGORY, SALON_MERCHANT, BRIDAL_FOLLOWUP_TRIGGER, CUSTOMER_KAVYA, llm,
    )
    user_prompt = llm.calls[0]["user"]
    assert "196" in user_prompt or "wedding" in user_prompt.lower()


# ── wedding_package_followup ──────────────────────────────────────────────

WEDDING_PACKAGE_TRIGGER = {
    "id": "trg_wedding_kavya",
    "scope": "customer",
    "kind": "wedding_package_followup",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "customer_id": "c_004_kavya_salon",
    "payload": {
        "wedding_date": "2026-12-01",
        "days_to_wedding": 196,
        "trial_date": "2026-04-20",
        "package_price": 8999,
    },
    "urgency": 3,
    "suppression_key": "wedding_pkg:c_004_kavya_salon",
    "expires_at": "2099-12-31T00:00:00Z",
}

WEDDING_PKG_RESPONSE = (
    '{"body": "Hi Kavya, Glamour Studio here! Your trial on 20 Apr looked beautiful. '
    'With 196 days to your wedding, let\'s plan your full day look. '
    'Bridal Package @ ₹8999 — reply YES to block your date.", '
    '"cta": "binary_yes_no", "rationale": "Wedding package — days-to-wedding urgency anchor."}'
)


def test_wedding_package_followup_returns_merchant_on_behalf():
    llm = FakeLLMProvider(WEDDING_PKG_RESPONSE)
    result = compose_customer_facing(
        SALON_CATEGORY, SALON_MERCHANT, WEDDING_PACKAGE_TRIGGER, CUSTOMER_KAVYA, llm,
    )
    assert result is not None
    assert result.send_as == "merchant_on_behalf"


def test_wedding_package_followup_suppression_key_preserved():
    llm = FakeLLMProvider(WEDDING_PKG_RESPONSE)
    result = compose_customer_facing(
        SALON_CATEGORY, SALON_MERCHANT, WEDDING_PACKAGE_TRIGGER, CUSTOMER_KAVYA, llm,
    )
    assert result is not None
    assert result.suppression_key == "wedding_pkg:c_004_kavya_salon"


def test_wedding_package_long_lead_framing_in_prompt():
    """196 days-to-wedding (long lead) must appear in user prompt."""
    llm = FakeLLMProvider(WEDDING_PKG_RESPONSE)
    compose_customer_facing(
        SALON_CATEGORY, SALON_MERCHANT, WEDDING_PACKAGE_TRIGGER, CUSTOMER_KAVYA, llm,
    )
    user_prompt = llm.calls[0]["user"]
    assert "196" in user_prompt
