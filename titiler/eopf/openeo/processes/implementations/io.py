"""eopf_openeo.processes - load_zarr implementation."""

import logging
from datetime import datetime
from typing import Dict, Optional

from openeo_pg_parser_networkx.pg_schema import BoundingBox
from rio_tiler.constants import MAX_THREADS
from rio_tiler.errors import TileOutsideBounds

from titiler.openeo.processes.implementations.data_model import RasterStack

from ....reader import GeoZarrReader

__all__ = ["load_zarr"]

logger = logging.getLogger(__name__)


def _create_zarr_time_task(
    time_key: str, zarr_dataset: GeoZarrReader, variables: list[str], options: dict
):
    """Create a task function for loading a specific time slice from GeoZarr.

    Args:
        time_key: Time value (ISO string) to load
        zarr_dataset: The GeoZarrReader instance
        variables: List of variables to load
        options: Reading options including spatial_extent, width, height, etc.

    Returns:
        Callable that returns ImageData for this time slice
    """

    def load_time_slice():
        # Get spatial extent from options or use reader's full bounds
        spatial_extent = options.get("spatial_extent")
        crs = "epsg:4326"
        if spatial_extent:
            # Handle BoundingBox object
            bbox = [
                spatial_extent.west,
                spatial_extent.south,
                spatial_extent.east,
                spatial_extent.north,
            ]
            if hasattr(spatial_extent, "crs"):
                crs = spatial_extent.crs
        else:
            bbox = zarr_dataset.bounds

        # Use the reader's part() method to load data for all variables at this time
        width = options.get("width")
        height = options.get("height")

        # For single time datasets, don't use time selection
        sel = None
        if len(options.get("time_values", [])) > 1:
            sel = [f"time={time_key}"]

        return zarr_dataset.part(
            bbox=bbox,
            bounds_crs=crs,
            dst_crs=crs,
            variables=variables,
            sel=sel,
            method=options.get("method", "nearest"),
            width=int(width) if width else None,
            height=int(height) if height else None,
        )

    return load_time_slice


def load_zarr(
    url: str,
    spatial_extent: Optional[BoundingBox] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    options: Optional[Dict] = None,
) -> RasterStack:
    """Load data from a Zarr store.

    Args:
        url: The URL or path to the Zarr store
        spatial_extent: Optional bounding box to limit the spatial extent
        width: Optional output width in pixels
        height: Optional output height in pixels
        options: Additional reading options (e.g., variables to load, sel, method)

    Returns:
        RasterStack: A data cube organized by time dimension.
                    Each key represents a time step (datetime), and each value is an ImageData
                    containing all spectral bands (x, y, bands) for that time.

    Example:
        >>> # Load a zarr store
        >>> data = load_zarr("s3://bucket/dataset.zarr")
        >>> # Access specific time slice
        >>> time_slice = data[some_datetime]
        >>> # Or specify variables and spatial extent
        >>> from openeo_pg_parser_networkx.pg_schema import BoundingBox
        >>> bbox = BoundingBox(west=-10, south=40, east=10, north=50)
        >>> data = load_zarr(
        ...     "path/to/data.zarr",
        ...     spatial_extent=bbox,
        ...     options={"variables": ["group:band1", "group:band2"]}
        ... )
    """
    options = options or {}

    # Store spatial extent in options for use by task creation
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

    # Store time_values in options for task creation
    options["time_values"] = time_values

    # Create tasks for each time slice
    tasks = []
    for time_key in time_values:
        # Create task function for this time slice (lazy - not executed yet)
        task_fn = _create_zarr_time_task(time_key, zarr_dataset, variables, options)

        # Parse datetime for the asset info
        try:
            dt = datetime.fromisoformat(time_key.replace("Z", "+00:00"))
        except ValueError:
            # Fallback for non-datetime keys like "data"
            dt = datetime.now()

        # Create asset info with datetime as the key identifier
        asset_info = {
            "datetime": dt,
            "time_key": time_key,
            "url": url,
            "variables": variables,
        }

        tasks.append((task_fn, asset_info))

    # Return a lazy RasterStack organized by time
    # In v0.12.0, datetime IS the key (no separate key_fn)
    return RasterStack(
        tasks=tasks,
        timestamp_fn=lambda asset: asset["datetime"],
        allowed_exceptions=(TileOutsideBounds,),
        max_workers=MAX_THREADS,
    )
