# Phase 6 — Submission Package & Deployment

## Goal
Produce the final deliverables required for submission: a working `submission.jsonl` with 30 pre-composed messages, a 1-page `README.md` describing the approach, a publicly-reachable deployed endpoint, and a hardened end-to-end run that survives the full 60-minute judge window.

---

## Why this phase last
Phases 1–5 build a working bot. Phase 6 turns that into a **submittable artifact** and validates it against the **real test conditions**: public URL accessibility, sustained uptime, the canonical 30-test-pair set, and the judge's full evaluation lifecycle from warmup to replay.

Skipping this phase means Phases 1–5 produced great code that nobody can grade.

---

## Capabilities Delivered

1. **`submission.jsonl` generation script** — given the canonical 30 (merchant, trigger) pairs, runs the bot's composer offline and writes one valid action JSON per line.

2. **`README.md`** (≤1 page) covering:
   - Approach (single-prompt vs trigger-routed; voice pack design)
   - Tradeoffs (e.g., "we chose strict anti-fabrication over creative freedom")
   - Tech stack
   - What additional context would have helped most

3. **Public deployment** — bot reachable at a stable URL via one of:
   - ngrok tunnel (quickest for testing)
   - Render free tier (recommended for sustained availability)
   - Fly.io / Railway (alternatives)

4. **Containerization** — `Dockerfile` so deployment is reproducible.

5. **Observability hardening** — structured logs to stdout for every action, skip, validation failure, and intent classification.

6. **Performance tuning**:
   - LLM call concurrency (parallel composes within a single tick if multiple triggers)
   - Prompt size optimization (drop unused context fields before sending)
   - Response caching for identical (merchant, trigger) inputs (rare but possible across ticks)

7. **Submission portal artifacts**:
   - Public URL
   - `submission.jsonl` (uploaded or in repo)
   - `README.md`
   - Optional: `conversation_handlers.py` skeleton showing multi-turn capability

8. **End-to-end self-test**: run `judge_simulator.py` with `TEST_SCENARIO="all"` against the deployed URL (not localhost) and confirm all scenarios pass.

---

## Files / Modules to Implement

```
scripts/
├── generate_submission.py       # builds submission.jsonl from 30 test pairs
├── canonical_test_pairs.json    # the 30 (merchant_id, trigger_id) pairs
├── deploy_render.sh             # one-shot Render deploy helper
└── run_e2e_local.sh             # local end-to-end smoke test

submission.jsonl                 # 30 lines (generated artifact)
README.md                        # final, polished
Dockerfile                       # python:3.11-slim base
.dockerignore
fly.toml | render.yaml           # deployment config (one or the other)

bot/
├── logging_config.py            # structured JSON logger setup
└── main.py                      # add startup banner with config summary
```

### `scripts/generate_submission.py` (sketch)
```python
"""
Build submission.jsonl from the canonical 30 test pairs.

Usage:
    python scripts/generate_submission.py \
        --output submission.jsonl \
        --pairs scripts/canonical_test_pairs.json
"""

import argparse
import json
from pathlib import Path
from bot.composer.composer import compose
from bot.composer.customer_composer import compose_customer_facing
from bot.consent import has_consent
from bot.llm.anthropic_adapter import AnthropicAdapter
from bot.config import settings


def load_dataset(root: Path) -> dict:
    out = {"categories": {}, "merchants": {}, "customers": {}, "triggers": {}}
    for f in (root / "categories").glob("*.json"):
        d = json.load(open(f))
        out["categories"][d["slug"]] = d
    for entry in json.load(open(root / "merchants_seed.json"))["merchants"]:
        out["merchants"][entry["merchant_id"]] = entry
    for entry in json.load(open(root / "customers_seed.json")).get("customers", []):
        out["customers"][entry["customer_id"]] = entry
    for entry in json.load(open(root / "triggers_seed.json"))["triggers"]:
        out["triggers"][entry["id"]] = entry
    return out


def build_action(test_id: str, merchant: dict, customer: dict | None,
                 trigger: dict, result: dict) -> dict:
    return {
        "test_id": test_id,
        "merchant_id": merchant["merchant_id"],
        "customer_id": customer["customer_id"] if customer else None,
        "trigger_id": trigger["id"],
        "send_as": "merchant_on_behalf" if customer else "vera",
        "body": result["body"],
        "cta": result["cta"],
        "suppression_key": trigger.get("suppression_key", ""),
        "rationale": result.get("rationale", ""),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", required=True)
    parser.add_argument("--output", default="submission.jsonl")
    parser.add_argument("--dataset-dir", default="dataset")
    args = parser.parse_args()

    dataset = load_dataset(Path(args.dataset_dir))
    pairs = json.load(open(args.pairs))    # [{"test_id": "T01", "merchant_id": "...", "trigger_id": "..."}]
    llm = AnthropicAdapter(settings.LLM_API_KEY, settings.LLM_MODEL)

    with open(args.output, "w") as out:
        for pair in pairs:
            merchant = dataset["merchants"][pair["merchant_id"]]
            trigger = dataset["triggers"][pair["trigger_id"]]
            category = dataset["categories"][merchant["category_slug"]]
            customer = (dataset["customers"][trigger.get("customer_id")]
                        if trigger.get("customer_id") else None)

            if customer and not has_consent(customer, trigger.get("kind", "")):
                # consent missing — emit no-op marker
                line = {"test_id": pair["test_id"], "skipped": True, "reason": "consent_missing"}
                out.write(json.dumps(line) + "\n")
                continue

            if customer:
                result = compose_customer_facing(category, merchant, trigger, customer, llm)
            else:
                result = compose(category, merchant, trigger, customer=None, llm=llm)

            if not result:
                line = {"test_id": pair["test_id"], "skipped": True, "reason": "compose_failed"}
                out.write(json.dumps(line) + "\n")
                continue

            out.write(json.dumps(build_action(pair["test_id"], merchant, customer,
                                              trigger, result)) + "\n")

    print(f"Wrote {len(pairs)} entries to {args.output}")


if __name__ == "__main__":
    main()
```

### `Dockerfile`
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/ ./bot/
COPY dataset/ ./dataset/

ENV PYTHONUNBUFFERED=1 \
    PORT=8080

EXPOSE 8080

CMD ["uvicorn", "bot.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

### `render.yaml` (alternative for Render deployment)
```yaml
services:
  - type: web
    name: vera-bot
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn bot.main:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: LLM_PROVIDER
        value: anthropic
      - key: LLM_API_KEY
        sync: false    # set in Render dashboard
      - key: LLM_MODEL
        value: claude-sonnet-4-6
      - key: TEAM_NAME
        value: "Your Team"
```

### `bot/logging_config.py` (sketch)
```python
import logging
import json
import sys
from datetime import datetime

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        if hasattr(record, "extra"):
            payload.update(record.extra)
        return json.dumps(payload)

def setup_logging(level: str = "INFO"):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler])
```

### `README.md` template
```markdown
# Vera — magicpin AI Challenge Submission

**Team**: <name>  •  **Members**: <names>  •  **Model**: claude-sonnet-4-6

## Approach (200 words)
- 4-context prompt with per-category voice packs and per-trigger framings
- Anti-fabrication validator extracts numbers/proper-nouns from output and confirms each appears in input contexts
- Intent classifier: regex patterns first, LLM fallback for ambiguous cases
- Auto-reply detection: phrase signals OR repetition signal; progressive backoff (hint → wait → end)
- Customer-facing path: separate composer; consent gate; language pref overrides

## Tradeoffs
- Strict anti-fabrication occasionally reject valid creative phrasing → accepted to eliminate hallucination penalties
- Per-trigger framings cover ~14 kinds; rare kinds fall through to a generic framing → less specific but never wrong
- In-memory state — accepts test-window only; not production-grade

## What additional context would have helped
- Historical engagement rates per (merchant, trigger_kind) — would inform priority/skip decisions
- Translation pairs for category vocab in regional languages beyond Hindi (Tamil, Marathi, Telugu)
- Real merchant response rates for each compulsion lever — to choose levers data-driven instead of heuristically

## Run locally
\`\`\`bash
pip install -r requirements.txt
export LLM_API_KEY=sk-...
uvicorn bot.main:app --port 8080
python judge_simulator.py    # in another shell
\`\`\`

## Endpoints
GET /v1/healthz, GET /v1/metadata, POST /v1/context, POST /v1/tick, POST /v1/reply
```

---

## Test Plan

### Submission generation tests
1. `test_generate_submission_full` — run script against 30 canonical pairs; expect 30 JSONL lines, all valid JSON
2. `test_submission_no_urls` — every body in submission.jsonl passes URL validator
3. `test_submission_no_taboos` — every body passes taboo validator for its category
4. `test_submission_consent_handled` — pairs with missing consent are emitted as `{skipped: true, reason: consent_missing}`
5. `test_submission_deterministic` — re-run script; output is byte-identical

### Deployment validation
6. **Container build** — `docker build .` succeeds; image runs and `/v1/healthz` responds
7. **Public URL reachability** — `curl https://<deployed>/v1/healthz` returns 200 from external network
8. **Cold-start budget** — first request after idle returns within 5s

### End-to-end against deployed URL
9. **Warmup against deployed** — `BOT_URL=https://<deployed> python judge_simulator.py` with `TEST_SCENARIO="warmup"` passes
10. **Phase 2 short** — same with `TEST_SCENARIO="phase2_short"` passes
11. **All scenarios** — `TEST_SCENARIO="all"` passes warmup + auto_reply + intent + hostile
12. **Full evaluation** — `TEST_SCENARIO="full_evaluation"` runs to completion, average score ≥ 38/50

### Sustained-uptime test
13. **60-minute stability** — bot survives 60 minutes of continuous ticks without OOM, hang, or crash

### Logging validation
14. **Every action emits log** — grep stdout for `compose_action`; should see one per returned action
15. **Skip reasons logged** — every skip has `tick_skip_reason` with cause

---

## Expected Output

### `submission.jsonl` line example
```json
{"test_id": "T01", "merchant_id": "m_001_drmeera_dentist_delhi", "customer_id": null, "trigger_id": "trg_001_research_digest_dentists", "send_as": "vera", "body": "Dr. Meera, JIDA's Oct issue (p.14)...", "cta": "binary_yes_no", "suppression_key": "research:dentists:2026-W17", "rationale": "..."}
```

### Skipped entry
```json
{"test_id": "T07", "skipped": true, "reason": "consent_missing"}
```

### Healthz from deployed URL
```bash
$ curl https://vera-bot.onrender.com/v1/healthz
{"status": "ok", "uptime_seconds": 3742, "contexts_loaded": {"category": 5, "merchant": 50, "customer": 200, "trigger": 100}}
```

### Final judge_simulator.py output (fingers crossed)
```
============================================================
LLM JUDGE — FULL_EVALUATION — FINAL SUMMARY
============================================================
Messages scored: 30

  Avg Specificity        [████████████████████] 9/10
  Avg Category Fit       [████████████████░░░░] 8/10
  Avg Merchant Fit       [████████████████░░░░] 8/10
  Avg Decision Quality   [████████████████████] 9/10
  Avg Engagement         [████████████████░░░░] 8/10

  AVERAGE SCORE: 42/50 (84%)

  EXCELLENT
============================================================
```

---

## Dependencies (prior phases)
- **All of Phases 1–5** — Phase 6 packages and validates everything built before.

---

## Acceptance / Definition of Done

- [ ] `submission.jsonl` generated with 30 lines (or 30 entries including any consent-skipped markers)
- [ ] Every body in submission passes all 6 validators
- [ ] Submission generation is deterministic (re-runnable to byte-identical output)
- [ ] `Dockerfile` builds cleanly; image runs and serves /v1/healthz
- [ ] Bot deployed at a publicly-reachable URL; URL is in submission portal
- [ ] `judge_simulator.py` `TEST_SCENARIO="all"` passes against the deployed URL
- [ ] `judge_simulator.py` `TEST_SCENARIO="full_evaluation"` average ≥ 38/50 against deployed URL
- [ ] Bot survives a 60-minute continuous run (no OOM, no hang)
- [ ] Structured JSON logs confirmed for every key event
- [ ] `README.md` written and ≤ 1 page
- [ ] Repository tagged with submission version (e.g., `git tag v1.0-submission`)

---

## Estimated Effort
~6–8 hours: deployment setup (1–2h), submission script (1–2h), e2e validation runs and fixes (3–4h).
