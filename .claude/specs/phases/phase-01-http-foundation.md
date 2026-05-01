# Phase 1 — HTTP Foundation & State Management

## Goal
Stand up the FastAPI server with all 5 endpoints reachable and a versioned, idempotent context store. No LLM yet — this phase delivers a "dumb but correct" bot that the judge can warm up against without errors.

---

## Why this phase first
The judge harness gates everything on `/v1/healthz` returning 200 and the bot accepting all 255 base contexts (5 categories + 50 merchants + 200 customers) before any composition is even attempted. If this phase isn't rock-solid, **nothing else works** — every later phase depends on contexts being correctly stored and retrievable.

---

## Capabilities Delivered

1. **All 5 HTTP endpoints reachable**
   - `GET /v1/healthz` returns live counts
   - `GET /v1/metadata` returns team identity
   - `POST /v1/context` accepts and persists context payloads
   - `POST /v1/tick` returns `{"actions": []}` (stub)
   - `POST /v1/reply` returns `{"action": "send", "body": "ack", ...}` (stub)

2. **Versioned context store** with three guarantees:
   - Re-posting same `(scope, context_id, version)` → 409 stale_version
   - Higher version atomically replaces prior
   - All four scopes supported (`category`, `merchant`, `customer`, `trigger`)

3. **Pydantic request validation** for all POST endpoints; malformed body → 400 with details.

4. **Healthz reflects live state**: `contexts_loaded.{category,merchant,customer,trigger}` counts update as contexts arrive.

5. **Single uvicorn process** running on port 8080.

---

## Files / Modules to Implement

```
bot/
├── __init__.py
├── main.py            # FastAPI app + 5 route handlers
├── models.py          # Pydantic schemas: CtxBody, TickBody, ReplyBody, etc.
├── state.py           # In-memory stores + StoredContext dataclass
├── config.py          # env loader: TEAM_NAME, TEAM_MEMBERS, MODEL, VERSION
└── services/
    ├── __init__.py
    └── context_service.py    # ContextService.put() with idempotency check

tests/
├── conftest.py        # pytest fixture: TestClient bound to fresh app
├── test_health.py     # healthz returns ok + 0 counts on fresh start
└── test_context.py    # idempotency, version replace, malformed payload

requirements.txt       # fastapi, uvicorn, pydantic
README.md              # placeholder
```

### `bot/main.py` (sketch)
```python
from fastapi import FastAPI
from datetime import datetime
import time
from .models import CtxBody, TickBody, ReplyBody, ContextResp
from .state import store
from .services.context_service import ContextService
from .config import settings

app = FastAPI(title="Vera Bot")
START = time.time()
ctx_service = ContextService(store)

@app.get("/v1/healthz")
async def healthz():
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - START),
        "contexts_loaded": store.counts_by_scope(),
    }

@app.get("/v1/metadata")
async def metadata():
    return settings.metadata_dict()

@app.post("/v1/context")
async def push_context(body: CtxBody):
    return ctx_service.put(body.scope, body.context_id, body.version, body.payload)

@app.post("/v1/tick")
async def tick(body: TickBody):
    return {"actions": []}    # stubbed; Phase 2 fills this

@app.post("/v1/reply")
async def reply(body: ReplyBody):
    return {"action": "send", "body": "ack — reply handler in phase 4",
            "cta": "open_ended", "rationale": "stub"}
```

### `bot/state.py` (sketch)
```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

@dataclass
class StoredContext:
    scope: str
    context_id: str
    version: int
    payload: dict[str, Any]
    stored_at: datetime

class StateStore:
    def __init__(self):
        self.contexts: dict[tuple[str, str], StoredContext] = {}
        self.conversations: dict[str, list] = {}
        self.suppressed_keys: set[str] = set()
        self.ended_conversations: set[str] = set()

    def counts_by_scope(self) -> dict[str, int]:
        out = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
        for (scope, _), _ in self.contexts.items():
            out[scope] = out.get(scope, 0) + 1
        return out

store = StateStore()
```

### `bot/services/context_service.py` (sketch)
```python
class ContextService:
    def __init__(self, store):
        self.store = store

    def put(self, scope: str, context_id: str, version: int, payload: dict) -> dict:
        if scope not in {"category", "merchant", "customer", "trigger"}:
            return {"accepted": False, "reason": "invalid_scope",
                    "details": f"scope must be one of category/merchant/customer/trigger"}

        key = (scope, context_id)
        cur = self.store.contexts.get(key)
        if cur and cur.version >= version:
            return {"accepted": False, "reason": "stale_version",
                    "current_version": cur.version}

        self.store.contexts[key] = StoredContext(
            scope=scope, context_id=context_id, version=version,
            payload=payload, stored_at=datetime.utcnow())
        return {"accepted": True,
                "ack_id": f"ack_{context_id}_v{version}",
                "stored_at": datetime.utcnow().isoformat() + "Z"}
```

---

## Test Plan

### Unit tests (pytest)
1. `test_health_initial` — fresh app: `contexts_loaded` all zeros
2. `test_health_after_pushes` — push 3 categories → counts.category == 3
3. `test_context_accepts_v1` — first push of `(merchant, m_001, v=1)` → 200 accepted
4. `test_context_rejects_stale` — push same again → 409 stale_version with current_version: 1
5. `test_context_replaces_higher_version` — push `(merchant, m_001, v=2)` → 200; healthz still shows 1 merchant
6. `test_context_invalid_scope` — `scope="invalid"` → 400 with reason=invalid_scope
7. `test_context_malformed` — missing `version` field → 422 (Pydantic auto)
8. `test_tick_stub` — `/v1/tick` returns `{"actions": []}`
9. `test_reply_stub` — `/v1/reply` returns valid action dict

### Integration test
- `test_warmup_full_dataset` — load `dataset/categories/*.json` and 50 generated merchants; push all to `/v1/context`; verify healthz shows 5/50 counts.

### Judge-simulator scenario
```bash
# Edit judge_simulator.py: TEST_SCENARIO = "warmup"
python judge_simulator.py
```
Must produce:
```
[PASS] healthz (xxxms)
[PASS] metadata — Team: ..., Model: ...
[PASS] category/dentists (and 4 others)
[PASS] merchant/m_001 (and others)
```

---

## Expected Output

### Sample 1 — health check after warmup
```bash
$ curl http://localhost:8080/v1/healthz
{
  "status": "ok",
  "uptime_seconds": 124,
  "contexts_loaded": {"category": 5, "merchant": 50, "customer": 200, "trigger": 0}
}
```

### Sample 2 — push then re-push
```bash
$ curl -X POST -H "Content-Type: application/json" \
  -d @dataset/categories/dentists.json \
  http://localhost:8080/v1/context
{"accepted": true, "ack_id": "ack_dentists_v1", "stored_at": "..."}

# Re-push same version
$ curl -X POST ... (same body)
{"accepted": false, "reason": "stale_version", "current_version": 1}
```

### Sample 3 — version bump
```bash
$ curl -X POST ... (version: 2)
{"accepted": true, "ack_id": "ack_dentists_v2", "stored_at": "..."}
```

### Sample 4 — tick still empty
```bash
$ curl -X POST -d '{"now":"2026-04-26T10:00:00Z","available_triggers":[]}' \
  http://localhost:8080/v1/tick
{"actions": []}
```

---

## Dependencies (prior phases)
None. This is the foundation phase.

---

## Acceptance / Definition of Done

- [ ] All 5 endpoints respond with correct HTTP status codes
- [ ] `/v1/context` is idempotent on `(scope, context_id, version)` — same version returns 409
- [ ] `/v1/context` atomically replaces on higher version
- [ ] Healthz shows accurate counts by scope after pushes
- [ ] All 9 unit tests pass
- [ ] `python judge_simulator.py` with `TEST_SCENARIO="warmup"` prints all green
- [ ] `bot.py` runs cleanly under uvicorn (no warnings, no errors on startup)
- [ ] Code is type-hinted and passes `mypy --strict bot/`

---

## Estimated Effort
~4–6 hours for someone fluent in FastAPI. Mostly boilerplate + tests.
