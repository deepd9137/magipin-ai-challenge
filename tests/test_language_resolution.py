from __future__ import annotations

from bot.language import resolve_language


MERCHANT_EN_ONLY = {
    "identity": {"languages": ["en"], "name": "Test Merchant"},
}

MERCHANT_HI_EN = {
    "identity": {"languages": ["en", "hi"], "name": "Test Merchant"},
}

MERCHANT_NO_LANG = {
    "identity": {"name": "Test Merchant"},
}

CUSTOMER_HI_EN_PREF = {
    "identity": {"name": "Priya", "language_pref": "hi-en mix"},
}

CUSTOMER_EN_PREF = {
    "identity": {"name": "John", "language_pref": "en"},
}

CUSTOMER_HI_ONLY = {
    "identity": {"name": "Ravi", "language_pref": "hi"},
}

CUSTOMER_NO_PREF = {
    "identity": {"name": "Sam"},
}


# ── Merchant-facing (no customer) ─────────────────────────────────────────

def test_merchant_hi_in_languages_returns_hi_en():
    assert resolve_language(MERCHANT_HI_EN) == "hi-en"


def test_merchant_en_only_returns_en():
    assert resolve_language(MERCHANT_EN_ONLY) == "en"


def test_merchant_no_languages_returns_en():
    assert resolve_language(MERCHANT_NO_LANG) == "en"


def test_merchant_hi_en_no_customer():
    assert resolve_language(MERCHANT_HI_EN, customer=None) == "hi-en"


# ── Customer-facing (customer overrides merchant) ─────────────────────────

def test_customer_hi_en_mix_overrides_merchant_en():
    """Customer pref=hi-en even when merchant is en-only → hi-en."""
    assert resolve_language(MERCHANT_EN_ONLY, CUSTOMER_HI_EN_PREF) == "hi-en"


def test_customer_hi_only_resolves_hi_en():
    assert resolve_language(MERCHANT_EN_ONLY, CUSTOMER_HI_ONLY) == "hi-en"


def test_customer_en_pref_returns_en():
    assert resolve_language(MERCHANT_HI_EN, CUSTOMER_EN_PREF) == "en"


def test_customer_no_pref_returns_en():
    assert resolve_language(MERCHANT_HI_EN, CUSTOMER_NO_PREF) == "en"


def test_customer_pref_with_uppercase_hi():
    customer = {"identity": {"name": "Test", "language_pref": "Hindi-English"}}
    assert resolve_language(MERCHANT_EN_ONLY, customer) == "hi-en"


def test_both_hi_stays_hi_en():
    """Both merchant and customer hi → hi-en."""
    assert resolve_language(MERCHANT_HI_EN, CUSTOMER_HI_EN_PREF) == "hi-en"


def test_empty_merchant_languages_list_returns_en():
    merchant = {"identity": {"languages": [], "name": "Test"}}
    assert resolve_language(merchant) == "en"
