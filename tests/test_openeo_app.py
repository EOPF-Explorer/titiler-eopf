"""test OpenEO app."""

import os
from collections.abc import Generator
from typing import Any
from unittest.mock import patch

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
    monkeypatch.setenv("TITILER_OPENEO_CACHE_DISABLE", "true")

    from titiler.eopf.openeo.main import app

    with TestClient(app) as app:
        yield app


@patch("titiler.openeo.stacapi.Client")
def test_openeo_collections(client, openeo_app):
    """Test collections endpoint."""
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
