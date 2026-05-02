import pytest
from fastapi.testclient import TestClient

import bot.main as bot_main
from bot.services.context_service import ContextService
from bot.state import StateStore


@pytest.fixture()
def client() -> TestClient:
    """Fresh StateStore + ContextService per test; shares the FastAPI app object."""
    fresh_store = StateStore()
    bot_main.store = fresh_store
    bot_main.ctx_service = ContextService(fresh_store)

    with TestClient(bot_main.app) as c:
        yield c


@pytest.fixture()
def ctx_payload() -> dict:
    return {
        "scope": "merchant",
        "context_id": "m_001",
        "version": 1,
        "payload": {"identity": {"name": "Test Merchant"}},
    }
