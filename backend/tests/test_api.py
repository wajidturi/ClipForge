from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from clipforge.api.app import create_app
from clipforge.jobs.worker import Worker


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:  # runs lifespan: migrations + event hub
        yield c


def test_health(client: TestClient) -> None:
    r = client.get("/api/v1/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_system_and_doctor(client: TestClient) -> None:
    s = client.get("/api/v1/system").json()
    assert s["database"] == "sqlite" and s["cpu_cores"] >= 1
    d = client.get("/api/v1/system/doctor").json()
    assert {c["name"] for c in d["checks"]} >= {"ffmpeg", "disk", "gpu"}


def test_job_types_public_only(client: TestClient) -> None:
    types = {t["type"] for t in client.get("/api/v1/jobs/types").json()}
    assert "system.selftest" in types


def test_job_crud(client: TestClient) -> None:
    r = client.post(
        "/api/v1/jobs", json={"type": "system.selftest", "payload": {"steps": 2, "delay": 0}}
    )
    assert r.status_code == 201
    job = r.json()
    assert job["status"] == "queued"
    assert client.get(f"/api/v1/jobs/{job['id']}").json()["id"] == job["id"]
    page = client.get("/api/v1/jobs").json()
    assert [j["id"] for j in page["items"]] == [job["id"]]
    assert client.get("/api/v1/jobs", params={"status": "failed"}).json()["items"] == []

    cancelled = client.post(f"/api/v1/jobs/{job['id']}/cancel").json()
    assert cancelled["status"] == "cancelled"
    assert client.post(f"/api/v1/jobs/{job['id']}/cancel").status_code == 409
    assert client.post(f"/api/v1/jobs/{job['id']}/retry").json()["status"] == "queued"


def test_unknown_job_type_rejected(client: TestClient) -> None:
    assert client.post("/api/v1/jobs", json={"type": "rm -rf"}).status_code == 422


def test_missing_job_404(client: TestClient) -> None:
    assert client.get("/api/v1/jobs/0190a0a0-0000-7000-8000-000000000000").status_code == 404


def test_pagination(client: TestClient) -> None:
    for _ in range(5):
        client.post("/api/v1/jobs", json={"type": "system.selftest"})
    first = client.get("/api/v1/jobs", params={"limit": 3}).json()
    assert len(first["items"]) == 3 and first["next_cursor"]
    second = client.get("/api/v1/jobs", params={"limit": 3, "cursor": first["next_cursor"]}).json()
    assert len(second["items"]) == 2 and second["next_cursor"] is None


def test_websocket_streams_job_progress(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/ws") as ws:
        job = client.post(
            "/api/v1/jobs", json={"type": "system.selftest", "payload": {"steps": 2, "delay": 0}}
        ).json()
        Worker("ws-test").run_once()
        seen = []
        while "succeeded" not in seen:
            msg = json.loads(ws.receive_text())
            if msg["type"] == "job.updated" and msg["job"]["id"] == job["id"]:
                seen.append(msg["job"]["status"])
        assert seen[-1] == "succeeded"


def test_openapi_lists_routes(client: TestClient) -> None:
    paths = client.get("/api/v1/openapi.json").json()["paths"]
    assert {"/api/v1/health", "/api/v1/jobs", "/api/v1/jobs/{job_id}/cancel"} <= set(paths)
