import pytest
from fastapi.testclient import TestClient


def test_context_accepts_v1(client: TestClient, ctx_payload: dict) -> None:
    r = client.post("/v1/context", json=ctx_payload)
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] is True
    assert "ack_id" in body
    assert "stored_at" in body


def test_context_rejects_same_version(client: TestClient, ctx_payload: dict) -> None:
    client.post("/v1/context", json=ctx_payload)
    r = client.post("/v1/context", json=ctx_payload)
    assert r.status_code == 409
    body = r.json()
    assert body["accepted"] is False
    assert body["reason"] == "stale_version"
    assert body["current_version"] == 1


def test_context_replaces_higher_version(client: TestClient, ctx_payload: dict) -> None:
    client.post("/v1/context", json=ctx_payload)

    v2 = {**ctx_payload, "version": 2, "payload": {"identity": {"name": "Updated"}}}
    r = client.post("/v1/context", json=v2)
    assert r.status_code == 200
    assert r.json()["accepted"] is True

    # Count should still be 1, not 2
    counts = client.get("/v1/healthz").json()["contexts_loaded"]
    assert counts["merchant"] == 1


def test_context_rejects_lower_version_after_higher(client: TestClient, ctx_payload: dict) -> None:
    v2 = {**ctx_payload, "version": 2}
    client.post("/v1/context", json=v2)

    r = client.post("/v1/context", json=ctx_payload)  # version 1 < 2
    assert r.status_code == 409
    body = r.json()
    assert body["reason"] == "stale_version"
    assert body["current_version"] == 2


def test_context_invalid_scope(client: TestClient) -> None:
    r = client.post("/v1/context", json={
        "scope": "invalid_scope",
        "context_id": "x",
        "version": 1,
        "payload": {},
    })
    assert r.status_code == 400
    body = r.json()
    assert body["accepted"] is False
    assert body["reason"] == "invalid_scope"


def test_context_malformed_missing_version(client: TestClient) -> None:
    r = client.post("/v1/context", json={
        "scope": "merchant",
        "context_id": "m_001",
        "payload": {},
    })
    assert r.status_code == 422  # Pydantic validation error


def test_tick_stub(client: TestClient) -> None:
    r = client.post("/v1/tick", json={"now": "2026-04-26T10:00:00Z", "available_triggers": []})
    assert r.status_code == 200
    assert r.json() == {"actions": []}


def test_reply_stub(client: TestClient) -> None:
    r = client.post("/v1/reply", json={
        "conversation_id": "conv_001",
        "merchant_id": "m_001",
        "from_role": "merchant",
        "message": "Hello",
        "received_at": "2026-04-26T10:00:00Z",
        "turn_number": 2,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["action"] in ("send", "wait", "end")


def test_all_four_scopes_accepted(client: TestClient) -> None:
    scopes = ["category", "merchant", "customer", "trigger"]
    for scope in scopes:
        r = client.post("/v1/context", json={
            "scope": scope,
            "context_id": f"test_{scope}",
            "version": 1,
            "payload": {"test": True},
        })
        assert r.status_code == 200, f"scope={scope} was rejected"

    counts = client.get("/v1/healthz").json()["contexts_loaded"]
    assert counts == {"category": 1, "merchant": 1, "customer": 1, "trigger": 1}
