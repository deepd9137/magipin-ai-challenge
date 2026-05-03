from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

BASE_SYSTEM = """\
You are Vera, magicpin's merchant AI assistant. You compose short, high-impact WhatsApp \
messages for Indian merchants and their customers. You have access to rich context: \
category intelligence, merchant performance data, and the specific trigger that makes \
now the right time to message.

CORE RULES (non-negotiable):
1. Specificity over generics — anchor every message on a concrete fact (number, date, \
headline, source citation) drawn from the contexts. Generic copy ("10% off") is penalised.
2. Single CTA in the last sentence. No buried CTAs, no multiple asks.
3. No URLs in the body (Meta WhatsApp template restriction — hard penalty -3 per URL).
4. No fabrication — every number, percentage, date, named entity, and citation in your \
body MUST appear verbatim in the provided context. Do not invent or infer statistics.
5. Voice match — use the category's tone profile and salutation style.
6. Hindi-English code-mix is fine when merchant.identity.languages includes "hi".
7. Use owner_first_name when present (not the full business name as salutation).
8. No long preambles ("I hope you are well"). Get to the point.
9. Restraint — if the trigger does not merit a message, output an empty body "".

OUTPUT FORMAT — strict JSON only, no markdown, no commentary:
{
  "body": "<the WhatsApp message text, or empty string if skipping>",
  "cta": "open_ended" | "binary_yes_no" | "binary_confirm_cancel" | "multi_choice_slot" | "none",
  "rationale": "<1-2 sentence explanation of why this message, what compulsion lever used>"
}
"""

CUSTOMER_BASE_SYSTEM = """\
You are Vera, composing a WhatsApp message that will be SENT FROM the merchant's WhatsApp \
number TO one of their customers. The customer should feel this message comes directly from \
the merchant they know — not from an AI platform.

CORE RULES (non-negotiable):
1. Address the customer by first name. Mention the merchant's business name early.
2. State a clear, specific reason for reaching out (timing, service due, lapse duration).
3. All slot times, prices, and facts must come verbatim from the provided contexts — no fabrication.
4. No URLs in the body (Meta WhatsApp template restriction).
5. Single CTA in the last sentence. Multi-choice slot ("Reply 1 for X, 2 for Y") is appropriate \
for booking flows.
6. Honor the customer's language preference — use Hindi-English code-mix if specified.
7. Warm, personal tone. No corporate language. No long preambles.
8. No taboo words from the category voice pack.
9. If the trigger does not warrant a message (e.g. consent issue, stale), output empty body "".

OUTPUT FORMAT — strict JSON only, no markdown, no commentary:
{
  "body": "<WhatsApp message text, or empty string if skipping>",
  "cta": "binary_yes_no" | "multi_choice_slot" | "binary_confirm_cancel" | "none",
  "rationale": "<why this message and what customer signal prompted it>"
}
"""


def build_system_prompt(voice_pack: Dict[str, Any], framing: str) -> str:
    """Build the per-composition system prompt: base rules + category voice + trigger framing."""
    salutation = voice_pack.get("salutation", "{first_name}")
    taboo: List[str] = voice_pack.get("vocab_taboo", [])
    voice_instructions = voice_pack.get("voice_instructions", "")

    voice_section = (
        "\n=== VOICE PACK ===\n"
        f"Salutation format: {salutation}\n"
        f"Additional taboo words (never use): {', '.join(taboo) if taboo else 'none'}\n"
        f"Voice instructions: {voice_instructions}\n"
    )

    framing_section = (
        "\n=== TRIGGER FRAMING GUIDE ===\n"
        f"Follow this guidance to shape your message for this specific trigger kind:\n"
        f"{framing}\n"
    )

    return BASE_SYSTEM + voice_section + framing_section


def build_customer_system_prompt(
    voice_pack: Dict[str, Any],
    framing: str,
    language: str,
) -> str:
    """Build the customer-facing system prompt: base rules + customer voice + framing + language."""
    salutation = voice_pack.get("salutation", "Hi {customer_name}")
    taboo: List[str] = voice_pack.get("vocab_taboo", [])
    voice_instructions = voice_pack.get("voice_instructions", "")

    voice_section = (
        "\n=== CUSTOMER-FACING VOICE PACK ===\n"
        f"Salutation format: {salutation}\n"
        f"Taboo words (never use): {', '.join(taboo) if taboo else 'none'}\n"
        f"Voice instructions: {voice_instructions}\n"
    )

    framing_section = (
        "\n=== TRIGGER FRAMING GUIDE ===\n"
        f"{framing}\n"
    )

    lang_instruction = (
        "\n=== LANGUAGE ===\n"
        + (
            "Use Hindi-English code-mix (Hinglish). Natural mix — "
            "English for medical/technical terms, Hindi for warmth and personal touch. "
            "Romanized Hindi is fine (e.g. 'Apke liye', 'bilkul', 'aaj'). "
            "Do NOT use Devanagari script.\n"
            if language == "hi-en"
            else "Use English only.\n"
        )
    )

    return CUSTOMER_BASE_SYSTEM + voice_section + framing_section + lang_instruction


def _safe(val: Any) -> str:
    if val is None:
        return "N/A"
    if isinstance(val, (dict, list)):
        return json.dumps(val, ensure_ascii=False)
    return str(val)


def _degradation_notes(
    merchant: Dict[str, Any],
    category: Dict[str, Any],
    customer: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Return explicit instructions the LLM should follow for any missing optional fields."""
    notes: List[str] = []
    identity = merchant.get("identity", {})

    if not identity.get("owner_first_name"):
        biz_name = identity.get("name", "the business")
        notes.append(
            f"IMPORTANT — owner_first_name is missing: do NOT write 'Dr. None' or 'N/A'. "
            f"Use 'Hi team at {biz_name}' or just the business name as the opener."
        )

    if not merchant.get("customer_aggregate"):
        notes.append(
            "IMPORTANT — customer_aggregate is missing: do NOT reference cohort counts, "
            "total patients, or aggregate stats. Focus on performance metrics and trigger payload."
        )

    if not category.get("digest"):
        notes.append(
            "IMPORTANT — research digest is empty: skip any research citation. "
            "Anchor the message on merchant performance signals and trigger payload instead."
        )

    if not category.get("voice"):
        notes.append(
            "IMPORTANT — category voice block is missing: use a neutral, professional register "
            "appropriate for the category slug."
        )

    if customer and not customer.get("identity", {}).get("name"):
        notes.append(
            "IMPORTANT — customer name is missing: use a generic greeting like 'Hi there' "
            "or 'Namaste' instead of a name."
        )

    return notes


def build_user_prompt(
    category: Dict[str, Any],
    merchant: Dict[str, Any],
    trigger: Dict[str, Any],
    customer: Optional[Dict[str, Any]] = None,
) -> str:
    voice = category.get("voice", {})
    identity = merchant.get("identity", {})
    perf = merchant.get("performance", {})
    active_offers = [o for o in merchant.get("offers", []) if o.get("status") == "active"]
    digest_items = category.get("digest", [])[:5]

    # Graceful degradation: emit explicit instructions for missing optional fields.
    degrade = _degradation_notes(merchant, category, customer)

    parts = [
        "=== CATEGORY CONTEXT ===",
        f"Slug: {_safe(category.get('slug'))}",
        f"Display name: {_safe(category.get('display_name'))}",
        f"Voice tone: {_safe(voice.get('tone'))}",
        f"Register: {_safe(voice.get('register'))}",
        f"Code mix: {_safe(voice.get('code_mix'))}",
        f"Vocab allowed: {_safe(voice.get('vocab_allowed'))}",
        f"Vocab taboo (never use): {_safe(voice.get('vocab_taboo'))}",
        f"Salutation examples: {_safe(voice.get('salutation_examples'))}",
        f"Tone examples: {_safe(voice.get('tone_examples'))}",
        f"Offer catalog: {_safe([o['title'] for o in category.get('offer_catalog', [])])}",
        f"Peer stats: {_safe(category.get('peer_stats'))}",
        f"Research digest (top 5): {_safe(digest_items) if digest_items else 'NOT AVAILABLE — skip citations'}",
        f"Seasonal beats: {_safe(category.get('seasonal_beats'))}",
        f"Trend signals: {_safe(category.get('trend_signals'))}",
        "",
        "=== MERCHANT CONTEXT ===",
        f"Business name: {_safe(identity.get('name'))}",
        f"Owner first name: {_safe(identity.get('owner_first_name'))}",
        f"City: {_safe(identity.get('city'))}, Locality: {_safe(identity.get('locality'))}",
        f"Languages: {_safe(identity.get('languages'))}",
        f"Subscription: {_safe(merchant.get('subscription'))}",
        f"Performance (30d): views={_safe(perf.get('views'))}, calls={_safe(perf.get('calls'))}, "
        f"ctr={_safe(perf.get('ctr'))}, leads={_safe(perf.get('leads'))}",
        f"7d delta: {_safe(perf.get('delta_7d'))}",
        f"Active offers: {_safe([o['title'] for o in active_offers])}",
        f"Signals: {_safe(merchant.get('signals'))}",
        f"Customer aggregate: {_safe(merchant.get('customer_aggregate')) if merchant.get('customer_aggregate') else 'NOT AVAILABLE — omit cohort stats'}",
        f"Review themes: {_safe(merchant.get('review_themes'))}",
        f"Recent conversation: {_safe(merchant.get('conversation_history', [])[-2:])}",
    ]

    if customer:
        cust_identity = customer.get("identity", {})
        parts += [
            "",
            "=== CUSTOMER CONTEXT ===",
            f"Name: {_safe(cust_identity.get('name'))}",
            f"Language pref: {_safe(cust_identity.get('language_pref'))}",
            f"Age band: {_safe(cust_identity.get('age_band'))}",
            f"Relationship: {_safe(customer.get('relationship'))}",
            f"State: {_safe(customer.get('state'))}",
            f"Lapse days: {_safe(customer.get('lapse_days'))}",
            f"Consent scope: {_safe(customer.get('consent', {}).get('scope'))}",
            f"Visit history: {_safe(customer.get('visit_history'))}",
        ]

    parts += [
        "",
        "=== TRIGGER CONTEXT ===",
        f"Trigger ID: {_safe(trigger.get('id'))}",
        f"Kind: {_safe(trigger.get('kind'))}",
        f"Scope: {_safe(trigger.get('scope'))}",
        f"Source: {_safe(trigger.get('source'))}",
        f"Urgency (1-5): {_safe(trigger.get('urgency'))}",
        f"Suppression key: {_safe(trigger.get('suppression_key'))}",
        f"Expires at: {_safe(trigger.get('expires_at'))}",
        f"Payload: {_safe(trigger.get('payload'))}",
        f"Merchant ID: {_safe(trigger.get('merchant_id'))}",
        f"Customer ID: {_safe(trigger.get('customer_id'))}",
        "",
        "Compose the next WhatsApp message based on the above contexts.",
        "Output strict JSON only — no markdown, no code fences, no commentary.",
    ]

    if degrade:
        parts += ["", "=== MISSING DATA INSTRUCTIONS ==="] + degrade

    return "\n".join(parts)


def build_customer_user_prompt(
    category: Dict[str, Any],
    merchant: Dict[str, Any],
    trigger: Dict[str, Any],
    customer: Dict[str, Any],
) -> str:
    """Build the user prompt for customer-facing composition.

    Focuses on the customer relationship and trigger specifics, not merchant performance.
    """
    identity = merchant.get("identity", {})
    cust_identity = customer.get("identity", {})
    active_offers = [o for o in merchant.get("offers", []) if o.get("status") == "active"]
    t_payload = trigger.get("payload", {})

    degrade = _degradation_notes(merchant, category, customer)

    parts = [
        "=== MERCHANT (SENDER) CONTEXT ===",
        f"Business name: {_safe(identity.get('name'))}",
        f"Category: {_safe(category.get('display_name'))} ({_safe(category.get('slug'))})",
        f"City: {_safe(identity.get('city'))}, Locality: {_safe(identity.get('locality'))}",
        f"Active offers: {_safe([o['title'] for o in active_offers])}",
        "",
        "=== CUSTOMER (RECIPIENT) CONTEXT ===",
        f"Name: {_safe(cust_identity.get('name'))}",
        f"Language pref: {_safe(cust_identity.get('language_pref'))}",
        f"Age band: {_safe(cust_identity.get('age_band'))}",
        f"Relationship state: {_safe(customer.get('state'))}",
        f"First visit: {_safe(customer.get('relationship', {}).get('first_visit') if isinstance(customer.get('relationship'), dict) else customer.get('relationship'))}",
        f"Last visit: {_safe(customer.get('relationship', {}).get('last_visit') if isinstance(customer.get('relationship'), dict) else 'N/A')}",
        f"Services received: {_safe(customer.get('relationship', {}).get('services_received') if isinstance(customer.get('relationship'), dict) else 'N/A')}",
        f"Lapse days: {_safe(customer.get('lapse_days'))}",
        f"Visit history: {_safe(customer.get('visit_history'))}",
        "",
        "=== TRIGGER CONTEXT ===",
        f"Kind: {_safe(trigger.get('kind'))}",
        f"Scope: customer",
        f"Urgency (1-5): {_safe(trigger.get('urgency'))}",
        f"Suppression key: {_safe(trigger.get('suppression_key'))}",
        f"Trigger payload: {_safe(t_payload)}",
        "",
        "=== CATEGORY SIGNALS (for context) ===",
        f"Offer catalog: {_safe([o['title'] for o in category.get('offer_catalog', [])])}",
        f"Peer stats: {_safe(category.get('peer_stats'))}",
        "",
        "Compose a WhatsApp message FROM the merchant TO the customer.",
        "The message must feel personal, specific to this customer's relationship with the merchant.",
        "Output strict JSON only — no markdown, no code fences, no commentary.",
    ]

    if degrade:
        parts += ["", "=== MISSING DATA INSTRUCTIONS ==="] + degrade

    return "\n".join(parts)
