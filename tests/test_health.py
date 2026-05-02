from fastapi.testclient import TestClient


def test_health_initial(client: TestClient) -> None:
    r = client.get("/v1/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["contexts_loaded"] == {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
    assert body["uptime_seconds"] >= 0


def test_health_after_pushes(client: TestClient) -> None:
    for i in range(3):
        client.post("/v1/context", json={
            "scope": "category",
            "context_id": f"cat_{i}",
            "version": 1,
            "payload": {"slug": f"cat_{i}"},
        })

    r = client.get("/v1/healthz")
    assert r.status_code == 200
    counts = r.json()["contexts_loaded"]
    assert counts["category"] == 3
    assert counts["merchant"] == 0
    assert counts["customer"] == 0
    assert counts["trigger"] == 0


def test_metadata_shape(client: TestClient) -> None:
    r = client.get("/v1/metadata")
    assert r.status_code == 200
    body = r.json()
    for key in ("team_name", "team_members", "model", "approach", "contact_email", "version", "submitted_at"):
        assert key in body
    assert isinstance(body["team_members"], list)
