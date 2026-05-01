# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A competition entry for the **magicpin AI Challenge**: build "Vera", an AI chatbot that messages Indian merchants over WhatsApp at the right time with the right content. The submission is an **HTTP server** (FastAPI) evaluated by an LLM judge.

## Running the bot and judge

```bash
# Install deps
pip install fastapi uvicorn anthropic httpx pytest pytest-asyncio

# Start the bot server
uvicorn bot.main:app --host 0.0.0.0 --port 8080 --reload

# Run all tests
pytest tests/

# Run a single test file
pytest tests/test_context.py -v

# Run the judge simulator (configure LLM_PROVIDER, LLM_API_KEY, BOT_URL, TEST_SCENARIO at top of file)
python judge_simulator.py

# Available TEST_SCENARIO values: warmup | phase2_short | auto_reply_hell | intent_transition | hostile | all | full_evaluation
```

## Planned module layout

The bot does not yet exist — build it according to this structure:

```
bot/
├── main.py                  # FastAPI app, 5 route handlers
├── models.py                # Pydantic request/response schemas
├── state.py                 # In-memory stores (singletons): contexts, conversations, suppressed_keys, ended_conversations
├── config.py                # env vars: TEAM_NAME, TEAM_MEMBERS, MODEL, VERSION, LLM_PROVIDER, LLM_API_KEY
├── suppression.py           # suppression-key dedup tracking
├── services/
│   ├── context_service.py   # versioned put/get with idempotency (returns 409 on stale version)
│   ├── tick_service.py      # /v1/tick orchestration: filter expired/suppressed, call composer
│   └── reply_service.py     # /v1/reply orchestration: classify intent, dispatch action
├── composer/
│   ├── composer.py          # build prompt → call LLM → parse → validate (7-step pipeline)
│   ├── prompts.py           # base prompt + per-trigger framing templates
│   └── voice.py             # per-category voice pack rules
├── intent/
│   └── classifier.py        # auto-reply / opt-out / commit / off-topic / engaged classifier
├── llm/
│   ├── adapter.py           # LLMProvider ABC: complete(system, user, max_tokens, temperature, timeout)
│   ├── anthropic_adapter.py
│   └── openai_adapter.py
└── validation/
    └── validators.py        # URL check, taboo vocab, CTA shape, anti-fabrication, repetition

tests/
├── conftest.py              # pytest fixtures (TestClient bound to fresh app, fake LLM)
├── test_health.py
├── test_context.py          # idempotency, version replace, malformed payload
├── test_tick.py             # composition, suppression, expiry
├── test_reply.py            # auto-reply, intent, hostile, off-topic
├── test_composer.py
├── test_validators.py
└── test_intent.py

scripts/
├── generate_submission.py   # builds submission.jsonl from 30 test pairs
└── run_local_judge.sh       # bot up + judge_simulator.py run
```

## Architecture

### The 5-endpoint HTTP contract

The judge drives everything over HTTP. All state is in-process Python dicts — no DB, no Redis.

| Endpoint | Purpose |
|---|---|
| `GET /v1/healthz` | Liveness probe — returns `contexts_loaded` counts |
| `GET /v1/metadata` | Team identity + model used |
| `POST /v1/context` | Receive context; idempotent by `(scope, context_id, version)` — same version → 409 stale_version; higher version atomically replaces |
| `POST /v1/tick` | Judge wakes bot; bot returns `actions[]` (or empty if nothing worth sending) |
| `POST /v1/reply` | Judge sends merchant reply; bot returns `{action: send|wait|end, ...}` |

### The 4-layer composition pipeline

Every outbound message is composed from 4 context layers:

```
compose(category, merchant, trigger, customer?) → {body, cta, send_as, suppression_key, rationale}
```

- **category** — voice rules, offer catalog, peer benchmarks, research digest, seasonal beats
- **merchant** — identity, performance numbers, active offers, conversation history, signals
- **trigger** — the event causing this message (`research_digest`, `perf_dip`, `recall_due`, `festival_upcoming`, etc.)
- **customer** — optional; when sending on the merchant's behalf to one of their customers

The 7-step composition pipeline in `composer.py`:
1. Context distillation (strip irrelevant fields, keep top 5 digest items)
2. Voice pack lookup (tone, vocab_allowed, vocab_taboo)
3. Trigger framing (select prompt template by `trigger.kind`)
4. Build prompt (system = rules + voice; user = all 4 context facts)
5. LLM call (`temperature=0`, `max_tokens=800`, `timeout=25s`)
6. Parse JSON response → `ComposedMessage`
7. Validation (length 10–800 chars, no URLs, no taboo vocab, CTA shape, anti-fabrication) — retry once on failure, skip if still invalid

### Tick → reply flow

```
POST /v1/tick  →  bot returns actions[]  →  judge plays merchant  →
POST /v1/reply  →  bot returns send/wait/end  →  repeat up to 5 turns
```

### Reply intent classification

The `classifier.py` classifies each merchant reply into one of: `AUTO_REPLY | OPT_OUT | HOSTILE | INTENT_COMMIT | OFF_TOPIC | ENGAGED | UNCLEAR`

Dispatch rules:
- **AUTO_REPLY**: turn 1 → send hint prompt; turn 2 → `wait` 4–24h; turn 3+ → `end`
- **OPT_OUT / HOSTILE**: immediately `end`, add `conv_id` to `ended_conversations`
- **INTENT_COMMIT**: switch to action mode — compose next concrete step + binary confirm CTA
- **OFF_TOPIC**: politely decline + redirect to topic
- **ENGAGED**: `compose_reply(conv_history, message)` and continue

## Phased implementation roadmap

Build in order; each phase is independently testable:

| Phase | What it delivers | Judge scenario that gates it |
|---|---|---|
| 1 — HTTP Foundation | All 5 endpoints; idempotent versioned context store | `warmup` passes |
| 2 — LLM Composer Baseline | `/v1/tick` produces real LLM-composed messages | `phase2_short` returns ≥1 scored action |
| 3 — Composition Quality | Voice packs, trigger routing, validation pipeline, suppression | `full_evaluation` avg ≥ 35/50 |
| 4 — Reply Handler | Multi-turn `/v1/reply` with intent classifier | `auto_reply_hell`, `intent_transition`, `hostile` all pass |
| 5 — Customer-Facing & Edge Cases | `merchant_on_behalf` flow, consent gate, expiry, version updates | Customer-scope triggers produce valid actions; avg ≥ 38/50 |
| 6 — Submission & Deployment | `submission.jsonl`, README, public deployment | E2E from public URL passes |

## Dataset

```
dataset/
├── categories/          # 5 CategoryContext JSONs (dentists, salons, restaurants, gyms, pharmacies)
├── merchants_seed.json  # 10 seed MerchantContexts (generator expands to 50)
├── customers_seed.json  # seed CustomerContexts (expands to 200)
├── triggers_seed.json   # 25 seed TriggerContexts (expands to 100)
└── generate_dataset.py  # expand seeds to full dataset
```

## Scoring (50 points total)

| Dimension | What earns full marks |
|---|---|
| Specificity | Real numbers from context — "38% better", "JIDA Oct 2026 p.14", "2,100-patient trial" |
| Category fit | Voice matches the vertical (dentists = clinical-peer; gyms = coach; restaurants = operator) |
| Merchant fit | Uses owner name, references their actual signals/numbers, honors language pref |
| Trigger relevance | Message clearly says *why now* — the trigger is the anchor, not a generic nudge |
| Engagement compulsion | Loss aversion, curiosity, social proof, effort externalization, single binary CTA |

**Penalties**: fabricating data not in context (−2), exposing internal jargon (−1), URL in body (−3), repeated body text (−2), malformed response (−2).

## Key constraints

- `/v1/tick` and `/v1/reply` must respond within **30s** — return `{"actions": []}` or `{"action": "wait"}` immediately if you can't compose in time (use 25s LLM timeout to preserve buffer)
- No URLs in message bodies (Meta WhatsApp template restriction)
- Single CTA per message (binary YES/STOP for action triggers; no CTA for pure-info triggers)
- Never fabricate data not present in the pushed contexts — the anti-fabrication validator extracts all numbers/names/dates from the body and cross-checks them against input context text
- LLM `temperature=0` for deterministic output
- Run uvicorn with `--workers 1` (single process) — all state is in-memory; multi-worker diverges state

## Tech stack

FastAPI 0.110+ + uvicorn (async, single process), Pydantic v2 for request validation, `httpx` for async HTTP in both LLM adapters and tests, pytest + pytest-asyncio + httpx.AsyncClient for testing, ruff + mypy (strict on `bot/`) for linting.

## Reference material

- `.claude/specs/architecture.md` — full component diagram, data flows, state machine diagrams, validation pipeline detail
- `.claude/specs/vera-bot.md` — functional requirements, edge cases, detailed reply handler behavior
- `.claude/specs/phases/` — per-phase acceptance criteria and code sketches
- `examples/case-studies.md` — 10 fully-scored example messages (north star for composition quality)
- `examples/api-call-examples.md` — exact HTTP request/response pairs for every endpoint
- `challenge-brief.md` — full product + evaluation spec
- `challenge-testing-brief.md` — HTTP contract + judge lifecycle + pre-flight checklist
