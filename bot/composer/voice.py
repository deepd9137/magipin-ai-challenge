from __future__ import annotations

VOICE_PACKS: dict[str, dict] = {
    "dentists": {
        "tone": "peer_clinical",
        "salutation": "Dr. {first_name}",
        "register": "respectful_collegial",
        "vocab_taboo": ["guaranteed", "100% safe", "completely cure", "miracle", "best in city"],
        "voice_instructions": (
            "Address as 'Dr. {first_name}'. Peer-to-peer, not promotional. "
            "Use clinical vocabulary (fluoride varnish, caries, scaling) when relevant. "
            "Cite sources for any research claims with source + page/issue. "
            "Never make medical guarantees. Speak as a knowledgeable colleague, not a salesperson."
        ),
    },
    "salons": {
        "tone": "warm_practical",
        "salutation": "{first_name}",
        "register": "operator_peer",
        "vocab_taboo": ["amazing", "best deal ever", "limited time only"],
        "voice_instructions": (
            "Warm but not gushing. Operator-to-operator register. "
            "Service+price phrasing (Haircut @ ₹99) outperforms generic discounts. "
            "Reference actual services, slot times, and prices from context. "
            "Emojis sparingly — one max, only when appropriate."
        ),
    },
    "restaurants": {
        "tone": "operator_to_operator",
        "salutation": "{first_name}",
        "register": "fellow_operator",
        "vocab_taboo": ["delicious", "mouth-watering", "best food"],
        "voice_instructions": (
            "Talk like a fellow operator: covers, AOV, delivery radius, prep time. "
            "Acknowledge local match-day, festivals, weather impact on covers. "
            "Never use food-blogger language. Focus on operational outcomes."
        ),
    },
    "gyms": {
        "tone": "coach_motivational",
        "salutation": "{first_name}",
        "register": "coach_peer",
        "vocab_taboo": ["fat-burning miracle", "guaranteed weight loss"],
        "voice_instructions": (
            "Coach voice. Use 'members', 'retention', 'attendance', 'class capacity'. "
            "Evidence-based; acknowledge seasonal acquisition cycles. "
            "No shame language for lapsed customers — warm and no-judgment tone."
        ),
    },
    "pharmacies": {
        "tone": "trustworthy_precise",
        "salutation": "{first_name}",
        "register": "professional_peer",
        "vocab_taboo": ["miracle drug", "guaranteed cure", "100% effective"],
        "voice_instructions": (
            "Trustworthy and precise. Use generic + brand names correctly. "
            "Compliance-aware. Apply senior-citizen norms for elderly customers "
            "(namaste salutation, Hindi-English mix if appropriate, clear dosage language). "
            "Never overstate efficacy."
        ),
    },
}


def get_voice(category_slug: str) -> dict:
    """Return voice pack for category_slug; falls back to restaurants if unknown."""
    return VOICE_PACKS.get(category_slug, VOICE_PACKS["restaurants"])
