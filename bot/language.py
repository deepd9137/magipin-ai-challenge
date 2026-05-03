from __future__ import annotations


def resolve_language(merchant: dict, customer: dict | None = None) -> str:
    """Return the language mode to use for this message.

    Returns one of: 'en', 'hi-en' (Hindi-English code-mix).
    Customer language preference overrides merchant when composing customer-facing messages.
    """
    if customer:
        pref = customer.get("identity", {}).get("language_pref", "")
        if "hi" in pref.lower():
            return "hi-en"
        return "en"

    langs = merchant.get("identity", {}).get("languages", ["en"])
    if "hi" in langs:
        return "hi-en"
    return "en"
