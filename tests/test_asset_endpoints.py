"""Test titiler.eopf /assets endpoints."""

from unittest.mock import patch
from urllib.parse import parse_qs

from owslib.wmts import WebMapTileService

from .conftest import parse_img


@patch("titiler.eopf.stac.get_stac_item")
def test_dataset(get_stac_item, app, geozarr_stac):
    """Test /datasets routes."""
    collection = geozarr_stac.collection_id
    item = geozarr_stac.id
    asset = "reflectance"

    get_stac_item.return_value = geozarr_stac

    response = app.get(f"/collections/{collection}/items/{item}/assets/{asset}/dataset")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    response = app.get(
        f"/collections/{collection}/items/{item}/assets/{asset}/dataset/groups"
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == ["/"]

    response = app.get(
        f"/collections/{collection}/items/{item}/assets/{asset}/dataset/keys"
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == [
        "b02",
        "b03",
        "b04",
        "b05",
        "b06",
        "b07",
        "b08",
        "b11",
        "b12",
        "b8a",
    ]

    response = app.get(
        f"/collections/{collection}/items/{item}/assets/{asset}/dataset/dict"
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert set(response.json()) == {
        ".",
        "r10m",
        "r20m",
        "r60m",
        "r120m",
    }


@patch("titiler.eopf.stac.get_stac_item")
def test_info(get_stac_item, app, geozarr_stac):
    """Test /info routes."""
    collection = geozarr_stac.collection_id
    item = geozarr_stac.id
    asset = "reflectance"

    get_stac_item.return_value = geozarr_stac

    response = app.get(f"/collections/{collection}/items/{item}/assets/{asset}/info")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert list(response.json()) == [
        "b02",
        "b03",
        "b04",
        "b05",
        "b06",
        "b07",
        "b08",
        "b11",
        "b12",
        "b8a",
    ]
    info = response.json()["b02"]
    assert len(info["band_descriptions"]) == 1
    assert info["band_descriptions"][0][0] == "b1"
    assert info["band_descriptions"][0][1] == "b02"
    assert info["name"] == "b02"
    assert info["dimensions"] == ["y", "x"]
    assert info["count"] == 1
    assert info["group"] == "/"
    assert info["variable"] == "b02"

    response = app.get(
        f"/collections/{collection}/items/{item}/assets/{asset}/info",
        params={
            "variables": "b02",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert list(response.json()) == [
        "b02",
    ]


@patch("titiler.eopf.stac.get_stac_item")
def test_preview(get_stac_item, app, geozarr_stac):
    """Test preview routes."""
    collection = geozarr_stac.collection_id
    item = geozarr_stac.id
    asset = "reflectance"

    get_stac_item.return_value = geozarr_stac

    response = app.get(
        f"/collections/{collection}/items/{item}/assets/{asset}/preview.png",
        params={
            "variables": "b02",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    profile = parse_img(response.content)
    assert profile["count"] == 2
    assert profile["dtype"] == "uint8"

    response = app.get(
        f"/collections/{collection}/items/{item}/assets/{asset}/preview.png",
        params=(
            ("variables", "b04"),
            ("variables", "b03"),
            ("variables", "b02"),
            ("rescale", "0,1"),
        ),
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    profile = parse_img(response.content)
    assert profile["count"] == 4
    assert profile["dtype"] == "uint8"

    response = app.get(
        f"/collections/{collection}/items/{item}/assets/{asset}/preview.png",
        params=(
            ("expression", "b04+b03+b02"),
            ("rescale", "0,3"),
        ),
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    profile = parse_img(response.content)
    assert profile["count"] == 2
    assert profile["dtype"] == "uint8"


@patch("titiler.eopf.stac.get_stac_item")
def test_wmts(get_stac_item, app, geozarr_stac):
    """Test wmts routes."""
    collection = geozarr_stac.collection_id
    item = geozarr_stac.id
    asset = "reflectance"

    get_stac_item.return_value = geozarr_stac

    response = app.get(
        f"/collections/{collection}/items/{item}/assets/{asset}/WMTSCapabilities.xml",
        params={
            "variables": "b02",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/xml"

    wmts = WebMapTileService(
        url=f"/collections/{collection}/items/{item}/assets/{asset}/wmts",
        xml=response.text.encode(),
    )
    layers = list(wmts.contents)
    assert len(layers) > 1

    asset_url = geozarr_stac.assets["reflectance"].get_absolute_href()

    assert f"{asset_url}_WorldMercatorWGS84Quad_default" in layers
    layer = wmts[f"{asset_url}_WorldMercatorWGS84Quad_default"]
    assert "WorldMercatorWGS84Quad" in layer.tilematrixsetlinks
    assert ["image/png"] == layer.formats

    params = layer.resourceURLs[0]["template"].split("?")[1]
    query = parse_qs(params)
    assert query["variables"] == ["b02"]


@patch("titiler.eopf.stac.get_stac_item")
def test_dataset_3d(get_stac_item, app, geozarr_3d_stac):
    """Test /datasets routes."""
    collection = geozarr_3d_stac.collection_id
    item = geozarr_3d_stac.id
    asset = "reflectance"

    get_stac_item.return_value = geozarr_3d_stac

    response = app.get(
        f"/collections/{collection}/items/{item}/assets/{asset}/dataset/groups",
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == ["/"]

    response = app.get(
        f"/collections/{collection}/items/{item}/assets/{asset}/dataset/keys",
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == [
        "b02",
        "b03",
        "b04",
        "b05",
        "b06",
        "b07",
        "b08",
        "b11",
        "b12",
        "b8a",
    ]

    response = app.get(f"/collections/{collection}/items/{item}/assets/{asset}/info")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert list(response.json()) == [
        "b02",
        "b03",
        "b04",
        "b05",
        "b06",
        "b07",
        "b08",
        "b11",
        "b12",
        "b8a",
    ]
    info = response.json()["b02"]
    assert len(info["band_descriptions"]) == 2
    assert info["band_descriptions"][0][0] == "b1"
    assert info["band_descriptions"][0][1] == "2022-01-01T00:00:00.000000000"
    assert info["name"] == "b02"
    assert "time" in info["dimensions"]
    assert info["count"] == 2

    response = app.get(
        f"/collections/{collection}/items/{item}/assets/{asset}/info",
        params={
            "variables": "b02",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert list(response.json()) == [
        "b02",
    ]

    response = app.get(
        f"/collections/{collection}/items/{item}/assets/{asset}/info",
        params={
            "variables": "b02",
            "sel": "time=nearest::2022-01-03T00:00:00.000000000",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert list(response.json()) == [
        "b02",
    ]
    info = response.json()["b02"]
    assert len(info["band_descriptions"]) == 1
    assert info["band_descriptions"][0][0] == "b1"
    assert info["band_descriptions"][0][1] == "2022-01-02T00:00:00.000000000"
    assert info["name"] == "b02"
    assert "time" not in info["dimensions"]
    assert info["count"] == 1


@patch("titiler.eopf.stac.get_stac_item")
def test_viewer(get_stac_item, app, geozarr_3d_stac):
    """Test /viewer endpoint, with and without render presets in the query string."""
    collection = geozarr_3d_stac.collection_id
    item = geozarr_3d_stac.id
    asset = "reflectance"

    get_stac_item.return_value = geozarr_3d_stac

    response = app.get(
        f"/collections/{collection}/items/{item}/assets/{asset}/viewer",
    )
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    # the template pre-selects tile parameters found in the page query string
    assert "applyPresetFromQuery" in response.text

    response = app.get(
        f"/collections/{collection}/items/{item}/assets/{asset}/viewer",
        params={
            "variables": [
                "b04",
                "b03",
                "b02",
            ],
            "rescale": "0,1",
            "color_formula": "gamma rgb 1.3, sigmoidal rgb 6 0.1, saturation 1.2",
            "bidx": 1,
        },
    )
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    response = app.get("/api")
    assert response.status_code == 200

    parameters = {
        param["name"]
        for param in response.json()["paths"][
            "/collections/{collection_id}/items/{item_id}/assets/{asset_id}/viewer"
        ]["get"]["parameters"]
    }
    assert {
        "variables",
        "bidx",
        "rescale",
        "color_formula",
        "colormap_name",
    } <= parameters


@patch("titiler.eopf.stac.get_stac_item")
def test_chunks_extension(get_stac_item, app, geozarr_stac):
    """Test /chunks.html endpoint"""
    collection = geozarr_stac.collection_id
    item = geozarr_stac.id
    asset = "reflectance"

    get_stac_item.return_value = geozarr_stac

    response = app.get(
        f"/collections/{collection}/items/{item}/assets/{asset}/chunks.html",
    )
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


@patch("titiler.eopf.stac.get_stac_item")
def test_info_measurements(get_stac_item, app, geozarr_stac_measurements):
    """Test /info routes."""
    collection = geozarr_stac_measurements.collection_id
    item = geozarr_stac_measurements.id
    asset = "measurements"

    get_stac_item.return_value = geozarr_stac_measurements

    response = app.get(f"/collections/{collection}/items/{item}/assets/{asset}/info")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert list(response.json()) == [
        "/reflectance:b02",
        "/reflectance:b03",
        "/reflectance:b04",
        "/reflectance:b05",
        "/reflectance:b06",
        "/reflectance:b07",
        "/reflectance:b08",
        "/reflectance:b11",
        "/reflectance:b12",
        "/reflectance:b8a",
    ]
    info = response.json()["/reflectance:b02"]
    assert len(info["band_descriptions"]) == 1
    assert info["band_descriptions"][0][0] == "b1"
    assert info["band_descriptions"][0][1] == "b02"
    assert info["name"] == "b02"
    assert info["dimensions"] == ["y", "x"]
    assert info["count"] == 1
    assert info["group"] == "/reflectance"
    assert info["variable"] == "b02"

    response = app.get(
        f"/collections/{collection}/items/{item}/assets/{asset}/info",
        params={
            "variables": "/reflectance:b02",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert list(response.json()) == [
        "/reflectance:b02",
    ]

    response = app.get(
        f"/collections/{collection}/items/{item}/assets/{asset}/preview",
        params={
            "variables": "/reflectance:b02",
            "rescale": "0,1",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"

    response = app.get(
        f"/collections/{collection}/items/{item}/assets/{asset}/preview",
        params={
            "expression": "/reflectance:b02+/reflectance:b03",
            "rescale": "0,2",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


@patch("titiler.eopf.stac.get_stac_item")
def test_statistics(get_stac_item, app, geozarr_stac):
    """Test /statistics routes."""
    collection = geozarr_stac.collection_id
    item = geozarr_stac.id
    asset = "reflectance"

    get_stac_item.return_value = geozarr_stac

    response = app.get(
        f"/collections/{collection}/items/{item}/assets/{asset}/statistics",
        params={"variables": "b02"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    infos = response.json()
    assert infos["b1"]
    assert infos["b1"]["description"] == "b02"

    response = app.get(
        f"/collections/{collection}/items/{item}/assets/{asset}/statistics",
        params={"expression": "b02+b04"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    infos = response.json()
    assert infos["b1"]
    assert infos["b1"]["description"] == "b02+b04"
