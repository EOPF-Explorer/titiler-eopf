"""Test titiler.eopf /external endpoints."""

from urllib.parse import parse_qs

from owslib.wmts import WebMapTileService

from .conftest import parse_img


def test_dataset(app, geozarr_dataset):
    """Test /datasets routes."""
    response = app.get("/external/dataset", params={"url": f"file://{geozarr_dataset}"})
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    response = app.get(
        "/external/dataset/groups", params={"url": f"file://{geozarr_dataset}"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == ["/measurements/reflectance"]

    response = app.get(
        "/external/dataset/keys", params={"url": f"file://{geozarr_dataset}"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == [
        "/measurements/reflectance:b02",
        "/measurements/reflectance:b03",
        "/measurements/reflectance:b04",
        "/measurements/reflectance:b05",
        "/measurements/reflectance:b06",
        "/measurements/reflectance:b07",
        "/measurements/reflectance:b08",
        "/measurements/reflectance:b11",
        "/measurements/reflectance:b12",
        "/measurements/reflectance:b8a",
    ]

    response = app.get(
        "/external/dataset/dict", params={"url": f"file://{geozarr_dataset}"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert set(response.json()) == {
        ".",
        "measurements",
        "measurements/reflectance",
        "measurements/reflectance/r10m",
        "measurements/reflectance/r20m",
        "measurements/reflectance/r60m",
        "measurements/reflectance/r120m",
    }


def test_preview(app, geozarr_dataset):
    """Test preview routes."""

    response = app.get(
        "/external/preview.png",
        params={
            "url": f"file://{geozarr_dataset}",
            "variables": "/measurements/reflectance:b02",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    profile = parse_img(response.content)
    assert profile["count"] == 2
    assert profile["dtype"] == "uint8"

    response = app.get(
        "/external/preview.png",
        params=(
            ("url", f"file://{geozarr_dataset}"),
            ("variables", "/measurements/reflectance:b04"),
            ("variables", "/measurements/reflectance:b03"),
            ("variables", "/measurements/reflectance:b02"),
            ("rescale", "0,1"),
        ),
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    profile = parse_img(response.content)
    assert profile["count"] == 4
    assert profile["dtype"] == "uint8"


def test_wmts(app, geozarr_dataset):
    """Test wmts routes."""
    response = app.get(
        "/external/WMTSCapabilities.xml",
        params={
            "url": f"file://{geozarr_dataset}",
            "variables": "/measurements/reflectance:b02",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/xml"

    wmts = WebMapTileService(url="/external/wmts", xml=response.text.encode())
    layers = list(wmts.contents)
    assert len(layers) > 1

    assert f"file://{geozarr_dataset}_WorldMercatorWGS84Quad_default" in layers
    layer = wmts[f"file://{geozarr_dataset}_WorldMercatorWGS84Quad_default"]
    assert "WorldMercatorWGS84Quad" in layer.tilematrixsetlinks
    assert ["image/png"] == layer.formats

    params = layer.resourceURLs[0]["template"].split("?")[1]
    query = parse_qs(params)
    assert query["variables"] == ["/measurements/reflectance:b02"]


def test_dataset_3d(app, geozarr_3d_dataset):
    """Test /datasets routes."""
    response = app.get(
        "/external/dataset/groups", params={"url": f"file://{geozarr_3d_dataset}"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == ["/measurements/reflectance"]

    response = app.get(
        "/external/dataset/keys", params={"url": f"file://{geozarr_3d_dataset}"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == [
        "/measurements/reflectance:b02",
        "/measurements/reflectance:b03",
        "/measurements/reflectance:b04",
        "/measurements/reflectance:b05",
        "/measurements/reflectance:b06",
        "/measurements/reflectance:b07",
        "/measurements/reflectance:b08",
        "/measurements/reflectance:b11",
        "/measurements/reflectance:b12",
        "/measurements/reflectance:b8a",
    ]

    response = app.get("/external/info", params={"url": f"file://{geozarr_3d_dataset}"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert list(response.json()) == [
        "/measurements/reflectance:b02",
        "/measurements/reflectance:b03",
        "/measurements/reflectance:b04",
        "/measurements/reflectance:b05",
        "/measurements/reflectance:b06",
        "/measurements/reflectance:b07",
        "/measurements/reflectance:b08",
        "/measurements/reflectance:b11",
        "/measurements/reflectance:b12",
        "/measurements/reflectance:b8a",
    ]
    info = response.json()["/measurements/reflectance:b02"]
    assert len(info["band_descriptions"]) == 2
    assert info["band_descriptions"][0][0] == "b1"
    assert info["band_descriptions"][0][1] == "2022-01-01T00:00:00.000000000"
    assert info["name"] == "b02"
    assert "time" in info["dimensions"]
    assert info["count"] == 2

    response = app.get(
        "/external/info",
        params={
            "url": f"file://{geozarr_3d_dataset}",
            "variables": "/measurements/reflectance:b02",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert list(response.json()) == [
        "/measurements/reflectance:b02",
    ]

    response = app.get(
        "/external/info",
        params={
            "url": f"file://{geozarr_3d_dataset}",
            "variables": "/measurements/reflectance:b02",
            "sel": "time=nearest::2022-01-03T00:00:00.000000000",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert list(response.json()) == [
        "/measurements/reflectance:b02",
    ]
    info = response.json()["/measurements/reflectance:b02"]
    assert len(info["band_descriptions"]) == 1
    assert info["band_descriptions"][0][0] == "b1"
    assert info["band_descriptions"][0][1] == "2022-01-02T00:00:00.000000000"
    assert info["name"] == "b02"
    assert "time" not in info["dimensions"]
    assert info["count"] == 1
