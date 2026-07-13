"""Tests for apps/api/src/openlex_api/http_metrics.py's RED-metrics middleware."""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from openlex_api.http_metrics import HTTP_REQUESTS_TOTAL
from openlex_api.main import app
from openlex_shared.db import get_session

client = TestClient(app)


def _override_session() -> None:
    async def _get_session():
        yield AsyncMock()

    app.dependency_overrides[get_session] = _get_session


def _count(route: str) -> float:
    total = 0.0
    for metric in HTTP_REQUESTS_TOTAL.collect():
        for sample in metric.samples:
            if sample.name.endswith("_total") and sample.labels.get("route") == route:
                total += sample.value
    return total


def test_healthz_is_excluded_from_red_metrics() -> None:
    _override_session()
    before = _count("/healthz")

    client.get("/healthz")

    assert _count("/healthz") == before
    app.dependency_overrides.clear()


def test_response_carries_x_trace_id_header() -> None:
    _override_session()

    response = client.get("/healthz")

    assert "x-trace-id" in response.headers
    assert len(response.headers["x-trace-id"]) == 32
    int(response.headers["x-trace-id"], 16)  # must be valid hex
    app.dependency_overrides.clear()
