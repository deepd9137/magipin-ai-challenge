from __future__ import annotations

import logging
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .config import settings
from .models import CtxBody, ReplyBody, TickBody
from .services.context_service import ContextService
from .services.tick_service import TickService
from .state import store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(title="Vera Bot", version=settings.version)
START = time.time()

ctx_service = ContextService(store)

def _build_primary() -> "LLMProvider":
    provider = settings.llm_provider
    key = settings.llm_api_key
    model = settings.llm_model

    if provider == "anthropic":
        from .llm.anthropic_adapter import AnthropicAdapter
        return AnthropicAdapter(api_key=key, model=model)
    elif provider == "gemini":
        from .llm.gemini_adapter import GeminiAdapter
        return GeminiAdapter(api_key=key, model=model)
    elif provider == "openai":
        from .llm.openai_adapter import OpenAIAdapter
        return OpenAIAdapter(api_key=key, model=model)
    elif provider == "nvidia":
        from .llm.nvidia_adapter import NvidiaAdapter
        return NvidiaAdapter(api_key=key, model=model)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider!r}. Set LLM_PROVIDER env var.")


def _build_llm() -> "LLMProvider":
    from .llm.fallback_adapter import FallbackLLMProvider
    from .llm.adapter import LLMProvider

    chain: list[LLMProvider] = [_build_primary()]

    # Append NVIDIA fallback if key present and not already primary
    if settings.nvidia_key and settings.llm_provider != "nvidia":
        from .llm.nvidia_adapter import NvidiaAdapter
        chain.append(NvidiaAdapter(api_key=settings.nvidia_key, model=settings.nvidia_model))
        log = logging.getLogger(__name__)
        log.info("llm_fallback_registered provider=nvidia model=%s", settings.nvidia_model)

    if len(chain) == 1:
        return chain[0]
    return FallbackLLMProvider(chain)


_llm = _build_llm()
tick_service = TickService(store=store, llm=_llm)


# ── Routes ────────────────────────────────────────────────────────────────

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
    result = ctx_service.put(body.scope, body.context_id, body.version, body.payload)
    if not result.get("accepted") and result.get("reason") == "stale_version":
        return JSONResponse(status_code=409, content=result)
    if not result.get("accepted") and result.get("reason") == "invalid_scope":
        return JSONResponse(status_code=400, content=result)
    return result


@app.post("/v1/tick")
async def tick(body: TickBody):
    try:
        return await tick_service.handle(body.now, body.available_triggers)
    except Exception:
        logging.getLogger(__name__).exception("tick_unhandled_error")
        return {"actions": []}


@app.post("/v1/reply")
async def reply(body: ReplyBody):
    # Phase 2 stub — full reply handler lands in Phase 4
    conv_id = body.conversation_id
    if conv_id in store.ended_conversations:
        return {"action": "end", "rationale": "conversation already ended"}

    return {
        "action": "send",
        "body": "Thank you for your reply — our team will follow up shortly.",
        "cta": "open_ended",
        "rationale": "reply handler stub (Phase 4)",
    }
