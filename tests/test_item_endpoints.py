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
        "reflectance_root_b02",
        "reflectance_root_b03",
        "reflectance_root_b04",
        "reflectance_root_b05",
        "reflectance_root_b06",
        "reflectance_root_b07",
        "reflectance_root_b08",
        "reflectance_root_b11",
        "reflectance_root_b12",
        "reflectance_root_b8a",
    ]

    response = app.get(
        f"/collections/{collection}/items/{item}/info",
        params={"assets": "reflectance"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    infos = response.json()
    assert list(infos) == [
        "reflectance_root_b02",
        "reflectance_root_b03",
        "reflectance_root_b04",
        "reflectance_root_b05",
        "reflectance_root_b06",
        "reflectance_root_b07",
        "reflectance_root_b08",
        "reflectance_root_b11",
        "reflectance_root_b12",
        "reflectance_root_b8a",
    ]

    response = app.get(
        f"/collections/{collection}/items/{item}/info",
        params={"assets": "reflectance|bands=b02,b03"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    infos = response.json()
    assert "reflectance|bands=['b02','b03']_b02" in infos
    assert "reflectance|bands=['b02','b03']_b03" in infos

    info = infos["reflectance|bands=['b02','b03']_b02"]
    assert len(info["band_descriptions"]) == 1
    assert info["band_descriptions"] == [["b1", "b02"]]
    assert info["dimensions"] == ["y", "x"]


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
        "reflectance_root_b02",
        "reflectance_root_b03",
        "reflectance_root_b04",
        "reflectance_root_b05",
        "reflectance_root_b06",
        "reflectance_root_b07",
        "reflectance_root_b08",
        "reflectance_root_b11",
        "reflectance_root_b12",
        "reflectance_root_b8a",
    ]

    response = app.get(
        f"/collections/{collection}/items/{item}/info",
        params={"assets": "reflectance|bands=b02,b03"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    infos = response.json()
    assert "reflectance|bands=['b02','b03']_b02" in infos
    assert "reflectance|bands=['b02','b03']_b03" in infos

    info = infos["reflectance|bands=['b02','b03']_b02"]
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
    assert (
        "reflectance|bands=['b02']&sel=['time=2022-01-01T00:00:00.000000000']_b02"
        in infos
    )

    info = infos[
        "reflectance|bands=['b02']&sel=['time=2022-01-01T00:00:00.000000000']_b02"
    ]
    assert len(info["band_descriptions"]) == 1
    assert info["band_descriptions"] == [["b1", "2022-01-01T00:00:00.000000000"]]
    assert info["dimensions"] == ["y", "x"]
