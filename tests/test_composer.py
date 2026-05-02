from __future__ import annotations

import json

import pytest

from bot.composer.composer import compose, _parse_json, _validate
from bot.state import ComposedMessage
from tests.conftest import (
    FakeLLMProvider,
    SAMPLE_CATEGORY,
    SAMPLE_MERCHANT,
    SAMPLE_TRIGGER,
    VALID_LLM_RESPONSE,
)


# ── _parse_json unit tests ────────────────────────────────────────────────

def test_parse_plain_json():
    raw = '{"body": "hello", "cta": "open_ended", "rationale": "test"}'
    result = _parse_json(raw)
    assert result is not None
    assert result["body"] == "hello"


def test_parse_code_fenced_json():
    raw = '```json\n{"body": "hello", "cta": "binary_yes_no", "rationale": "r"}\n```'
    result = _parse_json(raw)
    assert result is not None
    assert result["cta"] == "binary_yes_no"


def test_parse_bare_code_fence():
    raw = '```\n{"body": "hi", "cta": "none", "rationale": "r"}\n```'
    result = _parse_json(raw)
    assert result is not None


def test_parse_invalid_json_returns_none():
    assert _parse_json("not json at all") is None


def test_parse_empty_string_returns_none():
    assert _parse_json("") is None


# ── _validate unit tests ──────────────────────────────────────────────────

def test_validate_valid_message():
    failures = _validate("Dr. Meera, this is a valid message.", "binary_yes_no", [])
    assert failures == []


def test_validate_empty_body():
    assert "empty_body" in _validate("", "open_ended", [])


def test_validate_too_short():
    assert "body_too_short" in _validate("hi", "open_ended", [])


def test_validate_too_long():
    failures = _validate("x" * 801, "open_ended", [])
    assert "body_too_long" in failures


def test_validate_url_in_body():
    failures = _validate("Check https://example.com for details", "open_ended", [])
    assert "url_in_body" in failures


def test_validate_www_url():
    failures = _validate("Visit www.example.com", "open_ended", [])
    assert "url_in_body" in failures


def test_validate_invalid_cta():
    failures = _validate("Valid message here.", "unknown_cta_type", [])
    assert any("invalid_cta" in f for f in failures)


def test_validate_taboo_word():
    failures = _validate("This is guaranteed to cure your pain.", "open_ended", ["guaranteed", "cure"])
    assert any("taboo_word" in f for f in failures)


# ── compose() unit tests ──────────────────────────────────────────────────

def test_compose_returns_composed_message(fake_llm):
    fake_llm.set_response(VALID_LLM_RESPONSE)
    result = compose(SAMPLE_CATEGORY, SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, fake_llm)
    assert result is not None
    assert isinstance(result, ComposedMessage)
    assert result.body
    assert result.cta in {"open_ended", "binary_yes_no", "binary_confirm_cancel", "multi_choice_slot", "none"}
    assert result.rationale
    assert result.suppression_key == SAMPLE_TRIGGER["suppression_key"]


def test_compose_prompt_includes_all_contexts(fake_llm):
    fake_llm.set_response(VALID_LLM_RESPONSE)
    compose(SAMPLE_CATEGORY, SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, fake_llm)
    assert len(fake_llm.calls) == 1
    user_prompt = fake_llm.calls[0]["user"]
    # All 3 mandatory sections present
    assert "=== CATEGORY CONTEXT ===" in user_prompt
    assert "=== MERCHANT CONTEXT ===" in user_prompt
    assert "=== TRIGGER CONTEXT ===" in user_prompt
    # Key data points present
    assert "dentists" in user_prompt
    assert "Meera" in user_prompt
    assert "research_digest" in user_prompt


def test_compose_includes_customer_context_when_provided(fake_llm):
    fake_llm.set_response(VALID_LLM_RESPONSE)
    customer = {
        "identity": {"name": "Priya", "language_pref": "hi"},
        "state": "lapsed_soft",
        "consent": {"scope": ["recall_due"]},
    }
    trigger_with_customer = {**SAMPLE_TRIGGER, "scope": "customer", "customer_id": "c_001"}
    compose(SAMPLE_CATEGORY, SAMPLE_MERCHANT, trigger_with_customer, customer, fake_llm)
    user_prompt = fake_llm.calls[0]["user"]
    assert "=== CUSTOMER CONTEXT ===" in user_prompt
    assert "Priya" in user_prompt


def test_compose_send_as_vera_for_merchant_scope(fake_llm):
    fake_llm.set_response(VALID_LLM_RESPONSE)
    result = compose(SAMPLE_CATEGORY, SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, fake_llm)
    assert result is not None
    assert result.send_as == "vera"


def test_compose_send_as_merchant_on_behalf_for_customer_scope(fake_llm):
    fake_llm.set_response(VALID_LLM_RESPONSE)
    cust_trigger = {**SAMPLE_TRIGGER, "scope": "customer"}
    customer = {"identity": {"name": "Priya", "language_pref": "hi"}, "consent": {"scope": []}}
    result = compose(SAMPLE_CATEGORY, SAMPLE_MERCHANT, cust_trigger, customer, fake_llm)
    assert result is not None
    assert result.send_as == "merchant_on_behalf"


def test_compose_returns_none_on_invalid_json(fake_llm):
    fake_llm.set_response("this is not json at all")
    result = compose(SAMPLE_CATEGORY, SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, fake_llm)
    assert result is None


def test_compose_returns_none_on_empty_body(fake_llm):
    fake_llm.set_response('{"body": "", "cta": "open_ended", "rationale": "skip"}')
    result = compose(SAMPLE_CATEGORY, SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, fake_llm)
    assert result is None


def test_compose_retries_on_validation_failure(fake_llm):
    """First response has a URL (fails); second is valid — should retry once and succeed."""
    responses = [
        '{"body": "Check https://example.com for details", "cta": "open_ended", "rationale": "r"}',
        VALID_LLM_RESPONSE,
    ]
    call_count = 0

    class RetryFakeLLM(FakeLLMProvider):
        def complete(self, system, user, **kwargs):
            nonlocal call_count
            resp = responses[min(call_count, len(responses) - 1)]
            call_count += 1
            return resp

    result = compose(SAMPLE_CATEGORY, SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, RetryFakeLLM())
    assert result is not None
    assert call_count == 2


def test_compose_returns_none_after_two_failures(fake_llm):
    """Two consecutive bad responses → None."""
    fake_llm.set_response("not json")
    result = compose(SAMPLE_CATEGORY, SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, fake_llm)
    assert result is None
    assert len(fake_llm.calls) == 2  # retried once


def test_compose_returns_none_on_llm_exception():
    class ErrorLLM(FakeLLMProvider):
        def complete(self, *args, **kwargs):
            raise RuntimeError("network error")

    result = compose(SAMPLE_CATEGORY, SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, ErrorLLM())
    assert result is None


def test_compose_template_name_uses_trigger_kind(fake_llm):
    fake_llm.set_response(VALID_LLM_RESPONSE)
    result = compose(SAMPLE_CATEGORY, SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, fake_llm)
    assert result is not None
    assert "research_digest" in result.template_name


def test_compose_template_params_include_owner_name(fake_llm):
    fake_llm.set_response(VALID_LLM_RESPONSE)
    result = compose(SAMPLE_CATEGORY, SAMPLE_MERCHANT, SAMPLE_TRIGGER, None, fake_llm)
    assert result is not None
    assert "Meera" in result.template_params
