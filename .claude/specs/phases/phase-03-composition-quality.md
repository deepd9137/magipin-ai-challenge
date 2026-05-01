# Phase 3 — Composition Quality (Voice, Trigger Routing, Validation, Suppression)

## Goal
Lift composition scores from "valid output" (Phase 2) to **consistent 35+/50 average across all 5 dimensions** (specificity, category fit, merchant fit, trigger relevance, engagement compulsion). This is the phase that makes Vera **good**, not just functional.

---

## Why this phase next
Phase 2 produced a generic single-prompt composer. The judge will mark it down for:
- Wrong tone in clinical categories (dentists getting promo voice)
- Generic framing for triggers that need specific shapes (research_digest needs a citation; perf_dip needs diagnosis + reframe)
- Fabricated numbers slipping through
- Same trigger firing twice (no suppression)
- Taboo words appearing in messages

This phase systematically addresses each scoring lever identified in `examples/case-studies.md` and the rubric in the spec.

---

## Capabilities Delivered

1. **Per-category voice packs** — dentists get clinical-peer voice; gyms get coach voice; restaurants get operator voice; salons get warm-practical; pharmacies get trust-precise.

2. **Per-trigger-kind framing** — different prompt templates for `research_digest`, `perf_dip`, `recall_due`, `festival_upcoming`, `regulation_change`, `curious_ask_due`, `renewal_due`, `customer_lapsed_*`, etc.

3. **Validation pipeline** with 6 checks:
   - Body length (10–800 chars)
   - No URLs
   - No taboo vocabulary (per category)
   - CTA shape valid
   - Anti-fabrication (extracted facts must appear in input contexts)
   - No verbatim repetition vs prior bot turns in same conversation

4. **One-shot retry on validation failure** — if validator rejects, re-prompt LLM with explicit list of failures; if second attempt also fails, skip the trigger (return no action).

5. **Suppression key tracking** — once a `suppression_key` is fired, the trigger is skipped on subsequent ticks regardless of how many times the judge re-pushes.

6. **Trigger expiry handling** — if `trigger.expires_at < now`, skip without LLM call.

7. **Restraint** — return `{"actions": []}` when no triggers are worth firing rather than spamming.

---

## Files / Modules to Implement

```
bot/
├── composer/
│   ├── voice.py                # VOICE_PACKS dict: category_slug → voice instructions
│   ├── triggers.py             # TRIGGER_FRAMINGS dict: trigger.kind → guidance text
│   └── composer.py             # extended: select voice + framing, retry on validation fail
├── validation/
│   ├── __init__.py
│   └── validators.py           # 6-check validation pipeline; returns list of failure reasons
├── suppression.py              # SuppressionTracker (wrapper around state.suppressed_keys)
└── services/
    └── tick_service.py         # extended: expiry check, suppression check, retry logic

tests/
├── test_voice.py               # voice pack lookup; taboo checks
├── test_triggers.py            # trigger-kind routing
├── test_validators.py          # 6 validators × pass/fail cases
├── test_suppression.py         # mark + skip behavior
└── test_tick_quality.py        # integration: each trigger kind produces correctly-framed output
```

### `bot/composer/voice.py`
```python
VOICE_PACKS = {
    "dentists": {
        "tone": "peer_clinical",
        "salutation": "Dr. {first_name}",
        "register": "respectful_collegial",
        "vocab_taboo": ["guaranteed", "100% safe", "completely cure", "miracle", "best in city"],
        "voice_instructions": (
            "Use clinical vocabulary (fluoride varnish, caries, scaling) when relevant. "
            "Cite sources for any research claims. Never make medical guarantees. "
            "Address as 'Dr. {first_name}'. Peer-to-peer, not promotional."
        ),
    },
    "salons": {
        "tone": "warm_practical",
        "salutation": "{first_name}",
        "vocab_taboo": ["amazing", "best deal ever", "limited time only"],
        "voice_instructions": (
            "Warm but not gushing. Operator-to-operator. Service+price phrasing "
            "(Haircut @ ₹99) outperforms generic discounts. Emoji sparingly OK."
        ),
    },
    "restaurants": {
        "tone": "operator_to_operator",
        "salutation": "{first_name}",
        "vocab_taboo": ["delicious", "mouth-watering", "best food"],
        "voice_instructions": (
            "Talk like a fellow operator: covers, AOV, delivery radius, prep time. "
            "Acknowledge local match-day, festivals, weather impact on covers."
        ),
    },
    "gyms": {
        "tone": "coach_motivational",
        "salutation": "{first_name}",
        "vocab_taboo": ["fat-burning miracle", "guaranteed weight loss"],
        "voice_instructions": (
            "Coach voice. Use 'members', 'retention', 'attendance', 'class capacity'. "
            "Evidence-based; acknowledge seasonal acquisition cycles."
        ),
    },
    "pharmacies": {
        "tone": "trustworthy_precise",
        "salutation": "{first_name}",
        "vocab_taboo": ["miracle drug", "guaranteed cure", "100% effective"],
        "voice_instructions": (
            "Trustworthy and precise. Use generic + brand names correctly. "
            "Compliance-aware. Senior-citizen norms for elderly customers."
        ),
    },
}

def get_voice(category_slug: str) -> dict:
    return VOICE_PACKS.get(category_slug, VOICE_PACKS["restaurants"])  # safe default
```

### `bot/composer/triggers.py`
```python
TRIGGER_FRAMINGS = {
    "research_digest": (
        "Lead with the most-relevant single research item. Cite source + page/issue. "
        "Anchor on a merchant-specific signal (their customer_aggregate or signals list) "
        "explaining WHY this study matters to THIS merchant. Offer to pull the abstract "
        "or draft a patient/customer-ed message they can reshare."
    ),
    "regulation_change": (
        "Lead with the deadline date and what changes. Cite the issuing body. "
        "Estimate impact on this merchant (do they have the equipment/practice affected?). "
        "Offer to check or help comply."
    ),
    "perf_dip": (
        "Diagnose, then reframe. State the dip with exact numbers, then contextualize "
        "(seasonal? peer-wide? merchant-specific?). Propose ONE concrete next step."
    ),
    "perf_spike": (
        "Acknowledge the win with specifics. Suggest one capture-the-moment action "
        "(post on GBP, capture lead, share testimonial)."
    ),
    "recall_due": (
        "CUSTOMER-FACING. Lead with timing ('It's been X months'). Offer 2 specific slots "
        "honoring their preferences. State the price + any free-add. Multi-choice slot CTA OK."
    ),
    "renewal_due": (
        "Show value delivered in the renewing period (concrete numbers). State price + "
        "what changes if they don't renew. Single binary CTA."
    ),
    "festival_upcoming": (
        "Category-specific hook. Salons: bridal/festive looks. Restaurants: festival menu. "
        "Pharmacies: festival-related stock. Lead with days-until + a concrete drafted artifact."
    ),
    "curious_ask_due": (
        "Ask the merchant a specific question (Cialdini 'asking the merchant' lever). "
        "Frame around what's unique to their week. Offer reciprocity for their answer "
        "(I'll turn it into a Google post + reply template)."
    ),
    "customer_lapsed_soft": (
        "CUSTOMER-FACING. Warm, no-shame. Reference their past relationship "
        "(services received, time since last visit). Specific new offering relevant to past goals. "
        "No-commitment CTA."
    ),
    "customer_lapsed_hard": (
        "CUSTOMER-FACING. Same as soft but stronger no-commitment framing; offer free trial "
        "or risk-reversal. Single binary CTA."
    ),
    "competitor_opened": (
        "Acknowledge calmly. Pull peer benchmarks for their locality. Suggest one "
        "differentiation play (review depth, response time, niche service)."
    ),
    "review_theme_emerged": (
        "Surface the theme with a quote count. Offer to draft a response template + "
        "an operational change suggestion."
    ),
    "milestone_reached": (
        "Celebrate concretely (the milestone number). Suggest converting it into a "
        "social-proof artifact (testimonial post, GBP update)."
    ),
    "seasonal_perf_dip": (
        "Pre-empt anxiety: this is normal. Cite peer-wide seasonal pattern. "
        "Reframe to retention-focus action."
    ),
}

def get_framing(trigger_kind: str) -> str:
    return TRIGGER_FRAMINGS.get(trigger_kind, "Compose a relevant message based on the trigger.")
```

### `bot/validation/validators.py`
```python
import re
from typing import NamedTuple

class ValidationResult(NamedTuple):
    valid: bool
    failures: list[str]    # human-readable reasons

def validate(body: str, cta: str, category: dict, merchant: dict, trigger: dict,
             customer: dict | None, prior_bot_bodies: list[str]) -> ValidationResult:
    failures = []

    # 1. Length
    if not body or len(body) < 10:
        failures.append("body_too_short")
    if len(body) > 800:
        failures.append("body_too_long")

    # 2. No URLs
    if re.search(r"https?://|www\.|\.com/|bit\.ly|tinyurl", body, re.I):
        failures.append("contains_url")

    # 3. No taboo vocab
    taboos = category.get("voice", {}).get("vocab_taboo", [])
    for taboo in taboos:
        if taboo.lower() in body.lower():
            failures.append(f"taboo_word:{taboo}")

    # 4. CTA shape
    valid_ctas = {"open_ended", "binary_yes_no", "binary_confirm_cancel",
                  "multi_choice_slot", "none"}
    if cta not in valid_ctas:
        failures.append(f"invalid_cta:{cta}")

    # 5. Anti-fabrication
    fab = check_fabrication(body, category, merchant, trigger, customer)
    failures.extend(fab)

    # 6. No repetition
    norm_body = re.sub(r"\s+", " ", body).strip().lower()
    for prior in prior_bot_bodies:
        prior_norm = re.sub(r"\s+", " ", prior).strip().lower()
        if norm_body == prior_norm:
            failures.append("verbatim_repetition")
            break

    return ValidationResult(valid=(len(failures) == 0), failures=failures)


def check_fabrication(body: str, category: dict, merchant: dict, trigger: dict,
                      customer: dict | None) -> list[str]:
    """Each number/percentage/proper-noun in body must appear in flattened context."""
    flat = " ".join([
        json.dumps(category), json.dumps(merchant), json.dumps(trigger),
        json.dumps(customer or {}),
    ]).lower()
    failures = []

    # Extract numbers (preserving %)
    nums = re.findall(r"\b\d+\.?\d*%?\b", body)
    for n in nums:
        if len(n) <= 1:    # skip "1", "2" — too noisy
            continue
        if n.lower() not in flat:
            # Allow common counts: "3 months", "5 minutes" — small numbers without context
            failures.append(f"unverified_number:{n}")

    # Cap fabrication failures: max 2 reported (allow some leniency)
    return failures[:2]
```

### `bot/composer/composer.py` (extended)
```python
def compose(category, merchant, trigger, customer, llm,
            prior_bot_bodies: list[str] = None) -> dict | None:
    prior_bot_bodies = prior_bot_bodies or []

    voice = get_voice(category.get("slug", ""))
    framing = get_framing(trigger.get("kind", ""))

    system = build_system_prompt(voice, framing)

    for attempt in range(2):
        user = build_user_prompt(category, merchant, trigger, customer)
        if attempt == 1:
            user += f"\n\nPREVIOUS ATTEMPT FAILED VALIDATION: {prev_failures}\nFix these issues."

        try:
            raw = llm.complete(system, user, timeout=25)
        except Exception as e:
            log.warning(f"LLM error attempt {attempt}: {e}")
            return None

        parsed = parse_json(raw)
        if not parsed:
            return None

        result = ValidationResult.from_dict(parsed)
        validation = validate(parsed["body"], parsed["cta"], category, merchant,
                              trigger, customer, prior_bot_bodies)

        if validation.valid:
            return parsed
        prev_failures = validation.failures
        log.info(f"validation failed (attempt {attempt}): {validation.failures}")

    return None    # both attempts failed
```

### `bot/suppression.py`
```python
class SuppressionTracker:
    def __init__(self, store):
        self.store = store

    def is_suppressed(self, key: str) -> bool:
        return key in self.store.suppressed_keys

    def mark_fired(self, key: str):
        if key:
            self.store.suppressed_keys.add(key)
```

---

## Test Plan

### Unit tests
1. `test_voice_pack_dentists` — returns peer_clinical with correct taboos
2. `test_voice_pack_unknown_category` — returns safe default
3. `test_trigger_framing_research_digest` — returns citation guidance
4. `test_validators_rejects_url` — body with `https://` → failures contains contains_url
5. `test_validators_rejects_taboo` — body with "guaranteed" + dentists category → fails
6. `test_validators_accepts_clean` — Case Study 1 body → no failures
7. `test_validators_anti_fabrication_unknown_number` — body says "5,000 patients" but contexts don't → failure
8. `test_validators_anti_fabrication_known_number` — body says "2,100" and trigger payload says "trial_n: 2100" → no failure
9. `test_validators_repetition_detection` — body in prior_bot_bodies → fails
10. `test_suppression_marks_and_skips` — fire key, then check is_suppressed → True
11. `test_compose_retries_on_validation_failure` — fake LLM returns bad output first, good second → returns good
12. `test_compose_skips_after_two_failures` — fake LLM returns bad twice → returns None

### Integration tests
13. `test_tick_suppresses_repeated_trigger` — call /v1/tick with same trigger twice; second call has no actions
14. `test_tick_skips_expired_trigger` — trigger with expires_at in past → not in actions
15. `test_each_trigger_kind_produces_correct_framing` — for each of 14 trigger kinds, sample output and assert the framing keywords appear (e.g., research_digest output contains a source citation)

### Quality benchmark (manual + judge)
16. Run `judge_simulator.py` with `TEST_SCENARIO="full_evaluation"` → average score across all messages must be ≥ 35/50

---

## Expected Output

### Sample 1 — Dr. Meera + research_digest (now with proper framing)
**Output**:
```
Dr. Meera, JIDA's Oct issue (p.14) — 2,100-patient Indian trial: 3-month 
fluoride recall outperformed 6-month by 38% caries reduction in high-risk 
adults. With 124 high-risk adult patients in your Lajpat Nagar roster, this 
is the cohort it directly applies to. Want me to pull the 2-min abstract + 
draft a patient-ed WhatsApp you can reshare?
```
- Specificity: ✅ (38%, 2100, page 14, 124 patients)
- Category fit: ✅ (clinical voice, "Dr.", source citation)
- Merchant fit: ✅ (Lajpat Nagar, her cohort count)
- Trigger relevance: ✅ (lead with the digest item)
- Engagement compulsion: ✅ (reciprocity + low-friction CTA)

### Sample 2 — Bharat Dental + perf_dip
**Output**:
```
Dr. Bharat, your calls dropped 50% week-on-week (12 → 4). Two likely causes: 
your subscription expires in 12 days (some merchants pause posts in this 
window) AND your GBP is unverified — both depress visibility. Single highest-
ROI fix: verify GBP this week. Want me to send the 4-step verification guide?
```

### Sample 3 — Suppression in action
First tick: action returned for `trg_001_research_digest_dentists` ✅
Second tick (same trigger pushed again): `actions: []` — suppression_key already fired.

### Sample 4 — Validation rejection (logged)
LLM first attempt: `"...100% guaranteed reduction..."` (taboo for dentists)
Validator failures: `["taboo_word:100% safe", "taboo_word:guaranteed"]`
Retry attempt 2: clean output → returned.

---

## Dependencies (prior phases)
- **Phase 1** — state store, Pydantic models
- **Phase 2** — LLM adapter, base composer, tick service stub

---

## Acceptance / Definition of Done

- [ ] Voice packs implemented for all 5 categories
- [ ] Trigger framings cover at least 14 trigger kinds (those in `dataset/triggers_seed.json`)
- [ ] All 6 validation checks implemented and unit-tested
- [ ] Composer retries once on validation failure with explicit feedback
- [ ] Suppression tracker integrated into `/v1/tick`
- [ ] Expired triggers are skipped before LLM call
- [ ] All 16 tests pass
- [ ] `judge_simulator.py full_evaluation` average score ≥ 35/50
- [ ] No URL appears in any sampled message body across 30+ test compositions
- [ ] No taboo word appears in any sampled message body across 30+ test compositions
- [ ] Anti-fabrication catches at least 90% of injected fake numbers in red-team test

---

## Estimated Effort
~10–14 hours: voice/framing tuning is iterative; anti-fabrication is the trickiest validator; quality benchmarking takes multiple runs.
