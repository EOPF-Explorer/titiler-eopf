"""titiler.eopf.openeo data models."""

import logging
import numpy as np
from rio_tiler.models import ImageData
from rioxarray.exceptions import NoDataInBounds

from titiler.eopf.reader import GeoZarrReader

logger = logging.getLogger(__name__)


class LazyZarrRasterStack(dict[str, ImageData]):
    """A RasterStack that lazily loads zarr time slices when accessed.

    This class wraps a GeoZarrReader and organizes data by the TIME dimension.
    Each key in the RasterStack represents a time step, and each value is an
    ImageData containing all spectral bands (x, y, bands) for that time.
    """

    def __init__(
        self,
        zarr_dataset: GeoZarrReader,
        variables: list[str],
        time_values: list[str],
        options: dict | None = None,
    ):
        """Initialize a LazyZarrRasterStack.

        Args:
            reader: The GeoZarrReader instance
            variables: List of variables to load (spectral bands)
            time_values: List of time values (ISO strings)
            options: Additional reading options
        """
        super().__init__()
        self._dataset = zarr_dataset
        self._variables = variables
        self._time_values = time_values
        self._options = options or {}
        self._loaded_times = set[str]()

    def _load_time_slice(self, time_key: str) -> ImageData:
        """Load all spectral bands for a specific time slice.

        Args:
            time_key: Time value (ISO string) to load

        Returns:
            ImageData: Multi-band image with all spectral bands for this time

        """
        # Get spatial extent from options or use reader's full bounds
        spatial_extent = self._options.get("spatial_extent")
        crs = 4326
        if spatial_extent:
            # Handle both BoundingBox object and dictionary formats
            if hasattr(spatial_extent, "west"):
                # BoundingBox object
                bbox = [
                    spatial_extent.west,
                    spatial_extent.south,
                    spatial_extent.east,
                    spatial_extent.north,
                ]
            else:
                # Dictionary format
                bbox = [
                    spatial_extent["west"],
                    spatial_extent["south"],
                    spatial_extent["east"],
                    spatial_extent["north"],
                ]
            if hasattr(spatial_extent, "crs"):
                crs = spatial_extent.crs
        else:
            bbox = self._dataset.bounds

        # Use the reader's part() method to load data for all variables at this time
        # by selecting the time dimension
        width: int | None = None
        if w := self._options.get("width"):
            width = int(w)

        height: int | None = None
        if h := self._options.get("height"):
            height = int(h)

        return self._dataset.part(
            bbox=bbox,
            bounds_crs=crs,
            dst_crs=crs,
            variables=self._variables,
            sel=[f"time={time_key}"] if self.__len__() > 1 else None,
            method=self._options.get("method", "nearest"),
            width=width,
            height=height,
        )

    def __getitem__(self, key: str) -> ImageData:
        """Get ImageData for a time slice, loading it if necessary."""
        if key not in self._loaded_times:
            try:
                # Load the time slice and cache it
                super().__setitem__(key, self._load_time_slice(key))
                self._loaded_times.add(key)
            except NoDataInBounds as e:
                logger.warning(f"No data found for time slice '{key}': {str(e)}. Creating empty placeholder.")
                # Create a placeholder ImageData with NaN values to maintain consistency
                # This allows processing to continue with other valid time slices
                empty_data = np.full((1, 256, 256), np.nan, dtype=np.float32)
                placeholder_img = ImageData(
                    array=empty_data,
                    crs=None,
                    bounds=(0.0, 0.0, 1.0, 1.0),  # Placeholder bounds
                    band_names=[f"empty_{key}"],
                )
                super().__setitem__(key, placeholder_img)
                self._loaded_times.add(key)
        return super().__getitem__(key)

    def __iter__(self):
        """Iterate over time values."""
        return iter(self._time_values)

    def __len__(self) -> int:
        """Return the number of time steps."""
        return len(self._time_values)

    def __contains__(self, key: object) -> bool:
        """Check if a time value is available."""
        return key in self._time_values

    def keys(self):
        """Return the time values."""
        return self._time_values

    def values(self):
        """Return the values, loading all time slices if necessary."""
        for time_key in self._time_values:
            if time_key not in self._loaded_times:
                self[time_key]  # Trigger loading
        return super().values()

    def items(self):
        """Return the items, loading all time slices if necessary."""
        for time_key in self._time_values:
            if time_key not in self._loaded_times:
                self[time_key]  # Trigger loading
        return super().items()
