# Phase 2 — LLM Composer Baseline

## Goal
Replace the empty `/v1/tick` stub with a working LLM-driven composer. Given a trigger, look up its merchant + category contexts, build a prompt, call the LLM, and return a well-formed `action` JSON. This phase delivers the **first end-to-end "Vera says something"** moment.

---

## Why this phase next
Phase 1 proved the bot can hold state. This phase proves it can **act on that state** by producing a real WhatsApp message. The output won't be score-optimal yet (that's Phase 3), but it will be:
- Structurally valid (passes the judge's schema check)
- Driven by actual context data (not hardcoded)
- Reproducible (temperature=0)

This phase exists separately because LLM integration is its own slice of complexity (provider auth, prompt design, JSON parsing, timeouts) that benefits from being landed and tested in isolation.

---

## Capabilities Delivered

1. **LLM Provider Abstraction** — pluggable adapter supporting at minimum Anthropic Claude; adding OpenAI/others is a one-class change.

2. **Single-prompt composer** that ingests all 4 context layers (category, merchant, trigger, optional customer) and outputs:
   - `body` — the WhatsApp message text
   - `cta` — one of the 5 allowed values
   - `rationale` — 1–2 sentence explanation

3. **`/v1/tick` orchestration**:
   - For each trigger in `available_triggers`, look up associated merchant and category from state
   - Skip if merchant context not loaded
   - Call composer
   - Wrap composer output in the full `action` schema (conversation_id, send_as, etc.)
   - Return `actions[]`

4. **Timeout safety**: LLM calls capped at 25s; if exceeded, the trigger is skipped and `actions[]` returns whatever else completed.

5. **Determinism**: `temperature=0` everywhere; same input → same message.

---

## Files / Modules to Implement

```
bot/
├── llm/
│   ├── __init__.py
│   ├── adapter.py              # LLMProvider abstract base
│   ├── anthropic_adapter.py    # Claude implementation (primary)
│   └── openai_adapter.py       # GPT-4o-mini fallback
├── composer/
│   ├── __init__.py
│   ├── composer.py             # compose(category, merchant, trigger, customer?)
│   └── prompts.py              # base prompt template
├── services/
│   └── tick_service.py         # /v1/tick orchestration
└── config.py                   # extended: LLM_PROVIDER, LLM_API_KEY, LLM_MODEL

tests/
├── test_composer.py            # mocked LLM; assert prompt shape + parsing
├── test_tick.py                # /v1/tick with stubbed LLM returns valid actions
└── conftest.py                 # FakeLLMProvider fixture for offline tests

requirements.txt                # add: anthropic, openai (optional)
.env.example                    # LLM_PROVIDER=anthropic, LLM_API_KEY=sk-...
```

### `bot/llm/adapter.py`
```python
from abc import ABC, abstractmethod

class LLMProvider(ABC):
    @abstractmethod
    def complete(self, system: str, user: str,
                 max_tokens: int = 800, temperature: float = 0.0,
                 timeout: int = 25) -> str: ...

    @abstractmethod
    def name(self) -> str: ...
```

### `bot/llm/anthropic_adapter.py` (sketch)
```python
import anthropic

class AnthropicAdapter(LLMProvider):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def complete(self, system, user, max_tokens=800, temperature=0.0, timeout=25):
        resp = self.client.messages.create(
            model=self.model, max_tokens=max_tokens, temperature=temperature,
            system=system, messages=[{"role": "user", "content": user}],
            timeout=timeout,
        )
        return resp.content[0].text

    def name(self) -> str:
        return f"anthropic:{self.model}"
```

### `bot/composer/prompts.py` (sketch)
```python
BASE_SYSTEM = """You are Vera, magicpin's merchant AI assistant. You compose WhatsApp messages for Indian merchants.

RULES:
1. Specificity wins — anchor on a concrete fact (number, date, headline) from the contexts.
2. Single CTA in the last sentence.
3. No URLs in the body (Meta restriction).
4. Hindi-English code-mix is fine if merchant.identity.languages includes "hi".
5. Use the merchant's owner_first_name when available.
6. Never invent data not present in the contexts.

OUTPUT FORMAT — strict JSON only, no commentary:
{
  "body": "<the WhatsApp message text>",
  "cta": "open_ended" | "binary_yes_no" | "binary_confirm_cancel" | "multi_choice_slot" | "none",
  "rationale": "<1-2 sentence explanation of why this message>"
}"""

def build_user_prompt(category: dict, merchant: dict, trigger: dict, customer: dict | None) -> str:
    parts = [
        "=== CATEGORY CONTEXT ===",
        f"Slug: {category.get('slug')}",
        f"Voice: {category.get('voice', {}).get('tone')}",
        f"Offer catalog: {[o['title'] for o in category.get('offer_catalog', [])]}",
        f"Peer stats: {category.get('peer_stats')}",
        f"Top digest items: {category.get('digest', [])[:3]}",
        "",
        "=== MERCHANT CONTEXT ===",
        f"Name: {merchant['identity']['name']}, Owner: {merchant['identity'].get('owner_first_name')}",
        f"Locality: {merchant['identity'].get('locality')}, City: {merchant['identity'].get('city')}",
        f"Languages: {merchant['identity'].get('languages')}",
        f"Performance (30d): {merchant.get('performance')}",
        f"Active offers: {[o['title'] for o in merchant.get('offers', []) if o.get('status')=='active']}",
        f"Signals: {merchant.get('signals')}",
        f"Customer aggregate: {merchant.get('customer_aggregate')}",
        "",
        "=== TRIGGER CONTEXT ===",
        f"Kind: {trigger.get('kind')}, Source: {trigger.get('source')}, Urgency: {trigger.get('urgency')}",
        f"Payload: {trigger.get('payload')}",
        f"Expires: {trigger.get('expires_at')}",
    ]
    if customer:
        parts += [
            "",
            "=== CUSTOMER CONTEXT ===",
            f"Name: {customer['identity'].get('name')}",
            f"Language pref: {customer['identity'].get('language_pref')}",
            f"Relationship: {customer.get('relationship')}",
            f"State: {customer.get('state')}",
            f"Consent scope: {customer.get('consent', {}).get('scope')}",
        ]
    parts.append("\nCompose the next WhatsApp message. Output JSON only.")
    return "\n".join(parts)
```

### `bot/composer/composer.py` (sketch)
```python
import json
import logging
from .prompts import BASE_SYSTEM, build_user_prompt
from ..llm.adapter import LLMProvider

log = logging.getLogger(__name__)

def compose(category: dict, merchant: dict, trigger: dict,
            customer: dict | None, llm: LLMProvider) -> dict | None:
    user_prompt = build_user_prompt(category, merchant, trigger, customer)
    try:
        raw = llm.complete(BASE_SYSTEM, user_prompt, timeout=25)
    except Exception as e:
        log.warning(f"LLM call failed: {e}")
        return None

    # Parse JSON (tolerant of code fences)
    raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        log.warning(f"LLM returned non-JSON: {raw[:200]}")
        return None

    body = parsed.get("body", "").strip()
    cta = parsed.get("cta", "open_ended")
    rationale = parsed.get("rationale", "")
    if not body or len(body) < 10:
        return None

    return {"body": body, "cta": cta, "rationale": rationale}
```

### `bot/services/tick_service.py` (sketch)
```python
from datetime import datetime
from ..composer.composer import compose
from ..state import store

class TickService:
    def __init__(self, llm):
        self.llm = llm

    def handle(self, now: str, available_triggers: list[str]) -> dict:
        actions = []
        for trg_id in available_triggers[:20]:    # cap at 20
            trg = store.contexts.get(("trigger", trg_id))
            if not trg:
                continue
            t_payload = trg.payload
            mid = t_payload.get("merchant_id")
            merchant = store.contexts.get(("merchant", mid))
            if not merchant:
                continue
            cat_slug = merchant.payload.get("category_slug")
            cat = store.contexts.get(("category", cat_slug))
            if not cat:
                continue

            customer = None
            cid = t_payload.get("customer_id")
            if cid:
                cust_stored = store.contexts.get(("customer", cid))
                if cust_stored:
                    customer = cust_stored.payload

            result = compose(cat.payload, merchant.payload, t_payload, customer, self.llm)
            if not result:
                continue

            actions.append({
                "conversation_id": f"conv_{mid}_{trg_id}",
                "merchant_id": mid,
                "customer_id": cid,
                "send_as": "vera" if t_payload.get("scope") == "merchant" else "merchant_on_behalf",
                "trigger_id": trg_id,
                "template_name": f"vera_{t_payload.get('kind')}_v1",
                "template_params": [merchant.payload['identity'].get('owner_first_name', '')],
                "body": result["body"],
                "cta": result["cta"],
                "suppression_key": t_payload.get("suppression_key", ""),
                "rationale": result["rationale"],
            })
        return {"actions": actions}
```

---

## Test Plan

### Unit tests (with `FakeLLMProvider` returning canned JSON)
1. `test_compose_builds_correct_prompt` — fake LLM captures prompt; assert all 4 contexts appear
2. `test_compose_parses_json_response` — fake returns `{"body": "...", "cta": "open_ended", ...}`; result has all fields
3. `test_compose_handles_code_fenced_response` — fake returns ` ```json\n{...}\n``` ` → still parses
4. `test_compose_returns_none_on_invalid_json` — fake returns "not json" → None
5. `test_compose_returns_none_on_empty_body` — fake returns `{"body": "", ...}` → None
6. `test_compose_with_customer_context` — passes customer dict; prompt includes customer fields

### Tick service tests
7. `test_tick_skips_unknown_trigger` — `available_triggers` includes id not in state → skipped
8. `test_tick_skips_when_merchant_missing` — trigger references unknown merchant → skipped
9. `test_tick_returns_full_action_schema` — all required fields present in returned action
10. `test_tick_caps_at_20_actions` — 25 triggers in batch → max 20 in response

### Integration test (requires real LLM API key, opt-in)
11. `test_real_llm_compose_dr_meera` — real Claude call with Dr. Meera + research_digest trigger; output body contains "Meera" and a JIDA-related fact; assert it parses as valid JSON

### Judge-simulator scenario
```bash
TEST_SCENARIO = "phase2_short"
python judge_simulator.py
```
Expected: at least 1 action returned with non-trivial body, scored by the judge.

---

## Expected Output

### Sample — Dr. Meera + research digest trigger
**Input** (after Phase 1's context push):
```json
POST /v1/tick
{ "now": "2026-04-26T10:00:00Z",
  "available_triggers": ["trg_001_research_digest_dentists"] }
```

**Bot response** (typical):
```json
{
  "actions": [
    {
      "conversation_id": "conv_m_001_drmeera_dentist_delhi_trg_001_research_digest_dentists",
      "merchant_id": "m_001_drmeera_dentist_delhi",
      "customer_id": null,
      "send_as": "vera",
      "trigger_id": "trg_001_research_digest_dentists",
      "template_name": "vera_research_digest_v1",
      "template_params": ["Meera"],
      "body": "Dr. Meera, JIDA's Oct issue dropped a 2,100-patient trial showing 3-month fluoride recall cuts caries 38% better than 6-month for high-risk adult patients. Given your 124 high-risk adult cohort, worth a 2-min skim. Want me to pull the abstract + draft a patient WhatsApp?",
      "cta": "binary_yes_no",
      "suppression_key": "research:dentists:2026-W17",
      "rationale": "Research digest with merchant-specific anchor (high-risk adult cohort matches her customer_aggregate); offers reciprocity (pull abstract + draft) for low-friction continuation."
    }
  ]
}
```

This message will not necessarily score perfectly yet — voice-rule fine-tuning, validation, and trigger-kind routing arrive in Phase 3.

---

## Dependencies (prior phases)
- **Phase 1** — needed: state store, all 5 endpoints, Pydantic models. The composer mounts on top of `/v1/tick` and reads from `state.contexts`.

---

## Acceptance / Definition of Done

- [ ] `LLMProvider` interface defined; at least one provider (Anthropic) working
- [ ] `compose()` function returns valid `{body, cta, rationale}` for any 4-context input
- [ ] `/v1/tick` returns well-formed `actions[]` driven by state + LLM
- [ ] `/v1/tick` respects 30s budget; LLM timeout = 25s
- [ ] All 11 tests pass (10 mocked + 1 integration with real key)
- [ ] `judge_simulator.py` with `TEST_SCENARIO="phase2_short"` returns at least one scored action with score > 0
- [ ] No fabrication of merchant data observed in 10 sampled outputs (manual review)
- [ ] `temperature=0` confirmed by re-running same input twice and comparing output (must be byte-identical)

---

## Estimated Effort
~6–8 hours: LLM SDK setup, prompt iteration, parsing edge cases, tick orchestration, tests.
