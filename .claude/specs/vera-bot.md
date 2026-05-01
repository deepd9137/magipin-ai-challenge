# Spec: Vera — magicpin Merchant AI Assistant Bot

## Overview

Build **Vera**, an AI-powered WhatsApp chatbot that engages Indian merchants on behalf of magicpin. The bot is exposed as an **HTTP server** that receives context data (category, merchant, customer, trigger) from a judge harness, then proactively composes and sends personalised WhatsApp messages to merchants and their customers.

The bot must operate across 5 merchant verticals (dentists, salons, restaurants, gyms, pharmacies), adapt to 20+ trigger types, and handle multi-turn conversations including auto-reply detection, intent transitions, and graceful exits.

---

## Problem Statement

magicpin's production Vera bot suffers from four known failure modes:
1. **Auto-reply pollution** — burns 2–3 turns per merchant before detecting canned WhatsApp Business auto-replies.
2. **Intent-handoff failures** — asks qualifying questions even after a merchant signals clear intent to act.
3. **Generic copy** — discount-style offers ("10% off") instead of specific service+price anchors ("Haircut @ ₹99").
4. **Low engagement frequency** — only sends functional nudges (renewals, profile reminders) instead of curiosity- and knowledge-driven conversations.

The challenge is to rebuild Vera better across all four dimensions.

---

## Dependencies

### Runtime
- Python 3.11+
- `fastapi` — HTTP server framework
- `uvicorn` — ASGI server
- At least one LLM SDK: `anthropic`, `openai`, `google-generativeai`, `deepseek`, or `groq`

### Development / Testing
- `judge_simulator.py` — local harness that runs all test scenarios against your bot
- Dataset JSONs in `dataset/` — seed data for all 5 contexts

### External Services
- One LLM API (Claude / GPT / Gemini / DeepSeek / Groq / Ollama) for message composition

---

## Functional Requirements

### FR-1: Context Ingestion (`POST /v1/context`)

The bot must accept and store four types of context pushed by the judge:

| Scope | What it contains |
|---|---|
| `category` | Voice profile, offer catalog, peer stats, research digest, seasonal beats, trend signals |
| `merchant` | Identity, subscription, performance (30d + 7d delta), offers, conversation history, signals |
| `customer` | Identity, relationship history, lapsed state, language preference, consent scope |
| `trigger` | Event kind, merchant/customer reference, urgency (1–5), suppression key, expiry |

- Contexts are versioned. A higher `version` for the same `(scope, context_id)` must atomically replace the prior version.
- Re-posting the same `(scope, context_id, version)` must be a no-op (idempotent).
- All contexts must persist in memory for the entire test session.

### FR-2: Proactive Message Composition (`POST /v1/tick`)

When the judge calls `/v1/tick`, the bot must:
1. Inspect currently stored triggers in `available_triggers`.
2. For each actionable trigger, look up the associated merchant context and category context.
3. Call an LLM to compose a personalised WhatsApp message using all 4 context layers.
4. Return an `actions[]` array. Returning an empty array is valid (restraint is rewarded).

Each action must include:
- `conversation_id` — unique identifier for this conversation thread
- `merchant_id`, `customer_id` (null if merchant-facing)
- `send_as` — `"vera"` (merchant-facing) or `"merchant_on_behalf"` (customer-facing)
- `trigger_id`
- `template_name` + `template_params` — WhatsApp-style template structure
- `body` — the full message text
- `cta` — `"open_ended"`, `"binary_yes_no"`, `"binary_confirm_cancel"`, `"multi_choice_slot"`, or `"none"`
- `suppression_key` — copied from the trigger; used for deduplication
- `rationale` — concise explanation of why this message was sent

### FR-3: Multi-Turn Conversation Handling (`POST /v1/reply`)

When the judge sends a merchant or customer reply, the bot must respond synchronously with one of:

| Response action | When to use |
|---|---|
| `send` | Merchant engaged; continue the conversation with next message |
| `wait` | Auto-reply detected or merchant asked for time; include `wait_seconds` |
| `end` | Merchant opted out, hostile, or conversation completed |

### FR-4: Auto-Reply Detection

Detect canned WhatsApp Business auto-replies. Signals:
- Message contains phrases like "Thank you for contacting", "Our team will respond shortly", "automated assistant"
- Same message body repeated across multiple turns

Correct behaviour:
- **Turn 1** auto-reply → send one explicit prompt ("Looks like an auto-reply — when the owner sees this, just reply YES")
- **Turn 2** same auto-reply → `wait` for 4–24 hours
- **Turn 3** same auto-reply again → `end` the conversation

### FR-5: Intent Transition Handling

When a merchant signals clear commitment ("Ok let's do it", "Yes please", "Go ahead"), the bot must:
- Switch from qualification mode to **action mode immediately**
- Stop asking qualifying questions
- Confirm the next concrete step with a scope-bounded CTA

### FR-6: Message Composition Rules

All composed messages must follow:
1. **Specificity** — anchor on a real, verifiable fact from the contexts (number, date, headline, source citation). No generic copy.
2. **Voice match** — use the category's tone profile. Dentists = peer/clinical; gyms = coach/motivational; restaurants = operator-to-operator; salons = warm/practical; pharmacies = trustworthy/precise.
3. **Merchant personalisation** — use owner first name, reference their actual signals and numbers.
4. **Trigger relevance** — message must communicate *why now* based on the specific trigger.
5. **Single primary CTA** — one clear next step at the end of the message.
6. **Language match** — honor `identity.languages`. Use Hindi-English code-mix for merchants with `"hi"` in languages.
7. **No fabrication** — only cite data present in the pushed contexts.
8. **Restraint** — if a trigger isn't worth acting on, return `{"actions": []}`.

### FR-7: Customer-Facing Messages

When `trigger.scope == "customer"`, the bot must:
- Set `send_as = "merchant_on_behalf"` (message appears to come from the merchant's WhatsApp number)
- Address the customer by name and honor their language preference
- Respect consent scope (only send recall_reminders if opted in for recall_reminders)
- For booking flows, a multi-choice CTA (e.g., "Reply 1 for Wed, 2 for Thu") is acceptable

### FR-8: Liveness and Identity Endpoints

- `GET /v1/healthz` — must always return 200 with `contexts_loaded` counts by scope
- `GET /v1/metadata` — must return team name, model used, approach, version

---

## Non-Functional Requirements

| Requirement | Value |
|---|---|
| Response time — `/v1/tick` | ≤ 30 seconds |
| Response time — `/v1/reply` | ≤ 30 seconds |
| Response time — `/v1/healthz` | ≤ 2 seconds |
| Response time — `/v1/context` | ≤ 5 seconds |
| LLM temperature | 0 (deterministic output) |
| Max actions per tick | 20 |
| Context payload size | ≤ 500 KB |
| Uptime during test | No restarts; 3 consecutive healthz failures = disqualification |
| State persistence | In-memory is acceptable; must survive full 60-minute test window |

---

## API / Interfaces

### `GET /v1/healthz`
```json
// Response 200
{
  "status": "ok",
  "uptime_seconds": 3600,
  "contexts_loaded": { "category": 5, "merchant": 50, "customer": 200, "trigger": 100 }
}
```

### `GET /v1/metadata`
```json
// Response 200
{
  "team_name": "string",
  "team_members": ["string"],
  "model": "string",
  "approach": "string",
  "contact_email": "string",
  "version": "string",
  "submitted_at": "ISO8601"
}
```

### `POST /v1/context`
```json
// Request
{
  "scope": "category" | "merchant" | "customer" | "trigger",
  "context_id": "string",
  "version": 1,
  "payload": { ... },
  "delivered_at": "ISO8601"
}

// Response 200 — accepted
{ "accepted": true, "ack_id": "string", "stored_at": "ISO8601" }

// Response 409 — stale version
{ "accepted": false, "reason": "stale_version", "current_version": 5 }

// Response 400 — malformed
{ "accepted": false, "reason": "invalid_scope", "details": "..." }
```

### `POST /v1/tick`
```json
// Request
{ "now": "ISO8601", "available_triggers": ["trg_id_1", "trg_id_2"] }

// Response 200
{
  "actions": [
    {
      "conversation_id": "string",
      "merchant_id": "string",
      "customer_id": "string | null",
      "send_as": "vera" | "merchant_on_behalf",
      "trigger_id": "string",
      "template_name": "string",
      "template_params": ["string"],
      "body": "string",
      "cta": "open_ended" | "binary_yes_no" | "binary_confirm_cancel" | "multi_choice_slot" | "none",
      "suppression_key": "string",
      "rationale": "string"
    }
  ]
}
```

### `POST /v1/reply`
```json
// Request
{
  "conversation_id": "string",
  "merchant_id": "string | null",
  "customer_id": "string | null",
  "from_role": "merchant" | "customer",
  "message": "string",
  "received_at": "ISO8601",
  "turn_number": 2
}

// Response 200 — send
{ "action": "send", "body": "string", "cta": "string", "rationale": "string" }

// Response 200 — wait
{ "action": "wait", "wait_seconds": 14400, "rationale": "string" }

// Response 200 — end
{ "action": "end", "rationale": "string" }
```

---

## Data / Database Changes

No persistent database required. All state lives in in-memory Python dicts:

```python
contexts: dict[tuple[str, str], dict]   # (scope, context_id) → {version, payload}
conversations: dict[str, list]          # conversation_id → [turn dicts]
suppressed: set[str]                    # suppression_keys already acted on
ended_conversations: set[str]           # conversation_ids that have been ended
```

---

## UI / UX Changes

No UI. The "output" is WhatsApp message text. Quality rules:

- No long preambles ("I hope you're doing well…")
- CTA lands in the **last sentence**
- No more than one CTA per message
- No re-introducing yourself after the first message in a conversation
- No URLs in message body (Meta template restriction — will cause a −3 penalty)
- Hindi-English code-mix is preferred for merchants with `"hi"` in `identity.languages`
- Emojis allowed sparingly in customer-facing messages; avoid in clinical categories (dentists)

---

## Files to Create

| File | Purpose |
|---|---|
| `bot.py` | FastAPI HTTP server — all 5 endpoints + in-memory state |
| `composer.py` | LLM composition logic — takes 4 context dicts, returns action dict |
| `reply_handler.py` | Multi-turn reply logic — auto-reply detection, intent transition, hostile handling |
| `submission.jsonl` | 30-line JSONL — one pre-composed message per test pair |
| `README.md` | ≤1 page: approach, tradeoffs, what additional context would have helped |
| `conversation_handlers.py` | (Optional) standalone `respond(state, merchant_message)` for multi-turn demo |

## Files to Modify

| File | Change needed |
|---|---|
| `judge_simulator.py` | Set `BOT_URL`, `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL` at top of file before testing |

---

## Constraints / Rules

### Message Composition
- **No fabrication** — every number, date, citation, or name must appear in the pushed context. Fabricated data = −2 per instance.
- **No generic offers** — "Flat 30% off" when service+price is available ("Haircut @ ₹99") → penalised.
- **No URLs** in the message body — −3 per URL found.
- **No taboo vocabulary** — each category defines forbidden words (e.g., dentists: "guaranteed", "miracle", "cure").
- **No repetition** — same `body` text sent twice in the same `conversation_id` → −2 anti-repetition penalty per repeat.
- **Temperature = 0** — LLM must be called with deterministic settings.

### HTTP Contract
- `/v1/tick` must respond within 30s. If it cannot compose in time, return `{"actions": []}` immediately — do not delay.
- A `conversation_id` used in `/v1/tick` cannot be reused in a subsequent tick for a different conversation. Use `/v1/reply` to continue existing conversations.
- Malformed responses (missing required fields in actions) → −2 penalty per malformed action.

### Scoring Anti-Patterns (each penalised)
- Multiple CTAs in one message
- Buried CTA (not in the last sentence)
- Promotional tone in clinical categories
- Re-introducing Vera after the first message
- Ignoring language preference
- Continuing to qualify after merchant signals clear intent

---

## Edge Cases

### Auto-Reply Hell
- **Trigger**: Judge sends identical canned auto-reply 3–4 turns in a row
- **Expected**: `wait` after turn 2, `end` after turn 3–4
- **Wrong**: Continuing to engage or sending the same prompt again

### Intent Transition
- **Trigger**: Merchant says "Ok let's do it" or "Yes go ahead" after 1–2 qualifying turns
- **Expected**: Bot immediately switches to action mode, confirms next step
- **Wrong**: Asking another qualifying question → explicit penalty

### Hostile / Opt-Out
- **Trigger**: "Stop messaging me", "This is spam", abuse
- **Expected**: `end` immediately, or one short apology + `end`
- **Wrong**: Any further persuasion attempt

### Off-Topic Ask
- **Trigger**: Merchant asks something outside Vera's scope ("Help me file my GST")
- **Expected**: Politely decline, redirect back to the open thread
- **Wrong**: Attempting to answer, ignoring the open thread

### Stale Context Re-Push
- **Trigger**: Judge re-pushes same `(scope, context_id, version)` already stored
- **Expected**: `{"accepted": false, "reason": "stale_version", "current_version": N}`
- **Wrong**: Accepting and overwriting with the same version

### Mid-Test Context Update
- **Trigger**: Judge pushes a new `version` of a category or merchant context mid-conversation
- **Expected**: Bot uses the updated context in subsequent sends (not the stale version)
- **Wrong**: Ignoring the update; fabricating content from the old digest

### Missing Merchant in Trigger
- **Trigger**: A trigger references a `merchant_id` not yet pushed to `/v1/context`
- **Expected**: Skip the trigger; return `{"actions": []}` for that trigger; do not crash
- **Wrong**: 500 error, hallucinated merchant data

### Customer Consent Mismatch
- **Trigger**: `recall_due` trigger for a customer whose consent scope does not include `recall_reminders`
- **Expected**: Do not send; skip or `end`
- **Wrong**: Sending a recall reminder to an unconsented customer

### Expired Trigger
- **Trigger**: `trigger.expires_at` is in the past at the time of `/v1/tick`
- **Expected**: Skip the trigger; do not compose a message for it
- **Wrong**: Composing a message for an expired event

### Suppression Key Collision
- **Trigger**: Same `suppression_key` already fired in a previous tick
- **Expected**: Do not fire again; skip
- **Wrong**: Sending a duplicate message

---

## Testing

### Local Testing with Judge Simulator

```bash
# Edit judge_simulator.py: set LLM_PROVIDER, LLM_API_KEY, BOT_URL
python judge_simulator.py   # runs TEST_SCENARIO = "all" by default

# Individual scenarios (edit TEST_SCENARIO in judge_simulator.py):
# "warmup"           — healthz + metadata + context push
# "phase2_short"     — warmup + 3-trigger tick with LLM scoring
# "auto_reply_hell"  — 4 turns of identical auto-reply
# "intent_transition"— merchant commits; bot must switch to action
# "hostile"          — merchant abuses; bot must end
# "full_evaluation"  — push all 50 merchants + all triggers + score all ticks
```

### Manual curl tests

```bash
export BOT_URL=http://localhost:8080

# Health check
curl $BOT_URL/v1/healthz

# Push a category
curl -X POST -H "Content-Type: application/json" \
  -d @dataset/categories/dentists.json $BOT_URL/v1/context

# Run a tick
curl -X POST -H "Content-Type: application/json" \
  -d '{"now":"2026-04-26T10:35:00Z","available_triggers":["trg_001_research_digest_dentists"]}' \
  $BOT_URL/v1/tick

# Simulate a reply
curl -X POST -H "Content-Type: application/json" \
  -d '{"conversation_id":"conv_001","merchant_id":"m_001_drmeera_dentist_delhi","from_role":"merchant","message":"Yes please send the abstract","received_at":"2026-04-26T10:42:00Z","turn_number":2}' \
  $BOT_URL/v1/reply
```

### Scoring Rubric (per message, 0–10 each = 50 total)

| Dimension | What to verify |
|---|---|
| Specificity | Contains real numbers/dates/citations from the pushed context — not invented |
| Category fit | Voice, vocabulary, and tone match the category's `voice` profile |
| Merchant fit | Uses owner name; references their actual signals, numbers, and language pref |
| Trigger relevance | Message clearly anchors on the specific trigger event (not a generic nudge) |
| Engagement compulsion | Uses ≥1 compulsion lever; single clear CTA in the last sentence |

### Reference Outputs

`examples/case-studies.md` contains 10 fully-scored example messages (one per category × 2 trigger types). Use these as a north star. Do not copy them verbatim — the judge runs plagiarism detection.

---

## Definition of Done

- [ ] All 5 HTTP endpoints implemented and returning correct schemas
- [ ] `/v1/context` is idempotent on `(scope, context_id, version)`; returns 409 on stale re-push
- [ ] `/v1/tick` returns within 30s for any trigger set (returns `{"actions": []}` if nothing worth sending)
- [ ] `/v1/reply` handles: genuine reply → `send`, auto-reply → `wait`/`end`, opt-out → `end`, intent-commit → action mode, off-topic → redirect
- [ ] Composed messages pass all composition rules: no fabrication, no URLs, no taboo vocab, single CTA, voice-matched, language-matched
- [ ] `judge_simulator.py` passes locally with a score ≥ 30/50 average across all scenarios
- [ ] `submission.jsonl` contains 30 lines covering all test pairs
- [ ] `README.md` written (≤1 page)
- [ ] Bot reachable at a public URL (or ngrok tunnel) for submission
