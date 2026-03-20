"""test OpenEO app."""

import os
from collections.abc import Generator
from typing import Any
from unittest.mock import patch

import httpx
import pystac
import pytest
from starlette.testclient import TestClient

FIXTURES_DIRECTORY = os.path.join(os.path.dirname(__file__), "fixtures")

collection_json = os.path.join(FIXTURES_DIRECTORY, "collection.json")


@pytest.fixture
def openeo_app(monkeypatch) -> Generator[TestClient, Any, Any]:
    """Create App without authentication for testing."""
    store_path = os.path.join(FIXTURES_DIRECTORY, "openeo.json")

    monkeypatch.setenv("TITILER_OPENEO_STAC_API_URL", "https://fake.api.io/stac")
    monkeypatch.setenv("TITILER_OPENEO_STORE_URL", store_path)
    monkeypatch.setenv("TITILER_OPENEO_REQUIRE_AUTH", "false")
    monkeypatch.setenv("TITILER_OPENEO_AUTH_METHOD", "basic")
    monkeypatch.setenv(
        "TITILER_OPENEO_AUTH_USERS",
        '{"eopf": {"password": "password", "roles": ["user"]}}',
    )
    monkeypatch.setenv("TITILER_OPENEO_CACHE_DISABLE", "true")

    from titiler.eopf.openeo.main import app

    with TestClient(app) as app:
        yield app


@patch("titiler.openeo.stacapi.Client")
def test_openeo_app(client, openeo_app):
    """Test openeo endpoints."""

    response = openeo_app.get("/")
    assert response.status_code == 200

    response = openeo_app.get("/.well-known/openeo")
    assert response.status_code == 200

    response = openeo_app.get("/conformance")
    assert response.status_code == 200

    response = openeo_app.get("/processes")
    assert response.status_code == 200
    process_ids = [process["id"] for process in response.json()["processes"]]
    assert "load_collection" in process_ids
    assert "load_zarr" in process_ids

    client.open.return_value.get_collections.return_value = [
        pystac.Collection.from_file(collection_json)
    ]
    response = openeo_app.get("/collections")
    assert response.status_code == 200
    data = response.json()
    assert "collections" in data
    assert len(data["collections"]) == 1
    collection = data["collections"][0]
    assert collection["id"] == "sentinel-2-l2a"
    assert collection["version"] == "1.0.0"
    assert collection["cube:dimensions"]
    bands = collection["cube:dimensions"]["bands"]
    assert "reflectance|bands=b01" in bands["values"]

    client.open.return_value.get_collection.return_value = pystac.Collection.from_file(
        collection_json
    )
    response = openeo_app.get("/collections/sentinel-2-l2a")
    assert response.status_code == 200
    collection = response.json()
    assert collection["id"] == "sentinel-2-l2a"
    assert collection["version"] == "1.0.0"
    assert collection["cube:dimensions"]
    assert collection["cube:dimensions"]["bands"]
    bands = collection["cube:dimensions"]["bands"]
    assert "reflectance|bands=b01" in bands["values"]

    # Get Bearer Token using Basic Auth
    auth = httpx.BasicAuth(username="eopf", password="password")
    response = openeo_app.get("/credentials/basic", auth=auth)
    assert response.status_code == 200
    token = response.json().get("access_token")
    assert token

    bearer_token = f"Bearer basic//{token}"

    response = openeo_app.get("/me", headers={"Authorization": bearer_token})
    assert response.status_code == 200
    assert response.json()["user_id"] == "eopf"

    response = openeo_app.get("/services", headers={"Authorization": bearer_token})
    assert response.status_code == 200
    # Check no services are registered yet
    assert len(response.json()["services"]) == 0

    response = openeo_app.get(
        "/process_graphs", headers={"Authorization": bearer_token}
    )
    assert response.status_code == 200
    # Check no processes are registered yet
    assert len(response.json()["processes"]) == 0
