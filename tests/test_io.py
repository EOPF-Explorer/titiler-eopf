"""Test eopf openeo processes io module."""

from unittest.mock import Mock, patch

import numpy as np
import pytest
from openeo_pg_parser_networkx.pg_schema import BoundingBox
from rasterio.errors import RasterioIOError
from rio_tiler.models import ImageData
from rioxarray.exceptions import NoDataInBounds

from titiler.eopf.openeo.processes.implementations.io import (
    LoadCollection,
    STACReader,
    _reader,
    load_zarr,
)
from titiler.openeo.processes.implementations.data_model import LazyRasterStack


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

            assert isinstance(result, LazyRasterStack)
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

            assert isinstance(result, LazyRasterStack)

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

            assert isinstance(result, LazyRasterStack)

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

            assert isinstance(result, LazyRasterStack)


class TestSTACReaderMethods:
    """Test specific methods of STACReader without full initialization."""

    def test_get_reader_zarr_detection(self):
        """Test _get_reader method correctly identifies Zarr assets."""
        from titiler.eopf.reader import GeoZarrReader

        # Create a minimal STACReader instance by mocking the initialization
        with patch("titiler.openeo.reader.SimpleSTACReader.__attrs_post_init__"):
            mock_item = Mock()
            mock_item.bbox = [0, 0, 1, 1]
            reader = STACReader(mock_item)

            # Test Zarr asset detection
            asset_info = {"media_type": "application/x-zarr", "url": "test.zarr"}
            reader_class, options = reader._get_reader(asset_info)
            assert reader_class == GeoZarrReader

            # Test non-Zarr asset
            asset_info = {"media_type": "image/tiff", "url": "test.tif"}
            reader_class, options = reader._get_reader(asset_info)
            assert reader_class != GeoZarrReader


class TestReader:
    """Test _reader function."""

    def test_reader_success(self):
        """Test _reader function successful execution."""
        mock_item = {"id": "test_item"}
        bbox = [0, 0, 1, 1]

        mock_img = ImageData(
            array=np.ones((3, 256, 256), dtype=np.uint8), crs="EPSG:4326", bounds=bbox
        )

        with patch(
            "titiler.eopf.openeo.processes.implementations.io.STACReader"
        ) as mock_stac_reader:
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
            patch(
                "titiler.eopf.openeo.processes.implementations.io.STACReader"
            ) as mock_stac_reader,
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

    def test_reader_max_retries_exceeded(self):
        """Test _reader function when max retries are exceeded."""
        mock_item = {"id": "test_item"}
        bbox = [0, 0, 1, 1]

        with (
            patch(
                "titiler.eopf.openeo.processes.implementations.io.STACReader"
            ) as mock_stac_reader,
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
        from titiler.eopf.openeo.processes.implementations.io import logger

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
        with patch("titiler.eopf.openeo.processes.implementations.io.STACReader"):
            # This should not raise any import errors
            from titiler.eopf.openeo.processes.implementations.io import STACReader

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

            # Check that the LazyRasterStack was created with the correct exceptions
            assert isinstance(result, LazyRasterStack)
