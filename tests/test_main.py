"""Test titiler.eopf.main.app."""

import pytest


@pytest.mark.parametrize(
    "endpoint",
    [
        "/",
        "/conformance",
        "/api",
        "/api.html",
        "/algorithms",
        "/algorithms/hillshade",
        "/colorMaps",
        "/colorMaps/viridis",
        "/tileMatrixSets",
        "/tileMatrixSets/WebMercatorQuad",
        "/_mgmt/ping",
        "/_mgmt/health",
    ],
)
def test_get_routes(app, endpoint):
    """Test GET routes."""
    response = app.get(endpoint)
    assert response.status_code == 200


def test_health(app):
    """Test /healthz endpoint."""
    response = app.get("/_mgmt/health")
    assert response.status_code == 200
    resp = response.json()
    assert set(resp["versions"].keys()) == {
        "titiler",
        "gdal",
        "geos",
        "proj",
        "rasterio",
        "zarr",
        "xarray",
    }


def test_landing(app):
    """Test Landing Page routes."""
    response = app.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"

    content = response.json()
    assert content["title"] == "TiTiler application for EOPF datasets"

    response = app.get("/", params={"f": "html"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")

    response = app.get("/", headers={"Accept": "application/json"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"

    response = app.get("/", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_conformance(app):
    """Test Conformance Page routes."""
    response = app.get("/conformance")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"

    response = app.get("/conformance", params={"f": "html"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")

    response = app.get("/conformance", headers={"Accept": "application/json"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"

    response = app.get("/conformance", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
