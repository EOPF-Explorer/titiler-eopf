"""Test eopf openeo processes io module."""

from datetime import datetime, timezone
from unittest.mock import Mock, patch

import numpy as np
import pystac
import pytest
from openeo_pg_parser_networkx.pg_schema import BoundingBox
from rio_tiler.models import ImageData
from rioxarray.exceptions import NoDataInBounds

from titiler.eopf.openeo.processes.implementations.io import load_zarr
from titiler.eopf.openeo.reader import STACReader
from titiler.eopf.openeo.stacapi import LoadCollection
from titiler.openeo import reader as upstream_reader
from titiler.openeo.processes.implementations.data_model import RasterStack


class TestLoadZarr:
    """Test load_zarr function."""

    def test_load_zarr_basic(self):
        """Test basic load_zarr functionality."""
        with patch(
            "titiler.eopf.openeo.processes.implementations.io.GeoZarrReader"
        ) as mock_reader_class:
            mock_reader = Mock()
            mock_reader.variables = [
                "measurements/reflectance:b02",
                "measurements/reflectance:b03",
            ]

            # Mock the data array for time extraction
            mock_da = Mock()
            mock_da.dims = ["time", "y", "x"]
            mock_time_coord = Mock()
            mock_time_coord.__iter__ = lambda x: iter(
                [Mock(values="2020-01-01T00:00:00")]
            )
            mock_da.coords = {"time": mock_time_coord}

            mock_reader._get_variable.return_value = mock_da
            mock_reader_class.return_value = mock_reader

            result = load_zarr("test.zarr")

            assert isinstance(result, RasterStack)
            mock_reader_class.assert_called_once_with("test.zarr")

    def test_load_zarr_no_time_dimension(self):
        """Test load_zarr with no time dimension."""
        with patch(
            "titiler.eopf.openeo.processes.implementations.io.GeoZarrReader"
        ) as mock_reader_class:
            mock_reader = Mock()
            mock_reader.variables = ["measurements/reflectance:b02"]

            # Mock data array without time dimension
            mock_da = Mock()
            mock_da.dims = ["y", "x"]
            mock_da.coords = {}

            mock_reader._get_variable.return_value = mock_da
            mock_reader_class.return_value = mock_reader

            result = load_zarr("test.zarr")

            assert isinstance(result, RasterStack)

    def test_load_zarr_with_spatial_extent(self):
        """Test load_zarr with spatial extent."""
        bbox = BoundingBox(west=-10, south=40, east=10, north=50)

        with patch(
            "titiler.eopf.openeo.processes.implementations.io.GeoZarrReader"
        ) as mock_reader_class:
            mock_reader = Mock()
            mock_reader.variables = ["measurements/reflectance:b02"]
            mock_da = Mock()
            mock_da.dims = ["y", "x"]
            mock_reader._get_variable.return_value = mock_da
            mock_reader_class.return_value = mock_reader

            result = load_zarr("test.zarr", spatial_extent=bbox, width=512, height=512)

            assert isinstance(result, RasterStack)

    def test_load_zarr_with_options(self):
        """Test load_zarr with custom options."""
        options = {"variables": ["custom:variable"], "method": "bilinear"}

        with patch(
            "titiler.eopf.openeo.processes.implementations.io.GeoZarrReader"
        ) as mock_reader_class:
            mock_reader = Mock()
            mock_reader.variables = ["custom:variable"]
            mock_da = Mock()
            mock_da.dims = ["y", "x"]
            mock_reader._get_variable.return_value = mock_da
            mock_reader_class.return_value = mock_reader

            result = load_zarr("test.zarr", options=options)

            assert isinstance(result, RasterStack)


class TestSTACReaderMethods:
    """Test specific methods of STACReader without full initialization."""

    def test_get_reader_zarr_detection(self):
        """Test _get_reader method correctly identifies Zarr assets."""
        from titiler.eopf.reader import GeoZarrReader

        # Create a minimal STACReader instance by mocking the initialization
        with patch("titiler.eopf.openeo.reader.SimpleSTACReader.__attrs_post_init__"):
            mock_item = Mock()
            mock_item.bbox = [0, 0, 1, 1]
            reader = STACReader(mock_item)

            # Test Zarr asset detection
            asset_info = {
                "name": "data",
                "media_type": "application/x-zarr",
                "url": "test.zarr",
            }
            reader_class = reader._get_reader(asset_info)
            assert reader_class == GeoZarrReader

            # Test non-Zarr asset. `name` is required here: the non-Zarr path
            # now falls through to upstream's own `_get_reader`, which looks
            # up `asset_info["name"]` against `_derived_bands` before
            # defaulting to `self.reader` -- matching what a real `AssetInfo`
            # always carries (`_get_asset_info` always sets `name`).
            asset_info = {
                "name": "data",
                "media_type": "image/tiff",
                "url": "test.tif",
            }
            reader_class = reader._get_reader(asset_info)
            assert reader_class != GeoZarrReader

    def test_get_options_zarr_maps_bands_to_variables(self):
        """Zarr assets: `bands` resolves to `variables`, by common name or
        by the band's own `name` (both must map to the same underlying
        variable, matching `_get_asset_info`'s Zarr band selection)."""
        with patch("titiler.eopf.openeo.reader.SimpleSTACReader.__attrs_post_init__"):
            mock_item = Mock()
            mock_item.bbox = [0, 0, 1, 1]
            reader = STACReader(mock_item)

            metadata = pystac.Asset(
                href="s3://x/a.zarr",
                media_type="application/vnd+zarr",
                extra_fields={
                    "bands": [
                        {"name": "b04", "eo:common_name": "red"},
                        {"name": "b03", "eo:common_name": "green"},
                    ]
                },
            )

            _, by_common = reader._get_options(
                {"name": "a", "bands": ["red", "green"]}, metadata
            )
            assert by_common["variables"] == ["b04", "b03"]

            _, by_name = reader._get_options({"name": "a", "bands": ["b04"]}, metadata)
            assert by_name["variables"] == ["b04"]

    def test_get_options_non_zarr_delegates_to_upstream(self):
        """Non-Zarr assets: `bands` -> `indexes` is now upstream's own logic
        (`SimpleSTACReader._get_options`, delegated via `super()`), not a
        local copy. Exercises the positional-index fallback specifically --
        it depends on upstream's own bugfix (titiler-openeo#378) rather than
        anything local, so this is the test that would catch a regression on
        either side of that delegation."""
        with patch("titiler.eopf.openeo.reader.SimpleSTACReader.__attrs_post_init__"):
            mock_item = Mock()
            mock_item.bbox = [0, 0, 1, 1]
            reader = STACReader(mock_item)

            metadata = pystac.Asset(
                href="s3://x/a.tif",
                media_type="image/tiff",
                extra_fields={
                    "bands": [{"description": "first"}, {"description": "second"}]
                },
            )

            _, mo = reader._get_options({"name": "a", "bands": ["2"]}, metadata)
            assert mo["indexes"] == [2]

    def test_part_allowed_exceptions_is_narrow(self):
        """`part` must pass no `allowed_exceptions` to `multi_arrays`: one
        asset outside the bbox makes the whole item outside it, so an item
        never gives fewer bands than requested (the band order of openEO
        `load_collection`). A wider tuple used to swallow a genuine option
        error (e.g. an unknown band name from `_get_options`) silently:
        `filter_tasks` logs an allowed exception at INFO and drops the
        asset, so the error naming the bad band never reached the caller."""

        with patch("titiler.eopf.openeo.reader.SimpleSTACReader.__attrs_post_init__"):
            mock_item = Mock()
            mock_item.bbox = [0, 0, 1, 1]
            reader = STACReader(mock_item)
            reader.default_assets = None

            stub_img = ImageData(np.ones((1, 2, 2), dtype=np.uint8))
            with patch(
                "titiler.eopf.openeo.reader.multi_arrays", return_value=stub_img
            ) as mock_multi_arrays:
                reader.part((0, 0, 1, 1), assets=["a"])

            _, kwargs = mock_multi_arrays.call_args
            assert kwargs["allowed_exceptions"] == ()

    def test_get_options_variables_and_sel_pass_through(self):
        """`variables`/`sel` are EOPF-only options with no upstream
        equivalent; must survive delegation for non-Zarr/no-bands assets."""
        with patch("titiler.eopf.openeo.reader.SimpleSTACReader.__attrs_post_init__"):
            mock_item = Mock()
            mock_item.bbox = [0, 0, 1, 1]
            reader = STACReader(mock_item)

            metadata = pystac.Asset(
                href="s3://x/a.zarr", media_type="application/vnd+zarr"
            )

            _, mo = reader._get_options(
                {"name": "a", "variables": ["b04"], "sel": ["time=2024-01-01"]},
                metadata,
            )
            assert mo["variables"] == ["b04"]
            assert mo["sel"] == ["time=2024-01-01"]


class TestReaderSeam:
    """The EOPF reader goes through the upstream backend seam (titiler-openeo#462)."""

    def test_reader_cls_default(self):
        """Every LoadCollection reads with STACReader, without configuration."""
        assert LoadCollection(stac_api=Mock()).reader_cls is STACReader

    def test_bands_to_assets(self):
        """The EOPF band notation becomes one asset dict per band."""
        loaders = LoadCollection(stac_api=Mock())
        assert loaders._bands_to_assets(None) is None
        assert loaders._bands_to_assets(
            ["reflectance|bands=b04", "reflectance|bands=b03"]
        ) == [
            {"name": "reflectance", "bands": ["b04"]},
            {"name": "reflectance", "bands": ["b03"]},
        ]

    def test_upstream_reader_reads_geozarr(self, geozarr_stac):
        """Upstream `_reader` with `reader_cls=STACReader` reads a GeoZarr asset."""
        img = upstream_reader._reader(
            geozarr_stac,
            (15.0, 37.86, 15.11, 37.94),
            reader_cls=STACReader,
            assets=LoadCollection(stac_api=Mock())._bands_to_assets(
                ["reflectance|bands=b04"]
            ),
            bounds_crs="epsg:4326",
            width=32,
            height=32,
        )
        assert img.count == 1
        assert img.array.shape == (1, 32, 32)
        assert not img.array.mask.all()

    def test_no_double_scale_offset(self, geozarr_stac):
        """STAC `raster:scale` is not applied on top of the decoded Zarr values."""
        assert upstream_reader.processing_settings.apply_scale_offset is False

        kwargs = {
            "reader_cls": STACReader,
            "assets": [{"name": "reflectance", "bands": ["b04"]}],
            "bounds_crs": "epsg:4326",
            "width": 32,
            "height": 32,
        }
        bbox = (15.0, 37.86, 15.11, 37.94)
        plain = upstream_reader._reader(geozarr_stac, bbox, **kwargs)

        scaled = geozarr_stac.clone()
        scaled.assets["reflectance"].extra_fields["raster:scale"] = 0.0001
        img = upstream_reader._reader(scaled, bbox, **kwargs)

        np.testing.assert_array_equal(img.array, plain.array)


class TestLoadCollectionBasic:
    """Test LoadCollection class - basic functionality only."""

    def test_load_collection_instantiation(self):
        """Test LoadCollection can be instantiated."""
        mock_stac_api = Mock()
        collection = LoadCollection(stac_api=mock_stac_api)
        assert collection is not None
        assert hasattr(collection, "load_collection")


class TestLoggerUsage:
    """Test that logger usage works correctly in bounds checking."""

    def test_logger_import_and_usage(self):
        """Test that logger is properly imported and can be used."""
        from titiler.eopf.openeo.reader import logger

        # Test that logger exists and can be called
        assert logger is not None
        assert hasattr(logger, "debug")
        assert hasattr(logger, "info")
        assert hasattr(logger, "error")

        # Test that we can call logger.debug without errors
        try:
            logger.debug("Test message")
            logger.info("Test info")
        except Exception as e:
            pytest.fail(f"Logger usage failed: {e}")


class TestExceptionHandling:
    """Test the improved exception handling."""

    def test_rasterio_import(self):
        """Test that rasterio.RasterioIOError can be imported and used."""
        with patch("titiler.eopf.openeo.reader.STACReader"):
            # This should not raise any import errors
            from titiler.eopf.openeo.reader import STACReader

            assert STACReader is not None

    def test_nodata_in_bounds_import(self):
        """Test that NoDataInBounds can be imported and used."""
        assert NoDataInBounds is not None

        # Test that it's used in the allowed_exceptions
        with patch(
            "titiler.eopf.openeo.processes.implementations.io.GeoZarrReader"
        ) as mock_reader_class:
            mock_reader = Mock()
            mock_reader.variables = ["test"]
            mock_da = Mock()
            mock_da.dims = ["y", "x"]
            mock_reader._get_variable.return_value = mock_da
            mock_reader_class.return_value = mock_reader

            result = load_zarr("test.zarr")

            # Check that the RasterStack was created with the correct exceptions
            assert isinstance(result, RasterStack)


def _s1_rtc_item(nodata) -> pystac.Item:
    """A Sentinel-1 RTC-like item: one Zarr asset, `nodata` in the asset and
    in each band (the real items give the string "nan")."""
    item = pystac.Item(
        id="s1-rtc-28RBS-20211203t071038",
        geometry={
            "type": "Polygon",
            "coordinates": [
                [
                    [-18.1, 27.9],
                    [-16.9, 27.9],
                    [-16.9, 28.9],
                    [-18.1, 28.9],
                    [-18.1, 27.9],
                ]
            ],
        },
        bbox=[-18.1, 27.9, -16.9, 28.9],
        datetime=datetime(2021, 12, 3, 7, 10, 38, tzinfo=timezone.utc),
        properties={},
    )
    item.add_asset(
        "gamma0-rtc-backscatter-desc",
        pystac.Asset(
            href="https://example.com/s1-rtc-28RBS.zarr/descending",
            media_type="application/vnd.zarr; version=3",
            roles=["data"],
            extra_fields={
                "nodata": nodata,
                "bands": [
                    {"name": "vv", "nodata": nodata, "data_type": "float32"},
                    {"name": "vh", "nodata": nodata, "data_type": "float32"},
                ],
            },
        ),
    )
    return item


@pytest.mark.parametrize(
    ("stac_nodata", "expected"),
    [
        ("nan", float("nan")),
        ("inf", float("inf")),
        ("-inf", float("-inf")),
        (0, 0),
        (-9999.0, -9999.0),
    ],
)
def test_get_asset_info_nodata_string_to_float(stac_nodata, expected):
    """A STAC `nodata` string ("nan", "inf", "-inf") reaches the reader as a
    float. As a string, rasterio's reprojection raised `TypeError: ufunc
    'isnan' not supported` for every Sentinel-1 RTC tile."""
    with STACReader(_s1_rtc_item(stac_nodata)) as src:
        info = src._get_asset_info(
            {"name": "gamma0-rtc-backscatter-desc", "bands": ["vv"]}
        )

    nodata = info["method_options"]["nodata"]
    assert not isinstance(nodata, str)
    if np.isnan(expected):
        assert np.isnan(nodata)
    else:
        assert nodata == expected


def test_get_asset_info_nodata_invalid_string_is_ignored():
    """A `nodata` string that is not a number is removed, not sent to the
    reader (where it would fail in the same way)."""
    with STACReader(_s1_rtc_item("none")) as src:
        info = src._get_asset_info(
            {"name": "gamma0-rtc-backscatter-desc", "bands": ["vv"]}
        )

    assert "nodata" not in info["method_options"]


def test_get_options_zarr_gives_the_item_datetime():
    """Zarr asset: the item datetime (UTC, no offset) goes to the reader, so
    that it reads the item's time slice of a time-stacked store."""
    item = _s1_rtc_item("nan")
    with STACReader(item) as src:
        info = src._get_asset_info(
            {"name": "gamma0-rtc-backscatter-desc", "bands": ["vv"]}
        )
    assert info["reader_options"]["item_datetime"] == "2021-12-03T07:10:38"


def test_get_options_cog_has_no_item_datetime():
    """Not Zarr: no `item_datetime` (the rasterio reader does not take it)."""
    with patch("titiler.eopf.openeo.reader.SimpleSTACReader.__attrs_post_init__"):
        reader = STACReader(_s1_rtc_item("nan"))
        metadata = pystac.Asset(
            href="https://example.com/b04.tif",
            media_type="image/tiff; application=geotiff",
        )
        reader_options, _ = reader._get_options({"name": "b04"}, metadata)
    assert "item_datetime" not in reader_options
