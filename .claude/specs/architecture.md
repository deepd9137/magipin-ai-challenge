# System Architecture — Vera Bot

> Companion to `.claude/specs/vera-bot.md` (the functional spec).
> Defines **how** the bot is structured to satisfy the spec.

---

## 1. Architectural Goals

| Goal | Why it matters |
|---|---|
| **Stateless endpoints, stateful service** | Judge can call any endpoint at any time; bot must remember everything in-process. |
| **Deterministic outputs** | LLM `temperature=0`; same context → same message. Required for reproducibility. |
| **30-second hard budget** per `/v1/tick` and `/v1/reply` — fall back to empty/`wait` if LLM exceeds budget. |
| **Composability of contexts** | Each of the 4 context layers (category, merchant, customer, trigger) is independently versioned and can update mid-test. |
| **Pluggable LLM provider** | Anthropic / OpenAI / Gemini / DeepSeek / Groq / Ollama — provider behind one interface. |
| **Validate before sending** | A composed message must pass URL/taboo/length/fabrication checks before becoming an action. |
| **Graceful degradation** | If LLM fails or validation rejects twice, return empty `actions` rather than send garbage. |

---

## 2. High-Level Component Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│  Vera Bot Server (FastAPI)                                           │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  ENDPOINT LAYER  (bot/main.py)                               │   │
│  │  GET  /v1/healthz   GET  /v1/metadata                        │   │
│  │  POST /v1/context   POST /v1/tick   POST /v1/reply           │   │
│  └────────────────┬───────────────┬────────────────┬────────────┘   │
│                   │               │                │                 │
│         ┌─────────▼──────┐  ┌─────▼──────┐  ┌──────▼──────────┐     │
│         │ ContextService │  │ TickService│  │ ReplyService    │     │
│         │ (idempotent    │  │ (proactive │  │ (multi-turn     │     │
│         │  put/replace)  │  │  composer) │  │  reply handler) │     │
│         └─────────┬──────┘  └─────┬──────┘  └──────┬──────────┘     │
│                   │               │                │                 │
│                   │     ┌─────────▼────────┐       │                 │
│                   │     │ Composer         │◄──────┤                 │
│                   │     │ (4-ctx → message)│       │                 │
│                   │     └─────────┬────────┘       │                 │
│                   │               │                │                 │
│                   │     ┌─────────▼────────┐       │                 │
│                   │     │ Validator        │       │                 │
│                   │     │ (URL/taboo/CTA/  │       │                 │
│                   │     │  fabrication)    │       │                 │
│                   │     └─────────┬────────┘       │                 │
│                   │               │                │                 │
│                   │     ┌─────────▼────────┐       │                 │
│                   │     │ LLM Adapter      │◄──────┤                 │
│                   │     │ (provider plug)  │       │                 │
│                   │     └──────────────────┘       │                 │
│                   │                                │                 │
│         ┌─────────▼────────────────────────────────▼─────────┐       │
│         │  STATE LAYER (in-memory; bot/state.py)             │       │
│         │  contexts[(scope, ctx_id)] = {version, payload}    │       │
│         │  conversations[conv_id] = [Turn, ...]              │       │
│         │  suppressed: set[suppression_key]                  │       │
│         │  ended_conversations: set[conv_id]                 │       │
│         └──────────────────────────────────────────────────────┘       │
└──────────────────────────────────────────────────────────────────────┘
                              ▲
                              │  HTTP/JSON
                              ▼
            ┌─────────────────────────────────┐
            │  Judge Harness                  │
            │  (judge_simulator.py + LLM      │
            │   playing merchant/customer)    │
            └─────────────────────────────────┘
```

---

## 3. Module Layout

```
magicpin-ai-challenge/
├── bot/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app, route handlers
│   ├── models.py                # Pydantic request/response schemas
│   ├── state.py                 # In-memory stores (singletons)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── context_service.py   # versioned put/get with idempotency
│   │   ├── tick_service.py      # /v1/tick orchestration
│   │   └── reply_service.py     # /v1/reply orchestration
│   ├── composer/
│   │   ├── __init__.py
│   │   ├── composer.py          # build prompt → call LLM → parse
│   │   ├── prompts.py           # base prompt + per-trigger framing
│   │   └── voice.py             # per-category voice rules
│   ├── intent/
│   │   ├── __init__.py
│   │   └── classifier.py        # auto-reply / opt-out / commit / off-topic
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── adapter.py           # LLMProvider abstract base
│   │   ├── anthropic_adapter.py
│   │   └── openai_adapter.py
│   ├── validation/
│   │   ├── __init__.py
│   │   └── validators.py        # URL, taboo, CTA shape, fabrication
│   ├── suppression.py           # suppression-key dedup tracking
│   └── config.py                # env vars (LLM_PROVIDER, LLM_API_KEY, MODEL)
│
├── tests/
│   ├── conftest.py              # pytest fixtures (test client, fake LLM)
│   ├── test_health.py
│   ├── test_context.py          # idempotency, versioning, malformed
│   ├── test_tick.py             # composition, suppression, expiry
│   ├── test_reply.py            # auto-reply, intent, hostile, off-topic
│   ├── test_composer.py
│   ├── test_validators.py
│   └── test_intent.py
│
├── scripts/
│   ├── generate_submission.py   # builds submission.jsonl from 30 test pairs
│   └── run_local_judge.sh       # bot up + judge_simulator.py run
│
├── submission.jsonl             # 30 lines (one per test pair)
├── README.md                    # ≤1 page approach summary
├── requirements.txt             # FastAPI + uvicorn + LLM SDK + pytest + httpx
└── Dockerfile                   # for cloud deployment
```

---

## 4. Core Abstractions

### 4.1 Data structures

```python
# bot/state.py
from dataclasses import dataclass
from datetime import datetime

@dataclass
class StoredContext:
    scope: str            # "category" | "merchant" | "customer" | "trigger"
    context_id: str
    version: int
    payload: dict
    stored_at: datetime

@dataclass
class Turn:
    ts: datetime
    from_role: str        # "vera" | "merchant" | "customer"
    body: str
    kind: str             # "send" | "wait" | "end" | "reply"
    cta: str | None = None
    intent_classified: str | None = None   # filled by classifier

@dataclass
class ComposedMessage:
    body: str
    cta: str
    send_as: str          # "vera" | "merchant_on_behalf"
    suppression_key: str
    rationale: str
    template_name: str
    template_params: list[str]
```

### 4.2 LLM Adapter Interface

```python
# bot/llm/adapter.py
from abc import ABC, abstractmethod

class LLMProvider(ABC):
    @abstractmethod
    def complete(self, system: str, user: str, max_tokens: int = 800,
                 temperature: float = 0.0, timeout: int = 25) -> str: ...

    @abstractmethod
    def name(self) -> str: ...
```

### 4.3 Composer Interface

```python
# bot/composer/composer.py
def compose(category: dict, merchant: dict, trigger: dict,
            customer: dict | None = None) -> ComposedMessage | None:
    """
    Build prompt from 4 contexts, call LLM, parse response, validate.
    Returns None if validation fails twice or LLM times out.
    """
```

### 4.4 Intent Classifier Interface

```python
# bot/intent/classifier.py
from enum import Enum

class Intent(Enum):
    AUTO_REPLY = "auto_reply"
    OPT_OUT = "opt_out"
    HOSTILE = "hostile"
    INTENT_COMMIT = "intent_commit"   # "ok let's do it", "yes please"
    OFF_TOPIC = "off_topic"           # asks unrelated
    ENGAGED = "engaged"               # genuine reply
    UNCLEAR = "unclear"

def classify(message: str, history: list[Turn]) -> Intent: ...
```

---

## 5. Request Flows

### 5.1 Flow A — Context Push (`POST /v1/context`)

```
HTTP request
  │
  ▼
Pydantic validation (CtxBody)
  │
  ▼
ContextService.put(scope, context_id, version, payload):
  │
  ├─ if (scope, context_id) exists with version >= incoming:
  │     → return 409 stale_version
  ├─ else:
  │     → atomic replace state.contexts[(scope, context_id)]
  │     → return 200 accepted
```

### 5.2 Flow B — Tick (`POST /v1/tick`)

```
HTTP request { now, available_triggers[] }
  │
  ▼
TickService.handle():
  │
  for each trigger_id in available_triggers:
    ├─ Look up trigger payload from state
    ├─ if not found → skip
    ├─ if expires_at < now → skip (expired)
    ├─ if suppression_key in suppressed_keys → skip
    ├─ Look up merchant context; if missing → skip
    ├─ Look up category context (via merchant.category_slug)
    ├─ if trigger.scope == "customer":
    │     Look up customer context
    │     Check customer.consent.scope includes trigger.kind
    │     If consent missing → skip
    ▼
    Composer.compose(category, merchant, trigger, customer?)
      │
      ▼
    if result is None (LLM/validation failed) → skip
    if action created → mark suppression_key fired
  │
  ▼
Return { actions: [...] }  (≤20)
```

### 5.3 Flow C — Reply (`POST /v1/reply`)

```
HTTP request { conv_id, message, turn_number, ... }
  │
  ▼
ReplyService.handle():
  │
  ├─ if conv_id in ended_conversations → return ack-no-op
  ├─ Append turn to conversations[conv_id]
  ▼
  IntentClassifier.classify(message, history):
  │
  ┌──────────────────────┬──────────────────────┬─────────────────┐
  │                      │                      │                 │
  ▼                      ▼                      ▼                 ▼
AUTO_REPLY          OPT_OUT/HOSTILE        INTENT_COMMIT     OFF_TOPIC
  │                      │                      │                 │
  count consecutive      ▼                      ▼                 ▼
  auto-replies in        action=end             action=send       action=send
  this conversation:                            (action mode      (polite
  - 1: send hint         add conv_id to         draft + binary    decline +
  - 2: action=wait       ended_conversations    confirm CTA)      redirect)
  - 3+: action=end                              │                 │
                                                ▼                 ▼
                       ENGAGED                                    composer.compose_reply
                       │
                       ▼
                       composer.compose_reply(conv_history, message)
  │
  ▼
Validate output → return response
```

---

## 6. State Management

All state is **in-process Python dicts**. No DB, no Redis, no disk.

### Why in-memory is enough
- Test window is 60 simulated minutes (~30-45 real)
- Judge does not restart the bot
- 50 merchants × ~5 contexts each = ~5MB of state at most
- Conversations grow to ~5 turns × ~50 conversations = small

### Concurrency model
- FastAPI runs on uvicorn (asyncio single-threaded by default)
- All endpoints are `async def`
- LLM calls are blocking → wrap in `asyncio.to_thread()` or use SDK's async API
- No locks needed for state writes (single-threaded event loop)
- If we move to multi-worker uvicorn → switch to `multiprocessing.Manager` dicts or Redis

### State invariants
1. `contexts[(scope, ctx_id)].version` is monotonically increasing
2. `suppressed_keys` only grows (no removal during test)
3. `ended_conversations` only grows
4. `conversations[conv_id]` is append-only

---

## 7. LLM Composition Pipeline

```
┌───────────────────────────────────────────────────────────┐
│ Step 1 — Context Distillation                             │
│  Strip large/irrelevant fields from each context layer    │
│  (e.g. drop conversation_history older than 7d, keep      │
│   only top 5 digest items)                                │
└────────────────────────┬──────────────────────────────────┘
                         │
                         ▼
┌───────────────────────────────────────────────────────────┐
│ Step 2 — Voice Pack Lookup                                │
│  category.voice → tone, vocab_allowed, vocab_taboo,       │
│  salutation_examples, tone_examples                       │
└────────────────────────┬──────────────────────────────────┘
                         │
                         ▼
┌───────────────────────────────────────────────────────────┐
│ Step 3 — Trigger Framing                                  │
│  trigger.kind → which prompt template to use:             │
│   research_digest → "lead with source citation"           │
│   recall_due      → "lead with timing + slot offer"       │
│   perf_dip        → "lead with diagnosis + reframe"       │
│   festival_*      → "lead with category-specific hook"    │
│   curious_ask     → "ask the merchant a question"         │
│   compliance      → "lead with deadline + impact"         │
└────────────────────────┬──────────────────────────────────┘
                         │
                         ▼
┌───────────────────────────────────────────────────────────┐
│ Step 4 — Build Prompt                                     │
│  System: composition rules + voice pack                   │
│  User: { category_facts, merchant_facts, trigger_facts,   │
│          customer_facts? }                                │
│  Output schema: JSON { body, cta, rationale, ... }        │
└────────────────────────┬──────────────────────────────────┘
                         │
                         ▼
┌───────────────────────────────────────────────────────────┐
│ Step 5 — LLM Call (temp=0, max_tokens=800, timeout=25s)   │
└────────────────────────┬──────────────────────────────────┘
                         │
                         ▼
┌───────────────────────────────────────────────────────────┐
│ Step 6 — Parse JSON Response                              │
│  Extract body, cta, rationale; build ComposedMessage      │
└────────────────────────┬──────────────────────────────────┘
                         │
                         ▼
┌───────────────────────────────────────────────────────────┐
│ Step 7 — Validation Pipeline (5 checks)                   │
│  (a) body non-empty + reasonable length (10-800 chars)    │
│  (b) no URLs in body                                      │
│  (c) no taboo vocab from category.voice.vocab_taboo       │
│  (d) CTA shape matches one of allowed values              │
│  (e) anti-fabrication: every number, %, date, named      │
│      entity in body must appear somewhere in input        │
│      contexts (regex extraction + substring check)        │
└────────────────────────┬──────────────────────────────────┘
                         │
            ┌────────────┴────────────┐
            │                         │
        valid                     invalid
            │                         │
            ▼                  re-prompt with error
        return action          (one retry only)
                                      │
                                      ▼
                              still invalid → return None (skip)
```

---

## 8. Conversation State Machine (Reply Handler)

```
                   reply received
                        │
                        ▼
                 append to history
                        │
                        ▼
              classify_intent(msg, history)
                        │
   ┌───────────┬────────┼────────┬─────────────┬──────────┐
   │           │        │        │             │          │
   ▼           ▼        ▼        ▼             ▼          ▼
AUTO_REPLY  OPT_OUT  HOSTILE  INTENT_COMMIT  OFF_TOPIC  ENGAGED
   │           │        │        │             │          │
   ▼           ▼        ▼        ▼             ▼          ▼
count          end      end      action mode   redirect   continue
consecutive    │        │        │             to thread  thread
auto-replies   │        │        compose       │          │
in this conv   │        │        next concrete │          │
   │           │        │        step + binary │          │
   │           │        │        confirm CTA   │          │
   │           │        │        │             │          │
1: send hint   ▼        ▼        ▼             ▼          ▼
2: wait     mark conv ended     mark suppression      send + log
3+: end     in ended_set       fire on commit
            return end
```

### Auto-reply detection heuristics
- **Phrase signals**: "thank you for contacting", "team will respond shortly", "automated assistant", "please leave a message"
- **Repetition signal**: same message body verbatim ≥ 2 times in same conversation
- **Length signal**: very generic ≤ 80-char "thank you" message in turn 2

### Intent commit signals
- **Affirmative phrases**: "yes please", "ok let's do it", "go ahead", "haan kar do", "draft kar do"
- **Action verbs**: "send", "schedule", "post", "draft"
- **Combined with prior question** asked by Vera in last turn

### Hostile signals
- **Explicit stop**: "stop", "don't message", "unsubscribe", "spam"
- **Negative sentiment**: profanity, "useless", "bothering", "harass"

---

## 9. Validation Pipeline (Detail)

| Check | Implementation | Failure action |
|---|---|---|
| **Length** | `10 <= len(body) <= 800` | retry once, then skip |
| **No URL** | regex `https?://`, `www\.`, `\.com/`, `bit.ly` | retry once, then skip |
| **No taboo** | substring scan of `category.voice.vocab_taboo` | retry once, then skip |
| **CTA shape** | `cta ∈ {open_ended, binary_yes_no, binary_confirm_cancel, multi_choice_slot, none}` | retry once |
| **Fabrication** | extract numbers/percentages/proper nouns/dates from body; each must appear in flattened text of input contexts (substring match w/ tolerance) | retry once with explicit list of unauthorized facts |
| **Repetition** | normalized body equality vs prior bot turns in same conversation | retry once |
| **Language match** | if `merchant.identity.languages` includes `"hi"` → at least 2 Hindi tokens expected (heuristic via Devanagari or romanized common words) | warn-only (don't block) |

---

## 10. Tech Stack

| Layer | Choice | Justification |
|---|---|---|
| HTTP server | FastAPI 0.110+ + uvicorn | Async, Pydantic v2 built-in, lowest boilerplate |
| Validation | Pydantic v2 | Schema-first request validation |
| LLM (primary) | Anthropic Claude Sonnet 4.6 | Best instruction-following; long context for 4-layer prompt |
| LLM (fallback) | OpenAI GPT-4o-mini | Cheap, fast for retries |
| HTTP client | `httpx` | Used by both LLM SDK and tests |
| Tests | pytest + pytest-asyncio + httpx.AsyncClient | Standard FastAPI testing |
| Lint/format | ruff + mypy (strict on `bot/`) | Catches obvious bugs |
| Container | python:3.11-slim Docker base | Render/Fly compatibility |

---

## 11. Observability

Every action emits a single JSON log line:

```json
{
  "ts": "2026-04-26T10:35:00.123Z",
  "event": "compose_action",
  "trigger_id": "trg_001_research_digest_dentists",
  "merchant_id": "m_001_drmeera_dentist_delhi",
  "category_slug": "dentists",
  "trigger_kind": "research_digest",
  "llm_latency_ms": 1840,
  "validation_passes": ["length", "no_url", "no_taboo", "cta_shape", "no_fab"],
  "validation_failures": [],
  "retry_count": 0,
  "suppression_key": "research:dentists:2026-W17",
  "body_chars": 245,
  "rationale": "External research digest with merchant-relevant clinical anchor."
}
```

Log lines also at:
- `context_accept` / `context_reject_stale`
- `tick_skip_reason` (with reason: expired / suppressed / missing_merchant / consent_missing)
- `intent_classified` (with intent + confidence)
- `reply_action` (with action: send / wait / end)
- `llm_error` (with error class + retry attempt)

Logs go to stdout; cloud platforms ingest from there.

---

## 12. Deployment Topology

```
        ┌──────────────────────────┐
        │  Public URL              │
        │  (ngrok or Render/Fly)   │
        └────────────┬─────────────┘
                     │
                     ▼
        ┌──────────────────────────┐
        │  uvicorn worker          │
        │  bot.main:app            │
        │  port 8080               │
        │  single process          │
        └────────────┬─────────────┘
                     │
                     ▼
        ┌──────────────────────────┐
        │  In-memory state         │
        │  (dies on restart)       │
        └──────────────────────────┘
```

Single-process is acceptable for the test window. If a public host requires multi-worker, switch to single-worker mode (`--workers 1`) or use a shared dict via Redis.

---

## 13. Phase Implementation Roadmap

The build is split into 6 phases, each independently testable and additive.

| Phase | Capability Delivered | Pass Criterion (judge_simulator.py) |
|---|---|---|
| [Phase 1 — HTTP Foundation & State](phases/phase-01-http-foundation.md) | All 5 endpoints respond; idempotent versioned context store | `warmup` scenario passes |
| [Phase 2 — LLM Composer Baseline](phases/phase-02-llm-composer.md) | `/v1/tick` produces real composed messages via LLM | `phase2_short` produces ≥1 scored message |
| [Phase 3 — Composition Quality](phases/phase-03-composition-quality.md) | Voice rules, trigger routing, validation, suppression | `full_evaluation` avg ≥ 35/50 |
| [Phase 4 — Reply Handler](phases/phase-04-reply-handler.md) | Multi-turn `/v1/reply` with intent classifier | `auto_reply_hell`, `intent_transition`, `hostile` all pass |
| [Phase 5 — Customer-Facing & Edge Cases](phases/phase-05-customer-edge-cases.md) | `merchant_on_behalf` flow, consent, expiry, version updates | Customer-scope triggers produce valid actions |
| [Phase 6 — Submission & Deployment](phases/phase-06-submission-deployment.md) | `submission.jsonl`, README, public deployment | End-to-end full evaluation passes from public URL |

Each phase document specifies: goal, features, files to implement, test plan, expected output.

---

## 14. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| LLM hallucinates merchant names/numbers | Strict anti-fabrication validator; retry once with explicit list of unauthorized facts |
| LLM exceeds 30s budget | 25s timeout on LLM call; fall back to empty `actions` |
| Cost overrun (50 merchants × multiple ticks) | Use a smaller model for first pass, escalate only on validation failure |
| Multi-process state divergence | Pin to single uvicorn worker |
| Auto-reply false positive (real merchant says "thanks") | Require both phrase-match AND repetition signal before classifying as auto-reply |
| Intent commit false positive ("yes" to a question that wasn't a commitment) | Look at prior Vera turn — only classify as commit if Vera asked an actionable question |
| Submission deadline | Phase 6 runs in parallel with Phase 5 polish; submission.jsonl auto-generated from a script |

---

## End of architecture document
