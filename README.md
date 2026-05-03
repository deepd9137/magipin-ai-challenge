# Vera — magicpin AI Challenge Submission

**Team:** Vera AI &nbsp;•&nbsp; **Member:** Deepanshu Pofare &nbsp;•&nbsp; **Model:** claude-sonnet-4-6

---

## Approach

Every outbound message is composed from four independently-versioned context layers — category voice profile, live merchant signals, specific trigger event, and (optionally) an individual customer — fed as a single structured prompt to Claude Sonnet 4.6 at `temperature=0`.

**Key design decisions:**

- **Per-trigger framing templates** — 20+ trigger kinds each have a dedicated prompt template that anchors the message on *why now* (e.g. `research_digest` leads with the source citation; `perf_dip` leads with a diagnosis and a reframe).
- **Category voice packs** — dentists get peer/clinical tone with taboos like "guaranteed" and "miracle"; gyms get coach/motivational tone; restaurants get operator-to-operator plain speech. The voice pack is injected into the system prompt to prevent generic copy.
- **Anti-fabrication validator** — after generation, every number, percentage, date, and proper noun in the body is extracted via regex and cross-checked against a flattened text representation of all input contexts. Any fact that doesn't appear in the inputs causes a retry (one retry, then skip).
- **Strict suppression dedup** — each fired `suppression_key` is stored in memory; subsequent ticks skip it silently.
- **Intent state machine** — replies are classified into `AUTO_REPLY | OPT_OUT | HOSTILE | INTENT_COMMIT | OFF_TOPIC | ENGAGED`; auto-replies follow a progressive backoff (hint → wait 4-24h → end); hostile/opt-out immediately end.
- **Customer-facing path** — separate composer with consent gate; `send_as=merchant_on_behalf`; language preference from the customer record overrides the merchant's default.

## Tradeoffs

| Decision | Accepted cost |
|---|---|
| Strict anti-fabrication rejects creative phrasing that happens to not match the exact context string | Eliminates hallucination penalties (−2 each); accepted lower creativity |
| `temperature=0` for reproducibility | Less linguistic variety across merchants in the same category |
| Single-process in-memory state | No HA; acceptable for 60-min test window |
| Per-trigger framing templates (~20) | Rare trigger kinds fall through to a generic framing — less specific but never wrong |

## What additional context would have helped most

1. **Historical engagement rates per (merchant, trigger_kind)** — would let us skip low-ROI triggers rather than composing and discarding them.
2. **Regional language pairs beyond Hindi** — Tamil, Marathi, Telugu merchants get English instead of code-mix.
3. **Real WhatsApp template approval status** — to generate pre-approved template names rather than synthetic ones.

## Run locally

```bash
# 1. Install
pip install -r requirements.txt

# 2. Configure (copy and fill in your API key)
cp .env.example .env
# Set LLM_API_KEY in .env

# 3. Start
uvicorn bot.main:app --host 0.0.0.0 --port 8080 --workers 1

# 4. Run tests (in another terminal)
pytest tests/ -v

# 5. Run judge simulator
python judge_simulator.py
```

## Generate submission.jsonl

```bash
python scripts/generate_submission.py \
    --pairs scripts/canonical_test_pairs.json \
    --output submission.jsonl \
    --dataset-dir dataset
```

## Deploy (Render)

1. Push this repo to GitHub.
2. Create a new **Web Service** on [render.com](https://render.com) pointing at the repo.
3. Set `LLM_API_KEY` in the Render environment dashboard (marked `sync: false` in `render.yaml`).
4. Render auto-detects `render.yaml` and configures the rest.

Alternatively:

```bash
docker build -t vera-bot .
docker run -p 8080:8080 -e LLM_API_KEY=sk-ant-... vera-bot
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/healthz` | Liveness probe |
| GET | `/v1/metadata` | Team identity |
| POST | `/v1/context` | Receive versioned context |
| POST | `/v1/tick` | Compose proactive messages |
| POST | `/v1/reply` | Handle merchant/customer replies |
