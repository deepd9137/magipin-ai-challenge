from __future__ import annotations

import pytest

from bot.validation.validators import validate, _check_fabrication

# ── Shared context fixtures ───────────────────────────────────────────────

DENTIST_CATEGORY = {
    "slug": "dentists",
    "voice": {
        "vocab_taboo": ["guaranteed", "miracle", "cure"],
    },
    "digest": [
        {
            "headline": "3-month fluoride recall cuts caries 38% vs 6-month in 2,100-patient trial",
            "source": "JIDA Oct 2026 p.14",
        }
    ],
}

SAMPLE_MERCHANT = {
    "merchant_id": "m_001",
    "customer_aggregate": {"high_risk_adult_count": 124},
}

SAMPLE_TRIGGER = {
    "id": "trg_001",
    "kind": "research_digest",
    "suppression_key": "research:dentists:2026-W17",
    "expires_at": "2099-12-31T00:00:00Z",
    "payload": {"trial_n": 2100},
}

CLEAN_BODY = (
    "Dr. Meera, JIDA Oct 2026 p.14: fluoride recall cuts caries 38% in "
    "2,100-patient trial — your 124 high-risk adults are the target cohort. "
    "Want me to pull the abstract?"
)


# ── Length checks ─────────────────────────────────────────────────────────

def test_validates_clean_body_passes():
    result = validate(CLEAN_BODY, "binary_yes_no", DENTIST_CATEGORY,
                      SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, [])
    assert result.valid, f"Unexpected failures: {result.failures}"


def test_rejects_empty_body():
    result = validate("", "open_ended", DENTIST_CATEGORY,
                      SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, [])
    assert not result.valid
    assert "body_too_short" in result.failures


def test_rejects_too_short():
    result = validate("hi", "open_ended", DENTIST_CATEGORY,
                      SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, [])
    assert "body_too_short" in result.failures


def test_rejects_too_long():
    result = validate("x" * 801, "open_ended", DENTIST_CATEGORY,
                      SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, [])
    assert "body_too_long" in result.failures


# ── URL checks ────────────────────────────────────────────────────────────

def test_rejects_https_url():
    result = validate(
        "Check https://example.com for details",
        "open_ended", DENTIST_CATEGORY, SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, [],
    )
    assert "contains_url" in result.failures


def test_rejects_www_url():
    result = validate(
        "Visit www.example.com today",
        "open_ended", DENTIST_CATEGORY, SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, [],
    )
    assert "contains_url" in result.failures


def test_rejects_bitly():
    result = validate(
        "Click bit.ly/xyz to register",
        "open_ended", DENTIST_CATEGORY, SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, [],
    )
    assert "contains_url" in result.failures


# ── Taboo vocabulary ──────────────────────────────────────────────────────

def test_rejects_taboo_word_guaranteed():
    body = "This is guaranteed to reduce caries for your patients."
    result = validate(body, "open_ended", DENTIST_CATEGORY,
                      SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, [])
    assert any("taboo_word" in f for f in result.failures)


def test_rejects_taboo_word_miracle():
    body = "This miracle technique works wonders for your patients."
    result = validate(body, "open_ended", DENTIST_CATEGORY,
                      SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, [])
    assert any("taboo_word:miracle" in f for f in result.failures)


def test_no_false_taboo_on_clean_body():
    result = validate(CLEAN_BODY, "binary_yes_no", DENTIST_CATEGORY,
                      SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, [])
    assert not any("taboo_word" in f for f in result.failures)


# ── CTA shape ─────────────────────────────────────────────────────────────

def test_rejects_invalid_cta():
    result = validate(CLEAN_BODY, "unknown_cta_type", DENTIST_CATEGORY,
                      SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, [])
    assert any("invalid_cta" in f for f in result.failures)


def test_accepts_all_valid_cta_types():
    for cta in ("open_ended", "binary_yes_no", "binary_confirm_cancel",
                "multi_choice_slot", "none"):
        result = validate(CLEAN_BODY, cta, DENTIST_CATEGORY,
                          SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, [])
        assert not any("invalid_cta" in f for f in result.failures), f"CTA {cta!r} was rejected"


# ── Anti-fabrication ──────────────────────────────────────────────────────

def test_anti_fabrication_passes_known_number_from_context():
    """2,100 is in DENTIST_CATEGORY digest and SAMPLE_TRIGGER payload (trial_n: 2100) → pass."""
    body = "A 2,100-patient trial showed 38% improvement for your 124 patients."
    result = validate(body, "open_ended", DENTIST_CATEGORY,
                      SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, [])
    assert not any("unverified_number" in f for f in result.failures), (
        f"False fabrication failures: {result.failures}"
    )


def test_anti_fabrication_rejects_unknown_number():
    """5,000 patients is NOT in any context → should flag as fabricated."""
    trigger_no_5000 = {**SAMPLE_TRIGGER, "payload": {}}
    body = "A 5,000-patient study shows dramatic results for your clinic."
    result = validate(body, "open_ended", DENTIST_CATEGORY,
                      SAMPLE_MERCHANT, trigger_no_5000, None, [])
    assert any("unverified_number:5000" in f for f in result.failures), (
        f"Expected fabrication flag, got: {result.failures}"
    )


def test_anti_fabrication_caps_at_two_failures():
    """Multiple fabricated numbers → at most 2 fabrication failures reported."""
    trigger_clean = {**SAMPLE_TRIGGER, "payload": {}}
    body = "A 5,000-patient study with 7,890 cases and 12,345 controls."
    result = validate(body, "open_ended",
                      {"slug": "dentists", "voice": {"vocab_taboo": []}, "digest": []},
                      {}, trigger_clean, None, [])
    fab_failures = [f for f in result.failures if "unverified_number" in f]
    assert len(fab_failures) <= 2


def test_anti_fabrication_ignores_single_digits():
    """Single-digit numbers are too noisy to track."""
    body = "After 3 months, the results show clear improvement. Reply 1 for yes."
    trigger_clean = {**SAMPLE_TRIGGER, "payload": {"months": 3}}
    result = validate(body, "binary_yes_no",
                      {"slug": "dentists", "voice": {"vocab_taboo": []}, "digest": []},
                      {}, trigger_clean, None, [])
    assert not any("unverified_number:3" in f or "unverified_number:1" in f
                   for f in result.failures)


def test_anti_fabrication_percentage_in_context_as_decimal():
    """Body has '38%', context has 0.38 as a float → no fabrication failure."""
    category_with_decimal = {
        "slug": "gyms",
        "voice": {"vocab_taboo": []},
        "peer_stats": {"seasonal_dip_pct": 0.38},
    }
    body = "Your views fell 38% — this is normal for the April window."
    result = validate(body, "open_ended", category_with_decimal,
                      {}, {"id": "t1", "kind": "seasonal_perf_dip", "payload": {}}, None, [])
    assert not any("unverified_number:38%" in f for f in result.failures), (
        f"False fabrication: {result.failures}"
    )


# ── Repetition detection ──────────────────────────────────────────────────

def test_repetition_detection_identical_body():
    prior = [CLEAN_BODY]
    result = validate(CLEAN_BODY, "binary_yes_no", DENTIST_CATEGORY,
                      SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, prior)
    assert "verbatim_repetition" in result.failures


def test_repetition_detection_different_body_passes():
    prior = ["Some completely different message about something else."]
    result = validate(CLEAN_BODY, "binary_yes_no", DENTIST_CATEGORY,
                      SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, prior)
    assert "verbatim_repetition" not in result.failures


def test_repetition_detection_whitespace_normalized():
    """Whitespace differences should not prevent repetition detection."""
    prior = [re.sub(r"\s+", "  ", CLEAN_BODY)]
    result = validate(CLEAN_BODY, "binary_yes_no", DENTIST_CATEGORY,
                      SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, prior)
    assert "verbatim_repetition" in result.failures


def test_no_repetition_on_empty_prior_list():
    result = validate(CLEAN_BODY, "binary_yes_no", DENTIST_CATEGORY,
                      SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, [])
    assert "verbatim_repetition" not in result.failures


import re  # needed for the whitespace test above
