"""test titiler-eopf stac endpoints."""

import json
import os
from unittest.mock import patch
from urllib.parse import parse_qs

import pystac
from geojson_pydantic import Polygon
from owslib.wmts import WebMapTileService

from titiler.eopf.stac import (
    VALID_ASSET_OPTIONS,
    EOPFSimpleSTACReader,
    EOPFSTACAPIBackend,
    _parse_asset,
)
from titiler.stacapi.dependencies import APIParams, Search

collection_json = os.path.join(os.path.dirname(__file__), "fixtures", "collection.json")


def test_stac_reader(geozarr_stac):
    """test EOPFSimpleSTACReader."""
    stac = json.loads(geozarr_stac)
    simple_item = {
        "id": stac["id"],
        "collection": stac["collection"],
        "bbox": stac["bbox"],
        "properties": stac["properties"],
        "assets": stac["assets"],
    }
    with EOPFSimpleSTACReader(simple_item) as src:
        assert src.assets == ["reflectance"]

        info = src._get_asset_info("reflectance")
        assert info["url"].endswith(".zarr/measurements/reflectance")
        assert info["name"] == "reflectance"

        info = src._get_asset_info({"name": "reflectance", "variables": ["b02"]})
        assert info["url"].endswith(".zarr/measurements/reflectance")
        assert info["name"] == "reflectance"
        assert info["method_options"]["variables"] == ["b02"]

        info = src._get_asset_info({"name": "reflectance", "bands": ["blue"]})
        assert info["url"].endswith(".zarr/measurements/reflectance")
        assert info["name"] == "reflectance"
        assert info["method_options"]["variables"] == ["b02"]

        info = src.info(assets=src.assets)
        assert info["reflectance"]

        info = src.info(assets=[{"name": "reflectance", "bands": ["blue"]}])
        assert info["reflectance|bands=['blue']"]

        info = src.info(assets=[{"name": "reflectance", "variables": ["b02"]}])
        assert info["reflectance|variables=['b02']"]

        img = src.preview(assets=[{"name": "reflectance", "variables": ["b02"]}])
        assert img.band_descriptions == ["reflectance_b02"]


@patch("titiler.eopf.stac.EOPFSTACAPIBackend.get_assets")
def test_stacapi_backend(get_assets, geozarr_stac):
    """test EOPFSTACAPIBackend."""
    item = json.loads(geozarr_stac)
    get_assets.return_value = [
        {
            "id": item["id"],
            "collection": item["collection"],
            "bbox": item["bbox"],
            "properties": item["properties"],
            "assets": item["assets"],
        }
    ]

    with EOPFSTACAPIBackend(
        input=Search(), api_params=APIParams(url="http://endpoint.stac")
    ) as stac:
        pass

    with EOPFSTACAPIBackend(
        input=Search(), api_params=APIParams(url="http://endpoint.stac")
    ) as stac:
        assets = stac.assets_for_tile(0, 0, 0)
        assert len(assets) == 1
        assert isinstance(get_assets.call_args.args[0], Polygon)
        assert not get_assets.call_args.kwargs

    with EOPFSTACAPIBackend(
        input=Search(
            collections=["sentinel-2-l2a"],
            ids=["S2C_MSIL2A_20260316T142941_N0512_R139_T26WME_20260316T174811"],
        ),
        api_params=APIParams(url="http://endpoint.stac"),
    ) as stac:
        img, assets = stac.tile(
            8874,
            6325,
            14,
            search_options={"limit": 1},
            assets=[{"name": "reflectance", "bands": ["red", "green", "blue"]}],
        )
        assert (
            assets[0]
            == "sentinel-2-l2a/S2C_MSIL2A_20260316T142941_N0512_R139_T26WME_20260316T174811"
        )
        assert img.band_descriptions == [
            "reflectance_b04",
            "reflectance_b03",
            "reflectance_b02",
        ]
        assert (
            img.assets[0]["id"]
            == "S2C_MSIL2A_20260316T142941_N0512_R139_T26WME_20260316T174811"
        )
        assert img.assets[0]["collection"] == "sentinel-2-l2a"

        img, assets = stac.tile(
            8874,
            6325,
            14,
            search_options={"limit": 1},
            assets=[{"name": "reflectance", "variables": ["b04", "b03", "b02"]}],
        )
        assert (
            assets[0]
            == "sentinel-2-l2a/S2C_MSIL2A_20260316T142941_N0512_R139_T26WME_20260316T174811"
        )
        assert img.band_descriptions == [
            "reflectance_b04",
            "reflectance_b03",
            "reflectance_b02",
        ]
        assert (
            img.assets[0]["id"]
            == "S2C_MSIL2A_20260316T142941_N0512_R139_T26WME_20260316T174811"
        )
        assert img.assets[0]["collection"] == "sentinel-2-l2a"


@patch("titiler.eopf.stac.EOPFSTACAPIBackend._get_collection")
@patch("titiler.eopf.stac.EOPFSTACAPIBackend.get_assets")
def test_stac_collection_mosaic(get_assets, _get_collection, app, geozarr_stac):
    """test STAC /collections/{collection_id} endpoints."""
    item = json.loads(geozarr_stac)
    get_assets.return_value = [
        {
            "id": item["id"],
            "collection": item["collection"],
            "bbox": item["bbox"],
            "properties": item["properties"],
            "assets": item["assets"],
        }
    ]

    _get_collection.return_value = pystac.Collection.from_file(collection_json)

    response = app.get(
        "/collections/sentinel-2-l2a/WebMercatorQuad/tilejson.json",
        params={
            "assets": "reflectance|bands=red,green,blue",
            "minzoom": 12,
            "maxzoom": 14,
        },
    )
    assert response.status_code == 200
    resp = response.json()
    assert resp["minzoom"] == 12
    assert resp["maxzoom"] == 14
    assert "?assets=reflectance" in resp["tiles"][0]
    assert resp["bounds"] == [
        -179.99974060058594,
        -82.84402465820312,
        180.0,
        82.82318878173828,
    ]

    response = app.get(
        "/collections/sentinel-2-l2a/info",
    )
    assert response.status_code == 200
    resp = response.json()
    assert resp["bounds"] == [
        -179.99974060058594,
        -82.84402465820312,
        180.0,
        82.82318878173828,
    ]
    assert not resp["renders"]

    response = app.get(
        "/collections/sentinel-2-l2a/tiles/WebMercatorQuad/14/8874/6325/assets",
    )
    assert response.status_code == 200
    resp = response.json()
    assert len(resp) == 1
    assert (
        resp[0]["id"] == "S2C_MSIL2A_20260316T142941_N0512_R139_T26WME_20260316T174811"
    )

    response = app.get(
        "/collections/sentinel-2-l2a/tiles/WebMercatorQuad/14/8874/6325.png",
        params={
            "assets": "reflectance|bands=red,green,blue",
            "rescale": "0,1",
        },
    )
    assert response.status_code == 200

    response = app.get(
        "/collections/sentinel-2-l2a/point/15.0,37.9/assets",
    )
    assert response.status_code == 200
    resp = response.json()
    assert len(resp) == 1
    assert (
        resp[0]["id"] == "S2C_MSIL2A_20260316T142941_N0512_R139_T26WME_20260316T174811"
    )

    response = app.get(
        "/collections/sentinel-2-l2a/point/15.0,37.9",
        params={
            "assets": "reflectance|bands=red,green,blue",
        },
    )
    assert response.status_code == 200
    resp = response.json()
    assert len(resp["assets"]) == 1
    asset = resp["assets"][0]
    assert (
        asset["name"]
        == "sentinel-2-l2a/S2C_MSIL2A_20260316T142941_N0512_R139_T26WME_20260316T174811"
    )
    assert len(asset["values"]) == 3
    assert asset["band_descriptions"] == [
        "reflectance_b04",
        "reflectance_b03",
        "reflectance_b02",
    ]

    response = app.get(
        "/collections/sentinel-2-l2a/WMTSCapabilities.xml",
        params={
            "assets": "reflectance|bands=red,green,blue",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/xml"
    wmts = WebMapTileService(url="/wmts", xml=response.text.encode())
    layers = list(wmts.contents)
    assert len(layers) > 1

    assert "TiTiler Mosaic_WorldMercatorWGS84Quad_default" in layers
    layer = wmts["TiTiler Mosaic_WebMercatorQuad_default"]
    assert "WebMercatorQuad" in layer.tilematrixsetlinks
    assert ["TiTiler Mosaic_WebMercatorQuad_default"] == list(layer.styles.keys())
    assert ["image/png"] == layer.formats

    params = layer.resourceURLs[0]["template"].split("?")[1]
    query = parse_qs(params)
    assert query["assets"] == ["reflectance|bands=red,green,blue"]


def test_parse_asset():
    """test _parse_asset."""
    assert _parse_asset(["reflectance"]) == [{"name": "reflectance"}]
    assert _parse_asset(["reflectance|bidx=1,2"]) == [
        {"name": "reflectance", "indexes": [1, 2]}
    ]
    assert _parse_asset(["reflectance|expression=b04/b03"]) == [
        {"name": "reflectance", "expression": "b04/b03"}
    ]
    assert _parse_asset(["reflectance|bands=red,green,blue"]) == [
        {"name": "reflectance", "bands": ["red", "green", "blue"]}
    ]
    assert _parse_asset(["reflectance|variables=b02,b03,b04"]) == [
        {"name": "reflectance", "variables": ["b02", "b03", "b04"]}
    ]

    try:
        _parse_asset(["reflectance|bidx=invalid"])
    except ValueError as e:
        assert str(e) == (
            "Error parsing asset 'reflectance|bidx=invalid': Invalid bidx value 'invalid'. "
            "Expected comma-separated integers, e.g. 'bidx=1' or 'bidx=1,2,3'"
        )

    try:
        _parse_asset(["reflectance|unknown=foo"])
    except ValueError as e:
        assert str(e) == (
            "Error parsing asset 'reflectance|unknown=foo': Unknown asset option 'unknown'. "
            f"Valid options: {', '.join(sorted(VALID_ASSET_OPTIONS))}"
        )

    try:
        _parse_asset(["reflectance|invalidoption"])
    except ValueError as e:
        assert str(e) == (
            "Invalid asset option 'invalidoption' in 'reflectance|invalidoption'. "
            "Options must be in 'key=value' format. "
            f"Valid keys: {', '.join(sorted(VALID_ASSET_OPTIONS))}. "
            "Example: 'reflectance|bidx=1' or 'reflectance|variables=vv,vh'"
        )
