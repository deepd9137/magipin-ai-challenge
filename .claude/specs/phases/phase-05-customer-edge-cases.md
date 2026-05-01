# Phase 5 — Customer-Facing Flows & Edge Cases

## Goal
Round out the bot to handle (a) **customer-facing messages** sent on the merchant's behalf and (b) the cluster of **edge cases** that distinguish a complete implementation from a happy-path one — consent enforcement, mid-test context updates, expiry, suppression collisions, missing data, and language preference handling.

---

## Why this phase next
Phase 4 made the bot conversationally smart for merchant-facing flows. But:
- 5 of the 30 test pairs are **customer-facing** (`recall_due`, `customer_lapsed_*`, `wedding_package_followup`, `chronic_refill_due`, `bridal_followup`)
- The judge **mid-test injects** new context versions and expects the bot to incorporate them
- The judge tests **consent boundaries** — sending a recall reminder to an un-consented customer is a hard fail
- Real merchant data has missing fields; the bot must degrade gracefully instead of crashing

These cases combine into "operational completeness" — without them, the bot looks great in the happy path but loses ~15 points on edge-case exercises.

---

## Capabilities Delivered

1. **Customer-facing composition path** — when `trigger.scope == "customer"`:
   - `send_as = "merchant_on_behalf"`
   - Voice shifts: instead of Vera-talks-to-merchant, the message is **drafted by Vera but sent from merchant's WhatsApp number** to the customer
   - Customer's `language_pref` overrides merchant's languages list
   - Reference the relationship state (`first_visit`, `last_visit`, `services_received`)

2. **Consent enforcement** — for customer-scoped triggers, check `customer.consent.scope` includes the trigger kind:
   - `recall_due` requires `recall_reminders` in scope
   - `appointment_tomorrow` requires `appointment_reminders`
   - `chronic_refill_due` requires `medication_reminders`
   - If consent missing → skip (no action), log `consent_missing`

3. **Mid-test context update handling** — when judge pushes a new version of category/merchant context during the test:
   - Atomic replace (already in Phase 1)
   - Subsequent compositions use the new version
   - Verified via composition referencing newly-pushed digest items

4. **Trigger expiry guard** — `if trigger.expires_at < now`, skip without LLM call (already partial in Phase 3, here it's hardened).

5. **Missing-data graceful degradation**:
   - Missing `owner_first_name` → use generic salutation appropriate for category
   - Missing `customer_aggregate` → omit cohort references in composition
   - Missing `voice` block → use safe default voice pack
   - Missing `digest` → fall back to merchant-state-driven framing

6. **Language preference resolution**:
   - Merchant-facing: use `merchant.identity.languages`
   - Customer-facing: use `customer.identity.language_pref` (overrides merchant)
   - Hindi-English code-mix when `"hi"` is present
   - English-only otherwise

7. **Customer-facing CTA shapes**:
   - Booking flows: `multi_choice_slot` is acceptable (e.g., "Reply 1 for Wed, 2 for Thu")
   - Recall reminders: `binary_yes_no` or `multi_choice_slot`
   - Win-back campaigns: `binary_yes_no` with no-commitment framing

8. **Per-customer suppression** — if a customer-facing trigger fires for `c_001`, future identical triggers for `c_001` are suppressed (suppression_key is per-trigger and pre-includes customer_id).

---

## Files / Modules to Implement

```
bot/
├── composer/
│   ├── customer_composer.py       # specialized customer-facing composition
│   ├── voice.py                   # extended: customer-facing voice variants
│   └── triggers.py                # extended: customer-trigger framings
├── consent.py                     # consent check helper
├── language.py                    # resolve_language(merchant, customer) → "en" | "hi-en"
└── services/
    └── tick_service.py            # extended: customer scope routing + consent gate

tests/
├── test_customer_composer.py      # customer-facing composition for each customer trigger
├── test_consent_enforcement.py    # missing consent → skip
├── test_language_resolution.py    # merchant vs customer language pref
├── test_missing_data_resilience.py # missing fields → degraded but valid output
├── test_mid_test_context_update.py # version bump → next compose uses new version
└── test_edge_cases.py             # expired triggers, missing merchants, suppression collisions
```

### `bot/consent.py`
```python
TRIGGER_KIND_TO_CONSENT_SCOPE = {
    "recall_due": "recall_reminders",
    "appointment_tomorrow": "appointment_reminders",
    "appointment_reminder": "appointment_reminders",
    "chronic_refill_due": "medication_reminders",
    "wedding_package_followup": "marketing_outreach",
    "bridal_followup": "marketing_outreach",
    "customer_lapsed_soft": "marketing_outreach",
    "customer_lapsed_hard": "marketing_outreach",
    "promotional_campaign": "promotional_outreach",
}

def has_consent(customer: dict, trigger_kind: str) -> bool:
    if not customer:
        return True    # merchant-facing trigger; customer not relevant
    required = TRIGGER_KIND_TO_CONSENT_SCOPE.get(trigger_kind)
    if not required:
        # no specific consent requirement; default allow if customer is opted in at all
        return bool(customer.get("consent", {}).get("scope"))
    return required in customer.get("consent", {}).get("scope", [])
```

### `bot/language.py`
```python
def resolve_language(merchant: dict, customer: dict | None = None) -> str:
    """Return one of: 'en', 'hi-en' (code-mix), 'multi'."""
    # Customer overrides merchant when customer-facing
    if customer:
        pref = customer.get("identity", {}).get("language_pref", "")
        if "hi" in pref.lower():
            return "hi-en"
        return "en"
    langs = merchant.get("identity", {}).get("languages", ["en"])
    if "hi" in langs:
        return "hi-en"
    return "en"
```

### `bot/composer/customer_composer.py` (sketch)
```python
def compose_customer_facing(category: dict, merchant: dict, trigger: dict,
                            customer: dict, llm) -> dict | None:
    """Variant of compose() with customer-facing voice rules."""
    voice = get_customer_voice(category.get("slug", ""))
    framing = get_framing(trigger.get("kind", ""))
    language = resolve_language(merchant, customer)

    system = build_customer_system(voice, framing, language)
    user = build_customer_prompt(category, merchant, trigger, customer)

    # Same retry/validation pattern as Phase 3 composer
    ...
    # On success, set:
    result["send_as"] = "merchant_on_behalf"
    return result
```

### Updated `bot/services/tick_service.py` (additions)
```python
from ..consent import has_consent
from .. import logging_utils

class TickService:
    def handle(self, now, available_triggers):
        actions = []
        for trg_id in available_triggers[:20]:
            trg = store.contexts.get(("trigger", trg_id))
            if not trg:
                logging_utils.log_skip(trg_id, "trigger_not_loaded")
                continue
            t_payload = trg.payload

            # Expiry check (hardened)
            if self._is_expired(t_payload, now):
                logging_utils.log_skip(trg_id, "expired")
                continue

            # Suppression check
            sk = t_payload.get("suppression_key", "")
            if sk and sk in store.suppressed_keys:
                logging_utils.log_skip(trg_id, "suppressed")
                continue

            # Resolve merchant + category (with graceful degradation)
            merchant = self._resolve_merchant(t_payload.get("merchant_id"))
            if not merchant:
                logging_utils.log_skip(trg_id, "merchant_missing")
                continue
            category = self._resolve_category(merchant.get("category_slug"))
            if not category:
                logging_utils.log_skip(trg_id, "category_missing")
                continue

            customer = None
            if t_payload.get("scope") == "customer":
                customer = self._resolve_customer(t_payload.get("customer_id"))
                if not customer:
                    logging_utils.log_skip(trg_id, "customer_missing")
                    continue
                if not has_consent(customer, t_payload.get("kind", "")):
                    logging_utils.log_skip(trg_id, "consent_missing")
                    continue

            # Route to merchant- or customer-facing composer
            if customer:
                result = compose_customer_facing(category, merchant, t_payload, customer, self.llm)
            else:
                result = compose(category, merchant, t_payload, customer=None, llm=self.llm)

            if not result:
                continue

            actions.append(self._build_action(merchant, customer, t_payload, result))
            if sk:
                store.suppressed_keys.add(sk)

        return {"actions": actions}
```

---

## Test Plan

### Customer-facing composition tests
1. `test_recall_due_priya` — full Priya context + recall_due trigger → output contains her name, slot times, ₹299 price; `send_as=merchant_on_behalf`
2. `test_customer_lapsed_winback` — Rashmi (gym) + lapsed_hard trigger → output has no-shame framing, references past goal (weight loss)
3. `test_chronic_refill_senior` — Mr. Sharma + refill trigger → namaste salutation, molecule names, family-channel framing
4. `test_bridal_followup` — Kavya + wedding trigger → references trial completed, days-to-wedding
5. `test_wedding_followup_long_lead` — wedding 196 days away → message acknowledges runway

### Consent enforcement tests
6. `test_consent_missing_skips_recall` — customer.consent.scope = ["appointment_reminders"], trigger = recall_due → no action
7. `test_consent_present_allows_recall` — scope includes "recall_reminders" → action returned
8. `test_consent_no_customer_no_block` — merchant-facing trigger doesn't trigger consent check

### Language resolution tests
9. `test_lang_hi_in_merchant` — merchant.languages=[en, hi] → resolve to "hi-en"
10. `test_lang_customer_overrides_merchant` — merchant en-only, customer pref="hi-en mix" → "hi-en"
11. `test_lang_hi_en_message_contains_devanagari_or_romanized` — output for hi-en pref has Hindi tokens

### Missing-data resilience tests
12. `test_missing_owner_first_name` — merchant with no owner_first_name → uses generic salutation, doesn't crash
13. `test_missing_customer_aggregate` — merchant without customer_aggregate → output doesn't reference cohort counts
14. `test_missing_voice_block` — category without voice → uses default voice pack
15. `test_partial_voice_block` — voice has tone but no taboo list → no taboo failures (empty list default)

### Mid-test context update tests
16. `test_version_bump_replaces_atomically` — push v1, push v2 with different digest; next composition references v2 digest
17. `test_mid_conversation_context_update` — start conversation with v1, push v2 mid-flight; next reply uses v2

### Edge case tests
18. `test_expired_trigger_skipped` — trigger with expires_at in past → no action, logged as expired
19. `test_suppression_per_customer` — same trigger kind for two different customers → both fire (different suppression keys)
20. `test_unknown_merchant_in_trigger` — trigger references merchant not in store → skip, no crash
21. `test_malformed_payload_safe` — missing required fields in trigger payload → degraded composition or skip

### Integration test
22. `test_full_evaluation_with_customer_triggers` — all 5 customer-facing test pairs produce valid actions

---

## Expected Output

### Sample 1 — Priya recall (customer-facing)
**Trigger payload**:
```json
{
  "kind": "recall_due", "scope": "customer",
  "payload": {"service_due": "6_month_cleaning",
              "available_slots": [{"label": "Wed 5 Nov, 6pm"}, {"label": "Thu 6 Nov, 5pm"}]}
}
```

**Bot output**:
```json
{
  "merchant_id": "m_001_drmeera_dentist_delhi",
  "customer_id": "c_001_priya_for_m001",
  "send_as": "merchant_on_behalf",
  "body": "Hi Priya, Dr. Meera's clinic here 🦷 It's been 5 months since your last visit — your 6-month cleaning recall is due. Apke liye 2 slots ready hain: Wed 5 Nov, 6pm ya Thu 6 Nov, 5pm. ₹299 cleaning + complimentary fluoride. Reply 1 for Wed, 2 for Thu, or tell us a time that works.",
  "cta": "multi_choice_slot",
  "suppression_key": "recall:c_001_priya_for_m001:6mo",
  "rationale": "Customer-facing recall via merchant_on_behalf; honors hi-en mix pref + weekday-evening preference; multi-choice slot CTA appropriate for booking."
}
```

### Sample 2 — Consent missing (no action)
**Trigger**: `recall_due` for customer with consent scope = `["promotional_outreach"]`
**Bot output**:
```json
{ "actions": [] }
```
**Log**:
```json
{"event": "tick_skip_reason", "trigger_id": "trg_xxx", "reason": "consent_missing",
 "details": "trigger_kind=recall_due requires recall_reminders consent"}
```

### Sample 3 — Mid-test context update
- Tick 1: Compose for `research_digest` references "JIDA Oct 2026 p.14" (digest v1)
- Judge pushes category v2 with new digest item ("DCI radiograph dose limits")
- Tick 2: Compose for `regulation_change` references "DCI 1.5→1.0 mSv per IOPA" (from v2)

### Sample 4 — Expired trigger
**Trigger**: `expires_at: "2026-04-25T00:00:00Z"` (yesterday)
**Tick now**: `2026-04-26T10:00:00Z`
**Bot output**: `{ "actions": [] }` (trigger skipped, logged as expired, no LLM call made)

### Sample 5 — Missing owner_first_name (graceful)
**Merchant**: name="ABC Clinic", no `owner_first_name`
**Bot output**: Body uses "Hi team at ABC Clinic" or category-default opener instead of "Dr. None"

---

## Dependencies (prior phases)
- **Phase 1** — state store with all 4 scope types
- **Phase 2** — composer base
- **Phase 3** — voice packs, validators, suppression tracker
- **Phase 4** — reply handler (for cross-flow consistency)

---

## Acceptance / Definition of Done

- [ ] All 5 customer-facing trigger kinds compose correctly with `send_as=merchant_on_behalf`
- [ ] Consent gate skips triggers when `customer.consent.scope` lacks the required entry
- [ ] Language resolution returns correct mode for all combinations (merchant-only, customer-only, both, neither)
- [ ] Missing optional fields don't crash the bot — degraded but valid output
- [ ] Mid-test version bumps are reflected in subsequent compositions (verified by changing digest mid-test)
- [ ] Expired triggers don't trigger LLM calls
- [ ] Suppression keys are per-customer for customer-scoped triggers (different customers fire independently)
- [ ] All 22 tests pass
- [ ] All Phase 4 tests still pass (no regressions)
- [ ] `judge_simulator.py full_evaluation` average score ≥ 38/50 (up from Phase 3's 35)

---

## Estimated Effort
~8–10 hours: customer composer is largely a variant of Phase 3 work; consent + edge case tests are quick; mid-test update test requires careful state-replay setup.
