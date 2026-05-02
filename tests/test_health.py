from __future__ import annotations


def test_health_initial(client):
    resp = client.get("/v1/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    counts = data["contexts_loaded"]
    assert counts["category"] == 0
    assert counts["merchant"] == 0
    assert counts["customer"] == 0
    assert counts["trigger"] == 0


def test_health_after_pushes(client):
    for i in range(3):
        client.post("/v1/context", json={
            "scope": "category",
            "context_id": f"cat_{i}",
            "version": 1,
            "payload": {"slug": f"cat_{i}"},
        })
    resp = client.get("/v1/healthz")
    assert resp.json()["contexts_loaded"]["category"] == 3


def test_health_uptime(client):
    resp = client.get("/v1/healthz")
    assert resp.json()["uptime_seconds"] >= 0


def test_metadata(client):
    resp = client.get("/v1/metadata")
    assert resp.status_code == 200
    data = resp.json()
    for field in ("team_name", "model", "version", "approach"):
        assert field in data, f"missing field: {field}"
