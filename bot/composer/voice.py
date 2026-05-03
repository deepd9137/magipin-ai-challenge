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


CUSTOMER_VOICE_PACKS: dict[str, dict] = {
    "dentists": {
        "tone": "warm_reassuring",
        "salutation": "Hi {customer_name}",
        "register": "clinical_friendly",
        "vocab_taboo": ["guaranteed", "100% safe", "completely cure", "miracle", "best in city"],
        "voice_instructions": (
            "You are composing FROM the dental clinic TO the patient. "
            "Address the customer warmly by first name. Mention the clinic name early. "
            "Use plain, non-clinical language (say 'cleaning' not 'scaling' unless patient knows it). "
            "For recall/appointment messages: state the timing clearly, offer specific slots. "
            "One emoji max (🦷), skip it for clinical context. No promotional tone."
        ),
    },
    "salons": {
        "tone": "warm_friendly",
        "salutation": "Hi {customer_name}",
        "register": "personal_friendly",
        "vocab_taboo": ["amazing", "best deal ever", "limited time only"],
        "voice_instructions": (
            "You are composing FROM the salon TO the customer. "
            "Warm, personal, like a message from their regular stylist. "
            "Reference services they've had before, upcoming occasions, or lapse duration. "
            "Service+price phrasing preferred. One emoji max (💇 or ✨)."
        ),
    },
    "restaurants": {
        "tone": "warm_inviting",
        "salutation": "Hi {customer_name}",
        "register": "local_friendly",
        "vocab_taboo": ["delicious", "mouth-watering", "best food"],
        "voice_instructions": (
            "You are composing FROM the restaurant TO the customer. "
            "Friendly, personal, like a local they know. "
            "Reference their visit history or seasonal specials. "
            "No food-blogger language. One emoji max."
        ),
    },
    "gyms": {
        "tone": "motivational_warm",
        "salutation": "Hi {customer_name}",
        "register": "coach_personal",
        "vocab_taboo": ["fat-burning miracle", "guaranteed weight loss"],
        "voice_instructions": (
            "You are composing FROM the gym TO the member. "
            "Coach tone — warm, no shame, no judgment for lapsed members. "
            "Reference their past goal or class they attended. "
            "Low-friction CTA — make returning feel easy, not guilt-inducing. "
            "One emoji max (💪)."
        ),
    },
    "pharmacies": {
        "tone": "trustworthy_caring",
        "salutation": "Hi {customer_name}",
        "register": "professional_caring",
        "vocab_taboo": ["miracle drug", "guaranteed cure", "100% effective"],
        "voice_instructions": (
            "You are composing FROM the pharmacy TO the patient. "
            "Trustworthy, caring, precise. "
            "For elderly customers (age_band 60+): use 'Namaste {customer_name}', "
            "Hindi-English mix if language_pref includes 'hi'. "
            "State molecule/brand names clearly. Single-step action to confirm. "
            "Never overstate drug efficacy."
        ),
    },
}

_CUSTOMER_VOICE_DEFAULT = {
    "tone": "warm_professional",
    "salutation": "Hi {customer_name}",
    "register": "personal_friendly",
    "vocab_taboo": [],
    "voice_instructions": (
        "You are composing FROM the merchant TO the customer. "
        "Warm, personal, clear. State the reason for reaching out. "
        "Single clear CTA in the last sentence."
    ),
}


def get_voice(category_slug: str) -> dict:
    """Return merchant-facing voice pack; falls back to restaurants if unknown."""
    return VOICE_PACKS.get(category_slug, VOICE_PACKS["restaurants"])


def get_customer_voice(category_slug: str) -> dict:
    """Return customer-facing voice pack; falls back to default if unknown."""
    return CUSTOMER_VOICE_PACKS.get(category_slug, _CUSTOMER_VOICE_DEFAULT)
