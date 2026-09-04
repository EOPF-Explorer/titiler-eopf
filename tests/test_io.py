"""Test eopf openeo processes io module."""

from unittest.mock import Mock, patch

import numpy as np
import pystac
import pytest
from openeo_pg_parser_networkx.pg_schema import BoundingBox
from rasterio.errors import RasterioIOError
from rio_tiler.models import ImageData
from rioxarray.exceptions import NoDataInBounds

from titiler.eopf.openeo.processes.implementations.io import load_zarr
from titiler.eopf.openeo.reader import STACReader, _reader
from titiler.eopf.openeo.stacapi import LoadCollection
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
        """`part` must pass only `TileOutsideBounds` as `allowed_exceptions`
        to `multi_arrays` -- matching `mosaic_reader`'s own default one level
        up. A wider tuple used to swallow a genuine option error (e.g. an
        unknown band name from `_get_options`) silently: `filter_tasks` logs
        an allowed exception at INFO and drops the asset, so the error
        naming the bad band never reached the caller."""
        from rio_tiler.errors import TileOutsideBounds
        from rio_tiler.models import ImageData

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
            assert kwargs["allowed_exceptions"] == (TileOutsideBounds,)

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


class TestReader:
    """Test _reader function."""

    def test_reader_success(self):
        """Test _reader function successful execution."""
        mock_item = {"id": "test_item"}
        bbox = [0, 0, 1, 1]

        mock_img = ImageData(
            array=np.ones((3, 256, 256), dtype=np.uint8), crs="EPSG:4326", bounds=bbox
        )

        with patch("titiler.eopf.openeo.reader.STACReader") as mock_stac_reader:
            mock_reader_instance = Mock()
            mock_reader_instance.part.return_value = mock_img
            mock_stac_reader.return_value.__enter__ = Mock(
                return_value=mock_reader_instance
            )
            mock_stac_reader.return_value.__exit__ = Mock(return_value=None)

            result = _reader(mock_item, bbox)

            assert isinstance(result, ImageData)
            mock_reader_instance.part.assert_called_once_with(bbox)

    def test_reader_retry_logic(self):
        """Test _reader function retry logic."""
        mock_item = {"id": "test_item"}
        bbox = [0, 0, 1, 1]

        with (
            patch("titiler.eopf.openeo.reader.STACReader") as mock_stac_reader,
            patch("time.sleep"),
            patch("builtins.print"),
        ):  # Suppress print statements
            mock_reader_instance = Mock()
            # First two calls fail, third succeeds
            mock_reader_instance.part.side_effect = [
                RasterioIOError("Network error"),
                RasterioIOError("Network error"),
                ImageData(array=np.ones((3, 256, 256)), crs="EPSG:4326", bounds=bbox),
            ]

            mock_stac_reader.return_value.__enter__ = Mock(
                return_value=mock_reader_instance
            )
            mock_stac_reader.return_value.__exit__ = Mock(return_value=None)

            result = _reader(mock_item, bbox)

            assert isinstance(result, ImageData)
            assert mock_reader_instance.part.call_count == 3

    def test_reader_calls_inherit_derived_band_masks_when_assets_requested(self):
        """`_reader` must call `_inherit_derived_band_masks` when `assets` is
        passed -- restored from upstream, previously missing from this
        repo's copy (band-source-derived bands, e.g. SAR noise/calibration
        LUTs, would otherwise keep an honestly-unmasked mask and make a
        slice's nodata region read as valid). Not called at all when no
        `assets` is requested -- matches upstream, and is what every other
        test in this class already exercises without hitting this path."""
        mock_item = {"id": "test_item"}
        bbox = [0, 0, 1, 1]
        mock_img = ImageData(
            array=np.ones((3, 256, 256), dtype=np.uint8), crs="EPSG:4326", bounds=bbox
        )

        with (
            patch("titiler.eopf.openeo.reader.STACReader") as mock_stac_reader,
            patch(
                "titiler.eopf.openeo.reader._inherit_derived_band_masks",
                return_value=mock_img,
            ) as mock_inherit,
        ):
            mock_reader_instance = Mock()
            mock_reader_instance.part.return_value = mock_img
            mock_reader_instance._derived_bands = {}
            mock_stac_reader.return_value.__enter__ = Mock(
                return_value=mock_reader_instance
            )
            mock_stac_reader.return_value.__exit__ = Mock(return_value=None)

            result = _reader(mock_item, bbox, assets=["b04", "b03"])

            assert isinstance(result, ImageData)
            mock_inherit.assert_called_once_with(mock_img, {}, ["b04", "b03"])

    def test_reader_skips_inherit_derived_band_masks_without_assets(self):
        """No `assets` kwarg -- `_inherit_derived_band_masks` is never called."""
        mock_item = {"id": "test_item"}
        bbox = [0, 0, 1, 1]
        mock_img = ImageData(
            array=np.ones((3, 256, 256), dtype=np.uint8), crs="EPSG:4326", bounds=bbox
        )

        with (
            patch("titiler.eopf.openeo.reader.STACReader") as mock_stac_reader,
            patch(
                "titiler.eopf.openeo.reader._inherit_derived_band_masks"
            ) as mock_inherit,
        ):
            mock_reader_instance = Mock()
            mock_reader_instance.part.return_value = mock_img
            mock_stac_reader.return_value.__enter__ = Mock(
                return_value=mock_reader_instance
            )
            mock_stac_reader.return_value.__exit__ = Mock(return_value=None)

            _reader(mock_item, bbox)

            mock_inherit.assert_not_called()

    def test_reader_max_retries_exceeded(self):
        """Test _reader function when max retries are exceeded."""
        mock_item = {"id": "test_item"}
        bbox = [0, 0, 1, 1]

        with (
            patch("titiler.eopf.openeo.reader.STACReader") as mock_stac_reader,
            patch("time.sleep"),
            patch("builtins.print"),
        ):  # Suppress print statements
            mock_reader_instance = Mock()
            # Always fail
            mock_reader_instance.part.side_effect = RasterioIOError(
                "Persistent network error"
            )

            mock_stac_reader.return_value.__enter__ = Mock(
                return_value=mock_reader_instance
            )
            mock_stac_reader.return_value.__exit__ = Mock(return_value=None)

            with pytest.raises(RasterioIOError):
                _reader(mock_item, bbox)


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
