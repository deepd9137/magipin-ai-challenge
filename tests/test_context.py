from __future__ import annotations

import pytest


def push(client, scope, ctx_id, version=1, payload=None):
    return client.post("/v1/context", json={
        "scope": scope,
        "context_id": ctx_id,
        "version": version,
        "payload": payload or {"data": "test"},
    })


# ── Accept / idempotency ──────────────────────────────────────────────────

def test_context_accepts_first_push(client):
    resp = push(client, "merchant", "m_001", version=1)
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] is True
    assert "ack_id" in data
    assert "stored_at" in data


def test_context_rejects_same_version(client):
    push(client, "merchant", "m_001", version=1)
    resp = push(client, "merchant", "m_001", version=1)
    assert resp.status_code == 409
    data = resp.json()
    assert data["accepted"] is False
    assert data["reason"] == "stale_version"
    assert data["current_version"] == 1


def test_context_rejects_lower_version(client):
    push(client, "merchant", "m_001", version=5)
    resp = push(client, "merchant", "m_001", version=3)
    assert resp.status_code == 409
    data = resp.json()
    assert data["current_version"] == 5


def test_context_replaces_higher_version(client):
    push(client, "merchant", "m_001", version=1)
    resp = push(client, "merchant", "m_001", version=2, payload={"updated": True})
    assert resp.status_code == 200
    assert resp.json()["accepted"] is True


def test_context_version_replace_does_not_increase_count(client):
    push(client, "merchant", "m_001", version=1)
    push(client, "merchant", "m_001", version=2)
    counts = client.get("/v1/healthz").json()["contexts_loaded"]
    assert counts["merchant"] == 1


# ── Scope validation ──────────────────────────────────────────────────────

def test_context_invalid_scope(client):
    resp = push(client, "invalid_scope", "id_001", version=1)
    assert resp.status_code == 400
    data = resp.json()
    assert data["accepted"] is False
    assert data["reason"] == "invalid_scope"


def test_context_malformed_missing_version(client):
    resp = client.post("/v1/context", json={
        "scope": "merchant",
        "context_id": "m_001",
        "payload": {},
    })
    assert resp.status_code == 422


def test_context_malformed_missing_scope(client):
    resp = client.post("/v1/context", json={
        "context_id": "m_001",
        "version": 1,
        "payload": {},
    })
    assert resp.status_code == 422


# ── All four scopes accepted ──────────────────────────────────────────────

@pytest.mark.parametrize("scope", ["category", "merchant", "customer", "trigger"])
def test_all_scopes_accepted(client, scope):
    resp = push(client, scope, f"test_{scope}_id", version=1)
    assert resp.status_code == 200
    assert resp.json()["accepted"] is True


# ── Tick / Reply stubs still work ─────────────────────────────────────────

def test_tick_returns_list(client):
    resp = client.post("/v1/tick", json={"now": "2026-04-26T10:00:00Z", "available_triggers": []})
    assert resp.status_code == 200
    assert resp.json()["actions"] == []


def test_reply_stub(client):
    resp = client.post("/v1/reply", json={
        "conversation_id": "conv_001",
        "merchant_id": "m_001",
        "from_role": "merchant",
        "message": "Hello",
        "turn_number": 1,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] in ("send", "wait", "end")
