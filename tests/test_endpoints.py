"""Test titiler.eopf.main.app."""

from .conftest import parse_img


def test_dataset(app):
    """Test /datasets routes."""
    response = app.get(
        "/collections/eopf_geozarr/items/S2A_MSIL2A_20250704T094051_N0511_R036_T33SWB_20250704T115824/dataset"
    )
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    response = app.get("/collections/eopf_geozarr/items/optimized_pyramid/dataset")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    response = app.get(
        "/collections/eopf_geozarr/items/S2A_MSIL2A_20250704T094051_N0511_R036_T33SWB_20250704T115824/dataset/groups"
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == ["/measurements/reflectance/r60m"]

    response = app.get(
        "/collections/eopf_geozarr/items/optimized_pyramid/dataset/groups"
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == ["/measurements/reflectance"]

    response = app.get(
        "/collections/eopf_geozarr/items/S2A_MSIL2A_20250704T094051_N0511_R036_T33SWB_20250704T115824/dataset/keys"
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == [
        "/measurements/reflectance/r60m:b02",
        "/measurements/reflectance/r60m:b03",
        "/measurements/reflectance/r60m:b04",
    ]

    response = app.get("/collections/eopf_geozarr/items/optimized_pyramid/dataset/keys")
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
        "/collections/eopf_geozarr/items/S2A_MSIL2A_20250704T094051_N0511_R036_T33SWB_20250704T115824/dataset/dict"
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert list(response.json()) == [
        ".",
        "measurements",
        "measurements/reflectance",
        "measurements/reflectance/r60m",
        "measurements/reflectance/r60m/0",
        "measurements/reflectance/r60m/1",
        "measurements/reflectance/r60m/2",
    ]

    response = app.get("/collections/eopf_geozarr/items/optimized_pyramid/dataset/dict")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert list(response.json()) == [
        ".",
        "measurements",
        "measurements/reflectance",
        "measurements/reflectance/0",
        "measurements/reflectance/1",
        "measurements/reflectance/2",
        "measurements/reflectance/3",
    ]


def test_preview(app):
    """Test preview routes."""
    response = app.get(
        "/collections/eopf_geozarr/items/S2A_MSIL2A_20250704T094051_N0511_R036_T33SWB_20250704T115824/preview.png",
        params={"variables": "/measurements/reflectance/r60m:b02"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    profile = parse_img(response.content)
    assert profile["count"] == 2
    assert profile["dtype"] == "uint8"

    response = app.get(
        "/collections/eopf_geozarr/items/optimized_pyramid/preview.png",
        params={"variables": "/measurements/reflectance:b02"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    profile = parse_img(response.content)
    assert profile["count"] == 2
    assert profile["dtype"] == "uint8"

    response = app.get(
        "/collections/eopf_geozarr/items/optimized_pyramid/preview.png",
        params=(
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
