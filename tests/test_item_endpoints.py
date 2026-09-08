"""Test titiler.eopf.main.app."""

from unittest.mock import patch
from urllib.parse import parse_qs

from owslib.wmts import WebMapTileService

from .conftest import parse_img


@patch("titiler.stacapi.dependencies.get_stac_item")
def test_info(get_stac_item, app, geozarr_stac):
    """Test info routes."""
    collection = geozarr_stac.collection_id
    item = geozarr_stac.id

    get_stac_item.return_value = geozarr_stac

    response = app.get(
        f"/collections/{collection}/items/{item}/assets",
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == ["reflectance"]

    # missing assets query param
    response = app.get(
        f"/collections/{collection}/items/{item}/info",
    )
    assert response.status_code == 422

    response = app.get(
        f"/collections/{collection}/items/{item}/info",
        params={"assets": ":all:"},
    )
    assert response.status_code == 200
    infos = response.json()
    assert list(infos) == [
        "reflectance_b02",
        "reflectance_b03",
        "reflectance_b04",
        "reflectance_b05",
        "reflectance_b06",
        "reflectance_b07",
        "reflectance_b08",
        "reflectance_b11",
        "reflectance_b12",
        "reflectance_b8a",
    ]

    response = app.get(
        f"/collections/{collection}/items/{item}/info",
        params={"assets": "reflectance"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    infos = response.json()
    assert list(infos) == [
        "reflectance_b02",
        "reflectance_b03",
        "reflectance_b04",
        "reflectance_b05",
        "reflectance_b06",
        "reflectance_b07",
        "reflectance_b08",
        "reflectance_b11",
        "reflectance_b12",
        "reflectance_b8a",
    ]

    response = app.get(
        f"/collections/{collection}/items/{item}/info",
        params={"assets": "reflectance|bands=b02,b03"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    infos = response.json()
    assert "reflectance_b02" in infos
    assert "reflectance_b03" in infos

    info = infos["reflectance_b02"]
    assert len(info["band_descriptions"]) == 1
    assert info["band_descriptions"] == [["b1", "b02"]]
    assert info["dimensions"] == ["y", "x"]

    response = app.get(
        f"/collections/{collection}/items/{item}/info",
        params={"assets": "reflectance|bands=red"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    infos = response.json()
    assert infos["reflectance_b04"]

    response = app.get(
        f"/collections/{collection}/items/{item}/statistics",
        params={"assets": "reflectance|expression=b02+b04"},
    )


@patch("titiler.stacapi.dependencies.get_stac_item")
def test_statistics(get_stac_item, app, geozarr_stac):
    """Test /statistics routes."""
    collection = geozarr_stac.collection_id
    item = geozarr_stac.id

    get_stac_item.return_value = geozarr_stac

    response = app.get(
        f"/collections/{collection}/items/{item}/statistics",
        params={"assets": "reflectance|bands=red"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    infos = response.json()
    assert infos["b1"]
    assert infos["b1"]["description"] == "reflectance_b04"

    response = app.get(
        f"/collections/{collection}/items/{item}/statistics",
        params={"assets": "reflectance|expression=b02+b04"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    infos = response.json()
    assert infos["b1"]
    assert infos["b1"]["description"] == "reflectance_b02+b04"


@patch("titiler.stacapi.dependencies.get_stac_item")
def test_tiljeson(get_stac_item, app, geozarr_stac):
    """Test /tilejson routes."""
    collection = geozarr_stac.collection_id
    item = geozarr_stac.id

    get_stac_item.return_value = geozarr_stac

    response = app.get(
        f"/collections/{collection}/items/{item}/WebMercatorQuad/tilejson.json",
    )
    assert response.status_code == 422

    response = app.get(
        f"/collections/{collection}/items/{item}/WebMercatorQuad/tilejson.json",
        params={"assets": "reflectance|bands=b02,b03,b04", "rescale": "0,1"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"


@patch("titiler.stacapi.dependencies.get_stac_item")
def test_preview(get_stac_item, app, geozarr_stac):
    """Test preview routes."""
    collection = geozarr_stac.collection_id
    item = geozarr_stac.id

    get_stac_item.return_value = geozarr_stac

    response = app.get(
        f"/collections/{collection}/items/{item}/preview.png",
        params={"assets": "reflectance|bands=b02"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    profile = parse_img(response.content)
    assert profile["count"] == 2
    assert profile["dtype"] == "uint8"

    response = app.get(
        f"/collections/{collection}/items/{item}/preview.png",
        params=(
            ("assets", "reflectance|bands=b04"),
            ("assets", "reflectance|bands=b03"),
            ("assets", "reflectance|bands=b02"),
            ("rescale", "0,1"),
        ),
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    profile = parse_img(response.content)
    assert profile["count"] == 4
    assert profile["dtype"] == "uint8"

    response = app.get(
        f"/collections/{collection}/items/{item}/preview.png",
        params=(
            ("assets", "reflectance|bands=b04,b03,b02"),
            ("rescale", "0,1"),
        ),
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    profile = parse_img(response.content)
    assert profile["count"] == 4
    assert profile["dtype"] == "uint8"


@patch("titiler.stacapi.dependencies.get_stac_item")
def test_wmts(get_stac_item, app, geozarr_stac):
    """Test wmts routes."""
    collection = geozarr_stac.collection_id
    item = geozarr_stac.id

    get_stac_item.return_value = geozarr_stac

    response = app.get(
        f"/collections/{collection}/items/{item}/WMTSCapabilities.xml",
        params={"assets": "reflectance|bands=b02"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/xml"

    wmts = WebMapTileService(url="/wmts", xml=response.text.encode())
    layers = list(wmts.contents)
    assert len(layers) > 1

    assert "TiTiler_WorldMercatorWGS84Quad_default" in layers
    layer = wmts["TiTiler_WorldMercatorWGS84Quad_default"]
    assert "WorldMercatorWGS84Quad" in layer.tilematrixsetlinks
    assert ["image/png"] == layer.formats

    params = layer.resourceURLs[0]["template"].split("?")[1]
    query = parse_qs(params)
    assert query["assets"] == ["reflectance|bands=b02"]


@patch("titiler.stacapi.dependencies.get_stac_item")
def test_dataset_3d(get_stac_item, app, geozarr_3d_stac):
    """Test /datasets routes."""
    collection = geozarr_3d_stac.collection_id
    item = geozarr_3d_stac.id

    get_stac_item.return_value = geozarr_3d_stac

    response = app.get(
        f"/collections/{collection}/items/{item}/assets",
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == ["reflectance"]

    response = app.get(
        f"/collections/{collection}/items/{item}/info",
        params={"assets": "reflectance"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    infos = response.json()
    assert list(infos) == [
        "reflectance_b02",
        "reflectance_b03",
        "reflectance_b04",
        "reflectance_b05",
        "reflectance_b06",
        "reflectance_b07",
        "reflectance_b08",
        "reflectance_b11",
        "reflectance_b12",
        "reflectance_b8a",
    ]

    response = app.get(
        f"/collections/{collection}/items/{item}/info",
        params={"assets": "reflectance|bands=b02,b03"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    infos = response.json()
    assert "reflectance_b02" in infos
    assert "reflectance_b03" in infos

    info = infos["reflectance_b02"]
    assert len(info["band_descriptions"]) == 2
    assert info["band_descriptions"] == [
        ["b1", "2022-01-01T00:00:00.000000000"],
        ["b2", "2022-01-02T00:00:00.000000000"],
    ]
    assert info["dimensions"] == ["time", "y", "x"]

    response = app.get(
        f"/collections/{collection}/items/{item}/info",
        params={
            "assets": "reflectance|bands=b02|sel=time=2022-01-01T00:00:00.000000000"
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    infos = response.json()
    assert "reflectance_b02" in infos

    info = infos["reflectance_b02"]
    assert len(info["band_descriptions"]) == 1
    assert info["band_descriptions"] == [["b1", "2022-01-01T00:00:00.000000000"]]
    assert info["dimensions"] == ["y", "x"]


@patch("titiler.stacapi.dependencies.get_stac_item")
def test_info_measurements(get_stac_item, app, geozarr_stac_measurements):
    """Test /info routes."""
    collection = geozarr_stac_measurements.collection_id
    item = geozarr_stac_measurements.id

    get_stac_item.return_value = geozarr_stac_measurements

    response = app.get(f"/collections/{collection}/items/{item}/assets")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == ["measurements"]

    response = app.get(
        f"/collections/{collection}/items/{item}/info",
        params={
            "assets": "measurements",
        },
    )
    assert list(response.json()) == [
        "measurements_reflectance_b02",
        "measurements_reflectance_b03",
        "measurements_reflectance_b04",
        "measurements_reflectance_b05",
        "measurements_reflectance_b06",
        "measurements_reflectance_b07",
        "measurements_reflectance_b08",
        "measurements_reflectance_b11",
        "measurements_reflectance_b12",
        "measurements_reflectance_b8a",
    ]
    info = response.json()["measurements_reflectance_b02"]
    assert len(info["band_descriptions"]) == 1
    assert info["band_descriptions"][0][0] == "b1"
    assert info["band_descriptions"][0][1] == "b02"
    assert info["name"] == "b02"
    assert info["dimensions"] == ["y", "x"]
    assert info["count"] == 1

    response = app.get(
        f"/collections/{collection}/items/{item}/info",
        params={
            "assets": "measurements|variables=/reflectance:b02",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"

    response = app.get(
        f"/collections/{collection}/items/{item}/preview",
        params={
            "assets": "measurements|expression=/reflectance:b02+/reflectance:b03",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
