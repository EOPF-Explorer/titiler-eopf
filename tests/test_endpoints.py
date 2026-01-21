"""Test titiler.eopf.main.app."""

from .conftest import parse_img


def test_dataset(app):
    """Test /datasets routes."""
    response = app.get(
        "/collections/eopf_geozarr/items/S2C_MSIL2A_20260117T101351_N0511_R022_T32TQM_20260117T135312/dataset"
    )
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    response = app.get(
        "/collections/eopf_geozarr/items/S2C_MSIL2A_20260117T101351_N0511_R022_T32TQM_20260117T135312/dataset/groups"
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == ["/measurements/reflectance"]

    response = app.get(
        "/collections/eopf_geozarr/items/S2C_MSIL2A_20260117T101351_N0511_R022_T32TQM_20260117T135312/dataset/keys"
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == [
        "/measurements/reflectance:b01",
        "/measurements/reflectance:b02",
        "/measurements/reflectance:b03",
        "/measurements/reflectance:b04",
        "/measurements/reflectance:b05",
        "/measurements/reflectance:b06",
        "/measurements/reflectance:b07",
        "/measurements/reflectance:b09",
        "/measurements/reflectance:b11",
        "/measurements/reflectance:b12",
        "/measurements/reflectance:b8a",
    ]

    response = app.get(
        "/collections/eopf_geozarr/items/S2C_MSIL2A_20260117T101351_N0511_R022_T32TQM_20260117T135312/dataset/dict"
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert list(response.json()) == [
        ".",
        "measurements",
        "measurements/reflectance",
        "measurements/reflectance/r120m",
        "measurements/reflectance/r360m",
        "measurements/reflectance/r720m",
    ]


def test_preview(app):
    """Test preview routes."""
    response = app.get(
        "/collections/eopf_geozarr/items/S2C_MSIL2A_20260117T101351_N0511_R022_T32TQM_20260117T135312/preview.png",
        params={"variables": "/measurements/reflectance:b02", "rescale": "0,1"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    profile = parse_img(response.content)
    assert profile["count"] == 2
    assert profile["dtype"] == "uint8"

    response = app.get(
        "/collections/eopf_geozarr/items/S2C_MSIL2A_20260117T101351_N0511_R022_T32TQM_20260117T135312/preview.png",
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
