from __future__ import annotations

import time

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from bot.config import settings
from bot.models import CtxBody, ReplyBody, TickBody
from bot.services.context_service import ContextService
from bot.state import store

app = FastAPI(title="Vera Bot")

_START = time.time()
ctx_service = ContextService(store)


@app.get("/v1/healthz")
async def healthz() -> dict:
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - _START),
        "contexts_loaded": store.counts_by_scope(),
    }


@app.get("/v1/metadata")
async def metadata() -> dict:
    return settings.metadata_dict()


@app.post("/v1/context")
async def push_context(body: CtxBody) -> JSONResponse:
    status_code, result = ctx_service.put(
        body.scope, body.context_id, body.version, body.payload
    )
    return JSONResponse(content=result, status_code=status_code)


@app.post("/v1/tick")
async def tick(body: TickBody) -> dict:
    # Stub — Phase 2 wires in the LLM composer
    return {"actions": []}


@app.post("/v1/reply")
async def reply(body: ReplyBody) -> dict:
    # Stub — Phase 4 wires in the intent classifier and reply handler
    return {
        "action": "send",
        "body": "ack",
        "cta": "open_ended",
        "rationale": "stub",
    }
