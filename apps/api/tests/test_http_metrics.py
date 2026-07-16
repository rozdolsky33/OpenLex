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


def _count_class(route: str, status_class: str) -> float:
    total = 0.0
    for metric in HTTP_REQUESTS_TOTAL.collect():
        for sample in metric.samples:
            if (
                sample.name.endswith("_total")
                and sample.labels.get("route") == route
                and sample.labels.get("status_class") == status_class
            ):
                total += sample.value
    return total


def test_healthz_is_excluded_from_red_metrics() -> None:
    _override_session()
    before = _count("/healthz")

    client.get("/healthz")

    assert _count("/healthz") == before
    app.dependency_overrides.clear()


def test_response_carries_x_trace_id_header() -> None:
    response = client.get("/metrics")

    assert "x-trace-id" in response.headers
    assert len(response.headers["x-trace-id"]) == 32
    int(response.headers["x-trace-id"], 16)  # must be valid hex


def test_unhandled_exception_is_counted_as_5xx() -> None:
    """A handler that raises must still be recorded as a 5xx in the RED metrics.

    Otherwise the error-rate SLI (Executive "Error-free rate" panel, error alerts) is blind to
    unhandled-exception 500s -- exactly the failure that matters most. Regression guard for the
    observed anthropic 529 -> raw 500 that never showed up in openlex_http_requests_total.
    """

    async def _boom() -> None:
        raise RuntimeError("boom")

    app.add_api_route("/_test_boom", _boom, methods=["GET"])
    try:
        before = _count_class("/_test_boom", "5xx")
        # raise_server_exceptions=False so we see the 500 a real client sees, not the re-raise.
        local_client = TestClient(app, raise_server_exceptions=False)
        response = local_client.get("/_test_boom")

        assert response.status_code == 500
        assert _count_class("/_test_boom", "5xx") == before + 1
    finally:
        app.router.routes = [
            r for r in app.router.routes if getattr(r, "path", None) != "/_test_boom"
        ]
