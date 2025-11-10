"""eopf_openeo.processes."""

from typing import Dict, Optional

from ....reader import GeoZarrReader
from .data_model import LazyZarrRasterStack

__all__ = ["load_zarr"]


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
