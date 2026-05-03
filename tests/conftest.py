from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bot.llm.adapter import LLMProvider
from bot.main import app
from bot.state import store


class FakeLLMProvider(LLMProvider):
    """Synchronous fake LLM that returns a configurable canned response."""

    def __init__(self, response: str = "") -> None:
        self._response = response
        self.calls: list[dict] = []

    def complete(self, system: str, user: str, max_tokens: int = 800,
                 temperature: float = 0.0, timeout: int = 25) -> str:
        self.calls.append({"system": system, "user": user})
        return self._response

    def name(self) -> str:
        return "fake:test"

    def set_response(self, response: str) -> None:
        self._response = response


@pytest.fixture(autouse=True)
def reset_state():
    """Wipe in-memory state before every test for isolation."""
    store.reset()
    yield
    store.reset()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def fake_llm():
    return FakeLLMProvider()


# ── Shared context payloads used across tests ─────────────────────────────

SAMPLE_CATEGORY = {
    "slug": "dentists",
    "display_name": "Dentists",
    "voice": {
        "tone": "peer_clinical",
        "register": "respectful_collegial",
        "code_mix": "hindi_english_natural",
        "vocab_allowed": ["fluoride varnish", "scaling", "caries"],
        "vocab_taboo": ["guaranteed", "miracle", "cure"],
        "salutation_examples": ["Dr. {first_name}"],
        "tone_examples": ["Worth a look — JIDA Oct 2026 p.14"],
    },
    "offer_catalog": [
        {"id": "den_001", "title": "Dental Cleaning @ ₹299", "value": "299",
         "audience": "new_user", "type": "service_at_price"},
    ],
    "peer_stats": {"avg_ctr": 0.03, "avg_views_30d": 3000},
    "digest": [
        {"item_id": "d_2026W17_jida_fluoride",
         "headline": "3-month fluoride recall cuts caries 38% vs 6-month in 2,100-patient trial",
         "source": "JIDA Oct 2026 p.14"},
    ],
}

SAMPLE_MERCHANT = {
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "category_slug": "dentists",
    "identity": {
        "name": "Dr. Meera's Dental Clinic",
        "city": "Delhi",
        "locality": "Lajpat Nagar",
        "languages": ["en", "hi"],
        "owner_first_name": "Meera",
        "established_year": 2018,
    },
    "subscription": {"status": "active", "plan": "Pro", "days_remaining": 82},
    "performance": {
        "window_days": 30, "views": 2410, "calls": 18, "ctr": 0.021, "leads": 9,
        "delta_7d": {"views_pct": 0.18, "calls_pct": -0.05},
    },
    "offers": [
        {"id": "o_meera_001", "title": "Dental Cleaning @ ₹299", "status": "active"},
    ],
    "signals": ["stale_posts:22d", "ctr_below_peer_median", "high_risk_adult_cohort"],
    "customer_aggregate": {"total_unique_ytd": 540, "high_risk_adult_count": 124},
    "conversation_history": [],
    "review_themes": [],
}

SAMPLE_TRIGGER = {
    "id": "trg_001_research_digest_dentists",
    "scope": "merchant",
    "kind": "research_digest",
    "source": "external",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "customer_id": None,
    "payload": {
        "category": "dentists",
        "top_item_id": "d_2026W17_jida_fluoride",
    },
    "urgency": 2,
    "suppression_key": "research:dentists:2026-W17",
    "expires_at": "2099-12-31T00:00:00Z",
}

VALID_LLM_RESPONSE = (
    '{"body": "Dr. Meera, JIDA Oct 2026 p.14: 3-month fluoride recall cuts caries 38% '
    'in a 2,100-patient trial — relevant for your 124 high-risk adults. Want me to pull '
    'the abstract?", "cta": "binary_yes_no", "rationale": "Research digest anchor with merchant-specific cohort."}'
)
