"""test titiler-eopf reader"""

import numpy
import pytest
import xarray
from rio_tiler.errors import ExpressionMixingWarning

from titiler.eopf.reader import (
    GeoZarrReader,
    MissingVariables,
    _node_has_variable,
    _select_variable_from_node,
    get_multiscale_level,
)


def test_open(geozarr_dataset):
    """test GeoZarrReader open."""
    with GeoZarrReader(geozarr_dataset) as src:
        assert src.input == geozarr_dataset
        assert isinstance(src.datatree, xarray.DataTree)

        assert src.groups == ["/measurements/reflectance"]
        assert src.variables == [
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


def test_zooms_for_group(geozarr_dataset):
    """test GeoZarrReader min/max zoom."""
    with GeoZarrReader(geozarr_dataset) as src:
        # Default zooms to TMS zooms
        assert src.minzoom == 0
        assert src.maxzoom == 24

        assert src.get_minzoom("/measurements/reflectance") == 10
        assert src.get_maxzoom("/measurements/reflectance") == 14


def test_info(geozarr_dataset):
    """test info method."""
    with GeoZarrReader(geozarr_dataset) as src:
        # Default to all variables
        info = src.info()
        assert src.variables == list(info)
        info = src.info(variables=["/measurements/reflectance:b02"])
        info_b02 = info["/measurements/reflectance:b02"]
        assert info_b02.crs == "http://www.opengis.net/def/crs/EPSG/0/32633"
        assert info_b02.band_descriptions == [("b1", "b02")]
        assert info_b02.width == 1000
        assert info_b02.height == 1000


def test_tile(geozarr_dataset):
    """test tile method."""
    with GeoZarrReader(geozarr_dataset) as src:
        bounds = src.bounds
        lon, lat = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2

        tile = src.tms.tile(lon, lat, 10)

        img = src.tile(*tile, variables=["/measurements/reflectance:b02"])
        assert img.band_names == ["b1"]
        assert img.band_descriptions == ["/measurements/reflectance:b02"]
        assert img.data.shape == (1, 256, 256)

        img = src.tile(
            *tile,
            variables=[
                "/measurements/reflectance:b02",
                "/measurements/reflectance:b03",
            ],
        )
        assert img.band_names == ["b1", "b2"]
        assert img.band_descriptions == [
            "/measurements/reflectance:b02",
            "/measurements/reflectance:b03",
        ]
        assert img.data.shape == (2, 256, 256)

        img_expr = src.tile(
            *tile,
            expression="/measurements/reflectance:b02+/measurements/reflectance:b03",
        )
        assert img_expr.band_names == ["b1"]
        assert img_expr.band_descriptions == [
            "/measurements/reflectance:b02+/measurements/reflectance:b03"
        ]
        assert img_expr.data.shape == (1, 256, 256)
        numpy.testing.assert_equal(
            img_expr.data, numpy.ma.sum(img.data, axis=0, keepdims=True)
        )

        img_expr = src.tile(
            *tile,
            expression="/measurements/reflectance:b02+/measurements/reflectance:b03;/measurements/reflectance:b03",
        )
        assert img_expr.band_names == ["b1", "b2"]
        assert img_expr.band_descriptions == [
            "/measurements/reflectance:b02+/measurements/reflectance:b03",
            "/measurements/reflectance:b03",
        ]
        assert img_expr.data.shape == (2, 256, 256)
        numpy.testing.assert_equal(
            img_expr.data[0], numpy.ma.sum(img.data, axis=0, keepdims=True)[0]
        )

        with pytest.warns(ExpressionMixingWarning):
            img = src.tile(
                *tile,
                variables=["/measurements/reflectance:b02"],
                expression="/measurements/reflectance:b02+/measurements/reflectance:b03",
            )
            assert img.band_descriptions == [
                "/measurements/reflectance:b02+/measurements/reflectance:b03"
            ]
            assert img.data.shape == (1, 256, 256)

        with pytest.raises(MissingVariables):
            src.tile(*tile)


def test_point(geozarr_dataset):
    """test point method."""
    with GeoZarrReader(geozarr_dataset) as src:
        bounds = src.bounds
        lon, lat = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
        pt = src.point(lon, lat, variables=["/measurements/reflectance:b02"])
        assert pt.band_names == ["b1"]
        assert pt.band_descriptions == ["/measurements/reflectance:b02"]
        assert pt.data.shape == (1,)

        pt = src.point(
            lon,
            lat,
            variables=[
                "/measurements/reflectance:b02",
                "/measurements/reflectance:b03",
            ],
        )
        assert pt.band_names == ["b1", "b2"]
        assert pt.band_descriptions == [
            "/measurements/reflectance:b02",
            "/measurements/reflectance:b03",
        ]
        assert pt.data.shape == (2,)

        pt_expr = src.point(
            lon,
            lat,
            expression="/measurements/reflectance:b02+/measurements/reflectance:b03",
        )
        assert pt_expr.band_names == ["b1"]
        assert pt_expr.band_descriptions == [
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
            assert pt.band_descriptions == [
                "/measurements/reflectance:b02+/measurements/reflectance:b03"
            ]
            assert pt.data.shape == (1,)

        with pytest.raises(MissingVariables):
            src.point(lon, lat)


def test_statistics(geozarr_dataset):
    """test statistics method."""
    with GeoZarrReader(geozarr_dataset) as src:
        with pytest.raises(NotImplementedError):
            src.statistics(variables=["/measurements/reflectance:b02"])


def test_preview(geozarr_dataset):
    """test preview method."""
    with GeoZarrReader(geozarr_dataset) as src:
        img = src.preview(variables=["/measurements/reflectance:b02"], max_size=128)
        assert img.array.shape == (1, 128, 128)

        img = src.preview(
            variables=["/measurements/reflectance:b02"],
            max_size=128,
            dst_crs="epsg:4326",
        )
        assert img.array.shape == (1, 102, 128)


def test_part(geozarr_dataset):
    """test part method."""
    with GeoZarrReader(geozarr_dataset) as src:
        bounds = src.bounds
        lon, lat = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
        tile = src.tms.tile(lon, lat, 11)
        bbox = src.tms.xy_bounds(*tile)

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


def test_feature(geozarr_dataset):
    """test feature method."""
    with GeoZarrReader(geozarr_dataset) as src:
        bounds = src.bounds
        lon, lat = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
        xmin, ymin, xmax, ymax = src.tms.bounds(*src.tms.tile(lon, lat, 11))

        feat = {
            "type": "Polygon",
            "coordinates": [
                [(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax), (xmin, ymin)]
            ],
        }

        img = src.feature(feat, variables=["/measurements/reflectance:b02"])
        assert img.assets == [geozarr_dataset]


def test_node_has_variable_for_dataset_and_dataarray():
    """Variable lookup should support both dataset-like and DataArray-like nodes."""
    ds_node = xarray.Dataset({"b02": xarray.DataArray([1, 2], dims=["x"])})
    da_node = xarray.DataArray([1, 2], dims=["x"], name="b03")

    assert _node_has_variable(ds_node, "b02")
    assert _node_has_variable(da_node, "b03")
    assert not _node_has_variable(da_node, "b02")


def test_select_variable_from_node_supports_dataarray_and_errors():
    """Variable selection should return DataArray nodes directly when appropriate."""
    da_node = xarray.DataArray([1, 2], dims=["x"], name="b03")
    selected = _select_variable_from_node(da_node, "b03", asset="r20m")
    assert selected.name == "b03"

    with pytest.raises(MissingVariables):
        _select_variable_from_node(da_node, "b02", asset="r20m")


def test_get_multiscale_level_v1_filters_assets_without_variable():
    """V1 multiscale resolution selection should ignore assets missing the variable."""

    class MockTree:
        def __init__(self):
            self.attrs = {
                "multiscales": {
                    "layout": [
                        {
                            "asset": "r10m",
                            "spatial:transform": [10.0, 0.0, 0.0, 0.0, -10.0, 0.0],
                        },
                        {
                            "asset": "r20m",
                            "spatial:transform": [20.0, 0.0, 0.0, 0.0, -20.0, 0.0],
                        },
                    ]
                }
            }
            self._nodes = {
                "r10m": xarray.DataArray([1, 2], dims=["x"], name="other"),
                "r20m": xarray.DataArray([1, 2], dims=["x"], name="b02"),
            }

        def __getitem__(self, key):
            return self._nodes[key]

    level = get_multiscale_level(MockTree(), "b02", target_res=15.0)
    assert level == "r20m"
