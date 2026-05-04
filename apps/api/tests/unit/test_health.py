"""Tests for the `/health` route."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_emits_request_id_header(client: TestClient) -> None:
    resp = client.get("/health")
    assert "X-Request-ID" in resp.headers
    assert resp.headers["X-Request-ID"]


def test_health_echoes_client_request_id(client: TestClient) -> None:
    rid = "deadbeef-1234-5678-9abc-def012345678"
    resp = client.get("/health", headers={"X-Request-ID": rid})
    assert resp.headers["X-Request-ID"] == rid
