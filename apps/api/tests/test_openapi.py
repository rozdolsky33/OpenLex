"""Guards the OpenAPI spec endpoint FastAPI generates automatically (/openapi.json, /docs) --
regression coverage for `main.py` never setting `openapi_url=None`/`docs_url=None`.

Uses TestClient without a `with` block so the app's lifespan (embedding-model preload) never
runs -- neither route needs it, and this keeps the test fast and independent of a live DB.
"""

from fastapi.testclient import TestClient
from openlex_api.main import app

client = TestClient(app)


def test_openapi_spec_is_available() -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200

    spec = response.json()
    assert spec["info"]["title"] == "OpenLex API"
    for path in ("/query", "/ingest", "/healthz"):
        assert path in spec["paths"], f"{path} missing from OpenAPI spec"


def test_docs_ui_is_available() -> None:
    response = client.get("/docs")
    assert response.status_code == 200
