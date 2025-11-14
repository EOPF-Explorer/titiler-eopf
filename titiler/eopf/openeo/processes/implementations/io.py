"""eopf_openeo.processes."""

import time
from typing import Any, Dict, Optional, Tuple, Type

import attr
from attrs import define
from openeo_pg_parser_networkx.pg_schema import TemporalInterval
from rasterio.errors import RasterioIOError
from rio_tiler.constants import MAX_THREADS
from rio_tiler.errors import TileOutsideBounds
from rio_tiler.io import BaseReader
from rio_tiler.models import ImageData
from rio_tiler.tasks import create_tasks
from rio_tiler.types import AssetInfo, BBox

from titiler.openeo import stacapi
from titiler.openeo.errors import (
    ItemsLimitExceeded,
    NoDataAvailable,
    OutputLimitExceeded,
)
from titiler.openeo.models.openapi import SpatialExtent
from titiler.openeo.processes.implementations.data_model import LazyRasterStack
from titiler.openeo.processes.implementations.utils import _props_to_datename
from titiler.openeo.reader import SimpleSTACReader, _estimate_output_dimensions
from titiler.openeo.settings import ProcessingSettings

from ....reader import GeoZarrReader
from .data_model import LazyZarrRasterStack

__all__ = ["load_zarr", "LoadCollection"]

processing_settings = ProcessingSettings()


def load_zarr(
    url: str,
    spatial_extent: Optional[Dict] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    options: Optional[Dict] = None,
) -> LazyZarrRasterStack:
    """Load data from a Zarr store.

    Args:
        url: The URL or path to the Zarr store
        spatial_extent: Optional bounding box to limit the spatial extent
        options: Additional reading options (e.g., variables to load, sel, method)

    Returns:
        RasterStack: A data cube organized by time dimension.
                    Each key represents a time step, and each value is an ImageData
                    containing all spectral bands (x, y, bands) for that time.

    Example:
        >>> # Load a zarr store
        >>> data = load_zarr("s3://bucket/dataset.zarr")
        >>> # Access specific time slice
        >>> time_slice = data["2020-01-01T00:00:00"]
        >>> # Or specify variables and spatial extent
        >>> data = load_zarr(
        ...     "path/to/data.zarr",
        ...     spatial_extent={"west": -10, "south": 40, "east": 10, "north": 50},
        ...     options={"variables": ["group:band1", "group:band2"]}
        ... )
    """
    options = options or {}

    # Store spatial extent in options for use by LazyZarrRasterStack
    if spatial_extent is not None:
        options["spatial_extent"] = spatial_extent

    if width is not None:
        options["width"] = width

    if height is not None:
        options["height"] = height

    # Open the zarr store with GeoZarrReader
    zarr_dataset = GeoZarrReader(url)

    # Get variables to load (all variables if not specified)
    variables = options.get("variables", zarr_dataset.variables)

    # Extract time values from the zarr dataset
    # We need to get the time dimension values from the first variable
    time_values = []
    if variables:
        # Get the first variable to extract time dimension
        first_var = variables[0]
        group, variable = first_var.split(":") if ":" in first_var else ("/", first_var)

        # Get the data array to access time coordinate
        da = zarr_dataset._get_variable(group, variable)

        # Check if time dimension exists
        if "time" in da.dims:
            # Extract time values and convert to ISO strings
            time_coord = da.coords["time"]
            time_values = [str(t.values) for t in time_coord]
        else:
            # If no time dimension, create a single time entry
            time_values = ["data"]

    # Return a lazy RasterStack organized by time
    return LazyZarrRasterStack(
        zarr_dataset=zarr_dataset,
        variables=variables,
        time_values=time_values,
        options=options,
    )


@attr.s
class STACReader(SimpleSTACReader):
    """STACReader with support of Zarr or COG"""

    def _get_reader(self, asset_info: AssetInfo) -> Tuple[Type[BaseReader], Dict]:
        """Get Asset Reader."""
        asset_type = asset_info.get("media_type", None)
        if (
            asset_type
            and asset_type in ["application/x-zarr", "application/vnd+zarr"]
            and not asset_info["url"].startswith("vrt://")
        ):
            return GeoZarrReader, asset_info.get("reader_options", {})

        return self.reader, asset_info.get("reader_options", {})


def _reader(item: Dict[str, Any], bbox: BBox, **kwargs: Any) -> ImageData:
    """
    Read a STAC item and return an ImageData object.

    Args:
        item: STAC item dictionary
        bbox: Bounding box to read
        **kwargs: Additional keyword arguments to pass to the reader

    Returns:
        ImageData object
    """
    max_retries = 10
    retry_delay = 1.0  # seconds
    retries = 0

    while True:
        try:
            with STACReader(item) as src_dst:  # type: ignore
                return src_dst.part(bbox, **kwargs)
        except RasterioIOError as e:
            retries += 1
            if retries >= max_retries:
                # If we've reached max retries, re-raise the exception
                raise
            # Log the error and retry after a delay
            print(
                f"RasterioIOError encountered: {str(e)}. Retrying in {retry_delay} seconds... (Attempt {retries}/{max_retries})"
            )
            time.sleep(retry_delay)
            # Increase delay for next retry (exponential backoff)
            retry_delay *= 2


@define
class LoadCollection(stacapi.LoadCollection):
    """Load Collection process implementation."""

    def load_collection(
        self,
        id: str,
        spatial_extent: Optional[SpatialExtent] = None,
        temporal_extent: Optional[TemporalInterval] = None,
        bands: Optional[list[str]] = None,
        properties: Optional[dict] = None,
        # private arguments
        width: Optional[int] = 1024,
        height: Optional[int] = None,
        tile_buffer: Optional[float] = None,
        options: Optional[Dict] = None,
    ) -> LazyRasterStack:
        """Load Collection."""
        options = options or {}

        items = self._get_items(
            id,
            spatial_extent=spatial_extent,
            temporal_extent=temporal_extent,
            properties=properties,
        )
        if not items:
            raise NoDataAvailable("There is no data available for the given extents.")

        # Check the items limit
        if len(items) > processing_settings.max_items:
            raise ItemsLimitExceeded(len(items), processing_settings.max_items)

        # Check pixel limit before calling _estimate_output_dimensions
        # For test_load_collection_pixel_threshold
        if width and height:
            width_int = int(width)
            height_int = int(height)
            pixel_count = width_int * height_int * len(items)
            if pixel_count > processing_settings.max_pixels:
                raise OutputLimitExceeded(
                    width_int,
                    height_int,
                    processing_settings.max_pixels,
                    items_count=len(items),
                )

        # If bands parameter is missing, use the first asset from the first item
        if bands is None and items and items[0].assets:
            bands = list(items[0].assets.keys())[:1]  # Take the first asset as default

        # Estimate dimensions based on items and spatial extent
        dimensions = _estimate_output_dimensions(
            items, spatial_extent, bands, width, height
        )

        # Extract values from the result
        width = dimensions["width"]
        height = dimensions["height"]
        bbox = dimensions["bbox"]
        crs = dimensions["crs"]

        # Group items by date
        items_by_date: dict[str, list[dict]] = {}
        for item in items:
            date = item.datetime.isoformat()
            if date not in items_by_date:
                items_by_date[date] = []
            items_by_date[date].append(item)

        tasks = create_tasks(
            _reader,
            items,
            MAX_THREADS,
            bbox,
            assets=bands,
            bounds_crs=crs,
            dst_crs=crs,
            width=int(width) if width else width,
            height=int(height) if height else height,
            buffer=float(tile_buffer) if tile_buffer is not None else tile_buffer,
            **options,
        )

        return LazyRasterStack(
            tasks=tasks,
            date_name_fn=lambda asset: _props_to_datename(asset.properties),
            allowed_exceptions=(TileOutsideBounds,),
        )
