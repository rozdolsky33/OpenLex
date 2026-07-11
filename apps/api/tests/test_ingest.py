"""Tests for POST /ingest (apps/api/src/openlex_api/routers/ingest.py) -- the deliberate 501
boundary (ingestion runs in the worker container only, see the router's docstring)."""

from fastapi.testclient import TestClient
from openlex_api.main import app

client = TestClient(app)


def test_ingest_returns_not_implemented_pointing_at_the_worker() -> None:
    response = client.post("/ingest", json={"source": "statutes"})

    assert response.status_code == 501
    assert "worker container" in response.json()["detail"]


def test_ingest_still_validates_the_request_body_first() -> None:
    response = client.post("/ingest", json={"source": "not-a-real-source"})

    assert response.status_code == 422
