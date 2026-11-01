"""Tests for the application health endpoint."""

from fastapi.testclient import TestClient

from creditpilot.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "app": "CreditPilot",
        "version": "0.1.0",
        "mode": "demo",
    }
