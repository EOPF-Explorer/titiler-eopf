"""test titiler-eopf reader"""

import os

import numpy
import pytest
import xarray
from geojson_pydantic import Polygon
from rio_tiler.errors import ExpressionMixingWarning

from titiler.eopf.reader import GeoZarrReader, MissingVariables

DATA_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
SENTINEL_2 = os.path.join(
    DATA_DIR,
    "eopf_geozarr",
    "S2C_MSIL2A_20260117T101351_N0511_R022_T32TQM_20260117T135312.zarr",
)


def test_open():
    """test GeoZarrReader open."""
    with GeoZarrReader(SENTINEL_2) as src:
        assert src.input == SENTINEL_2
        assert isinstance(src.datatree, xarray.DataTree)

        assert src.groups == ["/measurements/reflectance"]
        assert src.variables == [
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

        # We don't have the shape the whole dataset
        assert not src.height
        assert not src.width
        assert not src.transform

        # Default zooms to TMS zooms
        assert src.minzoom == 0
        assert src.maxzoom == 24

        # Because we don't have top-level (dataTree) metadata
        # we compute the min/max bounds for each groups
        assert src.crs == "EPSG:4326"
        assert src.bounds


def test_zooms_for_group():
    """test GeoZarrReader min/max zoom."""
    with GeoZarrReader(SENTINEL_2) as src:
        # Default zooms to TMS zooms
        assert src.minzoom == 0
        assert src.maxzoom == 24

        assert src.get_minzoom("/measurements/reflectance") == 7
        assert src.get_maxzoom("/measurements/reflectance") == 10


def test_info():
    """test info method."""
    with GeoZarrReader(SENTINEL_2) as src:
        # Default to all variables
        info = src.info()
        assert src.variables == list(info)
        info = src.info(variables=["/measurements/reflectance:b02"])
        info_b02 = info["/measurements/reflectance:b02"]
        assert info_b02.crs == "http://www.opengis.net/def/crs/EPSG/0/32632"
        assert info_b02.band_descriptions == [("b1", "b02")]
        assert info_b02.width == 915
        assert info_b02.height == 915


def test_tile():
    """test tile method."""
    with GeoZarrReader(SENTINEL_2) as src:
        bounds = src.bounds
        lon, lat = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2

        tile = src.tms.tile(lon, lat, 9)

        img = src.tile(*tile, variables=["/measurements/reflectance:b02"])
        assert img.band_names == ["b02"]
        assert img.data.shape == (1, 256, 256)

        img = src.tile(
            *tile,
            variables=[
                "/measurements/reflectance:b02",
                "/measurements/reflectance:b03",
            ],
        )
        assert img.band_names == ["b02", "b03"]
        assert img.data.shape == (2, 256, 256)

        img_expr = src.tile(
            *tile,
            expression="/measurements/reflectance:b02+/measurements/reflectance:b03",
        )
        assert img_expr.band_names == [
            "/measurements/reflectance:b02+/measurements/reflectance:b03"
        ]

        assert img_expr.data.shape == (1, 256, 256)
        numpy.testing.assert_equal(
            img_expr.array, numpy.ma.sum(img.array, axis=0, keepdims=True)
        )

        with pytest.warns(ExpressionMixingWarning):
            img = src.tile(
                *tile,
                variables=["/measurements/reflectance:b02"],
                expression="/measurements/reflectance:b02+/measurements/reflectance:b03",
            )
            assert img.band_names == [
                "/measurements/reflectance:b02+/measurements/reflectance:b03"
            ]
            assert img.data.shape == (1, 256, 256)

        with pytest.raises(MissingVariables):
            src.tile(*tile)


def test_point():
    """test point method."""
    with GeoZarrReader(SENTINEL_2) as src:
        bounds = src.bounds
        lon, lat = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
        pt = src.point(lon, lat, variables=["/measurements/reflectance:b02"])
        assert pt.band_names == ["b02"]
        assert pt.data.shape == (1,)

        pt = src.point(
            lon,
            lat,
            variables=[
                "/measurements/reflectance:b02",
                "/measurements/reflectance:b03",
            ],
        )
        assert pt.band_names == ["b02", "b03"]
        assert pt.data.shape == (2,)

        pt_expr = src.point(
            lon,
            lat,
            expression="/measurements/reflectance:b02+/measurements/reflectance:b03",
        )
        assert pt_expr.band_names == [
            "/measurements/reflectance:b02+/measurements/reflectance:b03"
        ]
        assert pt_expr.data.shape == (1,)
        assert pt_expr.data == pt.data[0] + pt.data[1]

        with pytest.warns(ExpressionMixingWarning):
            pt = src.point(
                lon,
                lat,
                variables=["/measurements/reflectance:b02"],
                expression="/measurements/reflectance:b02+/measurements/reflectance:b03",
            )
            assert pt.band_names == [
                "/measurements/reflectance:b02+/measurements/reflectance:b03"
            ]
            assert pt.data.shape == (1,)

        with pytest.raises(MissingVariables):
            src.point(lon, lat)


def test_statistics():
    """test statistics method."""
    with GeoZarrReader(SENTINEL_2) as src:
        with pytest.raises(NotImplementedError):
            src.statistics(variables=["/measurements/reflectance:b02"])


def test_preview():
    """test preview method."""
    with GeoZarrReader(SENTINEL_2) as src:
        img = src.preview(variables=["/measurements/reflectance:b02"], max_size=128)
        assert img.array.shape == (1, 128, 128)

        img = src.preview(
            variables=["/measurements/reflectance:b02"],
            max_size=128,
            dst_crs="epsg:4326",
        )
        assert img.array.shape == (1, 96, 128)


def test_part():
    """test part method."""
    with GeoZarrReader(SENTINEL_2) as src:
        bounds = src.bounds
        lon, lat = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
        tile = src.tms.tile(lon, lat, 12)
        bbox = src.tms.xy_bounds(tile)

        img = src.part(
            bbox,
            bounds_crs="epsg:3857",
            dst_crs="epsg:3857",
            variables=["/measurements/reflectance:b02"],
            width=256,
            height=256,
        )

        img_tile = src.tile(
            tile.x,
            tile.y,
            tile.z,
            variables=["/measurements/reflectance:b02"],
        )
        numpy.testing.assert_array_equal(img.array, img_tile.array)


def test_feature():
    """test feature method."""
    with GeoZarrReader(SENTINEL_2) as src:
        bounds = src.bounds
        lon, lat = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
        tile = src.tms.tile(lon, lat, 12)
        bbox = src.tms.bounds(tile)
        feat = Polygon.from_bounds(*bbox).model_dump(exclude_none=True)
        img = src.feature(feat, variables=["/measurements/reflectance:b02"])

    assert list(img.bounds) == [
        12.041015624999872,
        41.90227704096376,
        12.12890624999987,
        41.96765920367824,
    ]
