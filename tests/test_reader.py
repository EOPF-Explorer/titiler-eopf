"""test titiler-eopf reader"""

import os

import numpy
import pytest
import xarray
from rio_tiler.errors import ExpressionMixingWarning

from titiler.eopf.reader import GeoZarrReader, MissingVariables

DATA_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
SENTINEL_2 = os.path.join(
    DATA_DIR,
    "eopf_geozarr",
    "S2A_MSIL2A_20250704T094051_N0511_R036_T33SWB_20250704T115824.zarr",
)


def test_open():
    """test GeoZarrReader open."""
    with GeoZarrReader(SENTINEL_2) as src:
        assert src.input == SENTINEL_2
        assert isinstance(src.datatree, xarray.DataTree)

        assert src.groups == ["/measurements/reflectance/r60m"]
        assert src.variables == [
            "/measurements/reflectance/r60m:b02",
            "/measurements/reflectance/r60m:b03",
            "/measurements/reflectance/r60m:b04",
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

        assert src.get_minzoom("/measurements/reflectance/r60m") == 9
        assert src.get_maxzoom("/measurements/reflectance/r60m") == 11


def test_info():
    """test info method."""
    with GeoZarrReader(SENTINEL_2) as src:
        # Default to all variables
        info = src.info()
        assert src.variables == list(info)
        info = src.info(variables=["/measurements/reflectance/r60m:b02"])
        info_b02 = info["/measurements/reflectance/r60m:b02"]
        assert info_b02.crs == "http://www.opengis.net/def/crs/EPSG/0/32633"
        assert info_b02.band_descriptions == [("b1", "b02")]
        assert info_b02.width == 1830
        assert info_b02.height == 1830


def test_tile():
    """test tile method."""
    with GeoZarrReader(SENTINEL_2) as src:
        bounds = src.bounds
        lon, lat = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2

        tile = src.tms.tile(lon, lat, 9)

        img = src.tile(*tile, variables=["/measurements/reflectance/r60m:b02"])
        assert img.band_names == ["b02"]
        assert img.data.shape == (1, 256, 256)

        img = src.tile(
            *tile,
            variables=[
                "/measurements/reflectance/r60m:b02",
                "/measurements/reflectance/r60m:b03",
            ],
        )
        assert img.band_names == ["b02", "b03"]
        assert img.data.shape == (2, 256, 256)

        img_expr = src.tile(
            *tile,
            expression="/measurements/reflectance/r60m:b02+/measurements/reflectance/r60m:b03",
        )
        assert img_expr.band_names == [
            "/measurements/reflectance/r60m:b02+/measurements/reflectance/r60m:b03"
        ]
        assert img_expr.data.shape == (1, 256, 256)
        numpy.testing.assert_equal(
            img_expr.data, numpy.ma.sum(img.data, axis=0, keepdims=True)
        )

        with pytest.warns(ExpressionMixingWarning):
            img = src.tile(
                *tile,
                variables=["/measurements/reflectance/r60m:b02"],
                expression="/measurements/reflectance/r60m:b02+/measurements/reflectance/r60m:b03",
            )
            assert img.band_names == [
                "/measurements/reflectance/r60m:b02+/measurements/reflectance/r60m:b03"
            ]
            assert img.data.shape == (1, 256, 256)

        with pytest.raises(MissingVariables):
            src.tile(*tile)


def test_point():
    """test point method."""
    with GeoZarrReader(SENTINEL_2) as src:
        bounds = src.bounds
        lon, lat = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
        pt = src.point(lon, lat, variables=["/measurements/reflectance/r60m:b02"])
        assert pt.band_names == ["b02"]
        assert pt.data.shape == (1,)

        pt = src.point(
            lon,
            lat,
            variables=[
                "/measurements/reflectance/r60m:b02",
                "/measurements/reflectance/r60m:b03",
            ],
        )
        assert pt.band_names == ["b02", "b03"]
        assert pt.data.shape == (2,)

        pt_expr = src.point(
            lon,
            lat,
            expression="/measurements/reflectance/r60m:b02+/measurements/reflectance/r60m:b03",
        )
        assert pt_expr.band_names == [
            "/measurements/reflectance/r60m:b02+/measurements/reflectance/r60m:b03"
        ]
        assert pt_expr.data.shape == (1,)
        assert pt_expr.data == pt.data[0] + pt.data[1]

        with pytest.warns(ExpressionMixingWarning):
            pt = src.point(
                lon,
                lat,
                variables=["/measurements/reflectance/r60m:b02"],
                expression="/measurements/reflectance/r60m:b02+/measurements/reflectance/r60m:b03",
            )
            assert pt.band_names == [
                "/measurements/reflectance/r60m:b02+/measurements/reflectance/r60m:b03"
            ]
            assert pt.data.shape == (1,)

        with pytest.raises(MissingVariables):
            src.point(lon, lat)


def test_statistics():
    """test statistics method."""
    with GeoZarrReader(SENTINEL_2) as src:
        with pytest.raises(NotImplementedError):
            src.statistics(variables=["/measurements/reflectance/r60m:b02"])


def test_preview():
    """test preview method."""
    with GeoZarrReader(SENTINEL_2) as src:
        img = src.preview(
            variables=["/measurements/reflectance/r60m:b02"], max_size=128
        )
        assert img.array.shape == (1, 128, 128)

        img = src.preview(
            variables=["/measurements/reflectance/r60m:b02"],
            max_size=128,
            dst_crs="epsg:4326",
        )
        assert img.array.shape == (1, 103, 128)


def test_part():
    """test part method."""
    # list(tms.bounds(2219, 1580, 12))
    bbox = [
        1673053.675105922,
        4569099.802774707,
        1682837.6147264242,
        4578883.742395209,
    ]
    with GeoZarrReader(SENTINEL_2) as src:
        _ = src.part(
            bbox,
            bounds_crs="epsg:3857",
            dst_crs="epsg:3857",
            variables=["/measurements/reflectance/r60m:b02"],
            width=256,
            height=256,
        )
        # Cannot compart Part/Tile at the moment
        #
        # img_tile = src.tile(
        #     2219,
        #     1580,
        #     12,
        #     variables=["/measurements/reflectance/r60m:b02"],
        # )
        # numpy.testing.assert_array_equal(img.array, img_tile.array)


# def test_feature():
#     """test feature method."""
#     with GeoZarrReader(SENTINEL_2) as src:
#         with pytest.raises(NotImplementedError):
#             src.feature(feat, variables=["/measurements/reflectance/r60m:b02"])
