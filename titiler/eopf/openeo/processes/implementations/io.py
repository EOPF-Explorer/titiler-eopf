"""eopf_openeo.processes."""

import time
import warnings
from datetime import datetime
from typing import Any, Dict, Optional, Sequence, Tuple, Type, Union

import attr
import numpy as np
from attrs import define
from openeo_pg_parser_networkx.pg_schema import BoundingBox, TemporalInterval
from rasterio.errors import RasterioIOError
from rio_tiler.constants import MAX_THREADS
from rio_tiler.errors import (
    AssetAsBandError,
    ExpressionMixingWarning,
    InvalidAssetName,
    MissingAssets,
    TileOutsideBounds,
)
from rio_tiler.io import BaseReader
from rio_tiler.io.stac import STAC_ALTERNATE_KEY
from rio_tiler.models import ImageData
from rio_tiler.tasks import create_tasks, multi_arrays
from rio_tiler.types import AssetInfo, BBox, Indexes
from rio_tiler.utils import cast_to_sequence
from rioxarray.exceptions import NoDataInBounds

from titiler.openeo import stacapi
from titiler.openeo.errors import (
    ItemsLimitExceeded,
    NoDataAvailable,
    OutputLimitExceeded,
)
from titiler.openeo.processes.implementations.data_model import LazyRasterStack
from titiler.openeo.processes.implementations.utils import _props_to_datetime
from titiler.openeo.reader import SimpleSTACReader, _estimate_output_dimensions
from titiler.openeo.settings import ProcessingSettings

from ....reader import GeoZarrReader

__all__ = ["load_zarr", "LoadCollection"]

processing_settings = ProcessingSettings()


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
    spatial_extent: Optional[Dict] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    options: Optional[Dict] = None,
) -> LazyRasterStack:
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

    # Store time_values in options for task creation
    options["time_values"] = time_values

    # Create tasks for each time slice
    tasks = []
    for time_key in time_values:
        # Create asset info for this time slice
        asset_info = {
            "time_key": time_key,
            "url": url,
            "variables": variables,
        }

        # Create task function for this time slice
        task_fn = _create_zarr_time_task(time_key, zarr_dataset, variables, options)

        tasks.append((task_fn, asset_info))

    # Create key and timestamp functions
    def key_fn(asset):
        return asset["time_key"]

    def timestamp_fn(asset):
        try:
            # Try to parse as ISO datetime
            return datetime.fromisoformat(asset["time_key"].replace("Z", "+00:00"))
        except ValueError:
            # Fallback for non-datetime keys like "data"
            return datetime.now()

    # Return a lazy RasterStack organized by time using tasks
    return LazyRasterStack(
        tasks=tasks,
        key_fn=key_fn,
        timestamp_fn=timestamp_fn,
        allowed_exceptions=(TileOutsideBounds, NoDataInBounds),
        max_workers=MAX_THREADS,
    )


@attr.s
class STACReader(SimpleSTACReader):
    """STACReader with support of Zarr or COG"""

    def _get_reader(self, asset_info: AssetInfo) -> Tuple[Type[BaseReader], Dict]:
        """Get Asset Reader."""
        if asset_type := asset_info.get("media_type", None):
            if asset_type.split(";")[0] in [
                "application/x-zarr",
                "application/vnd+zarr",
                "application/vnd.zarr",
            ] and not asset_info["url"].startswith("vrt://"):
                return GeoZarrReader, asset_info.get("reader_options", {})

        return self.reader, asset_info.get("reader_options", {})

    # Added in titiler-openeo https://github.com/sentinel-hub/titiler-openeo/pull/135
    def _get_asset_info(self, asset: str) -> AssetInfo:
        """Validate asset names and return asset's info.

        Args:
            asset (str): STAC asset name.

        Returns:
            AssetInfo: STAC asset info.

        """
        asset, vrt_options = self._parse_vrt_asset(asset)
        if asset not in self.assets:
            raise InvalidAssetName(
                f"'{asset}' is not valid, should be one of {self.assets}"
            )

        asset_info = self.item.assets[asset]
        extras = asset_info.extra_fields

        info = AssetInfo(
            url=asset_info.get_absolute_href() or asset_info.href,
            metadata=extras if not vrt_options else None,
        )

        if STAC_ALTERNATE_KEY and extras.get("alternate"):
            if alternate := extras["alternate"].get(STAC_ALTERNATE_KEY):
                info["url"] = alternate["href"]

        if asset_info.media_type:
            info["media_type"] = asset_info.media_type

        # https://github.com/stac-extensions/file
        if head := extras.get("file:header_size"):
            info["env"] = {"GDAL_INGESTED_BYTES_AT_OPEN": head}

        # https://github.com/stac-extensions/raster
        if extras.get("raster:bands") and not vrt_options:
            bands = extras.get("raster:bands")
            stats = [
                (b["statistics"]["minimum"], b["statistics"]["maximum"])
                for b in bands
                if {"minimum", "maximum"}.issubset(b.get("statistics", {}))
            ]
            # check that stats data are all double and make warning if not
            if (
                stats
                and all(isinstance(v, (int, float)) for stat in stats for v in stat)
                and len(stats) == len(bands)
            ):
                info["dataset_statistics"] = stats
            else:
                warnings.warn(
                    "Some statistics data in STAC are invalid, they will be ignored.",
                    UserWarning,
                    stacklevel=2,
                )

        if vrt_options:
            info["url"] = f"vrt://{info['url']}?{vrt_options}"

        return info

    # Custom PART method for multi-asset reading
    # We need to customize the `part()._reader` method to parse the asset (which can bel in form of `{asset}|{variable}` for Zarr)
    # then pass the variable to the `GeoZarrReader`
    def part(  # noqa: C901
        self,
        bbox: BBox,
        assets: Union[Sequence[str], str] | None = None,
        expression: str | None = None,
        asset_indexes: Dict[str, Indexes] | None = None,
        asset_as_band: bool = False,
        **kwargs: Any,
    ) -> ImageData:
        """Read and merge parts from multiple assets.

        Args:
            bbox (tuple): Output bounds (left, bottom, right, top) in target crs.
            assets (sequence of str or str, optional): assets to fetch info from.
            expression (str, optional): rio-tiler expression for the asset list (e.g. asset1/asset2+asset3).
            asset_indexes (dict, optional): Band indexes for each asset (e.g {"asset1": 1, "asset2": (1, 2,)}).
            kwargs (optional): Options to forward to the `self.reader.part` method.

        Returns:
            rio_tiler.models.ImageData: ImageData instance with data, mask and tile spatial info.

        """
        assets = cast_to_sequence(assets)
        if assets and expression:
            warnings.warn(
                "Both expression and assets passed; expression will overwrite assets parameter.",
                ExpressionMixingWarning,
                stacklevel=2,
            )

        if expression:
            assets = self.parse_expression(expression, asset_as_band=asset_as_band)

        if not assets and self.default_assets:
            warnings.warn(
                f"No assets/expression passed, defaults to {self.default_assets}",
                UserWarning,
                stacklevel=2,
            )
            assets = self.default_assets

        if not assets:
            raise MissingAssets(
                "assets must be passed via `expression` or `assets` options, or via class-level `default_assets`."
            )

        asset_indexes = asset_indexes or {}

        # We fall back to `indexes` if provided
        indexes = kwargs.pop("indexes", None)

        def _reader(asset_name: str, *args: Any, **kwargs: Any) -> ImageData:
            idx = asset_indexes.get(asset_name) or indexes

            # Parse Asset `{asset}|{variable}`
            variable = asset_name.split("|")[1] if "|" in asset_name else None
            asset = asset_name.split("|")[0]

            read_options = {**kwargs, "variables": [variable]} if variable else kwargs

            # TODO: Parse Asset `{asset}|{bidx}` ? for COG

            asset_info = self._get_asset_info(asset)
            reader, options = self._get_reader(asset_info)
            uri = asset_info["url"]

            # TODO: add s3 alternate in STAC Items
            uri = uri.replace(
                "https://esa-zarr-sentinel-explorer-fra.s3.de.io.cloud.ovh.net/",
                "s3://esa-zarr-sentinel-explorer-fra/",
            )

            with self.ctx(**asset_info.get("env", {})):
                with reader(
                    uri,
                    tms=self.tms,
                    **{**self.reader_options, **options},
                ) as src:
                    # Note: Check if the `variable` name is a
                    metadata = asset_info.get("metadata", {})
                    if (bands := metadata.get("bands", {})) and (
                        variables := read_options.pop("variables", None)
                    ):
                        common_to_variable = {
                            b["eo:common_name"]
                            if "eo:common_name" in b
                            else b["name"]: b["name"]
                            for b in bands
                        }
                        read_options["variables"] = [
                            common_to_variable.get(v, v) for v in variables
                        ]

                    data = src.part(*args, indexes=idx, **read_options)

                    self._update_statistics(
                        data,
                        indexes=idx,
                        statistics=asset_info.get("dataset_statistics"),
                    )

                    metadata = data.metadata or {}
                    if m := asset_info.get("metadata"):
                        metadata.update(m)
                    data.metadata = {asset: metadata}

                    if asset_as_band:
                        if len(data.band_names) > 1:
                            raise AssetAsBandError(
                                "Can't use `asset_as_band` for multibands asset"
                            )
                        data.band_names = [asset_name]
                    else:
                        data.band_names = [f"{asset_name}_{n}" for n in data.band_names]

                    return data

        # Check intersection of bbox with self bounds
        # get method crs from kwargs for bbox reprojection
        # first compare CRS of bbox and self.bounds and reproject the bbox if needed
        # Then check intersection and discard reading if no intersection

        # Filter assets based on bounds intersection to prevent NoDataInBounds exceptions
        valid_assets = []
        for asset_name in assets:
            asset = asset_name.split("|")[0]
            try:
                asset_info = self._get_asset_info(asset)
                reader, options = self._get_reader(asset_info)
                uri = asset_info["url"]

                # Quick bounds check without full data loading
                with self.ctx(**asset_info.get("env", {})):
                    with reader(uri, **{**self.reader_options, **options}) as src:
                        # Get CRS from kwargs or use source CRS
                        bounds_crs = kwargs.get("bounds_crs", src.crs)

                        # Transform bbox to source CRS if needed
                        if bounds_crs != src.crs:
                            from rasterio.warp import transform_bounds

                            transformed_bbox = transform_bounds(
                                bounds_crs, src.crs, *bbox
                            )
                        else:
                            transformed_bbox = bbox

                        # Check if bbox intersects with source bounds
                        src_bounds = src.bounds
                        if (
                            transformed_bbox[2] > src_bounds[0]
                            and transformed_bbox[0] < src_bounds[2]
                            and transformed_bbox[3] > src_bounds[1]
                            and transformed_bbox[1] < src_bounds[3]
                        ):
                            valid_assets.append(asset_name)
            except Exception:
                # If bounds check fails, skip this asset
                continue

        # If no valid assets, return empty ImageData instead of failing
        if not valid_assets:
            empty_data = np.full((1, 256, 256), 0, dtype=np.float32)
            return ImageData(
                array=empty_data,
                crs=self.tms.rasterio_crs,
                bounds=bbox,
                band_names=["empty"],
            )

        img = multi_arrays(
            valid_assets, _reader, bbox, allowed_exceptions=(NoDataInBounds,), **kwargs
        )
        if expression:
            return img.apply_expression(expression)

        return img

    def tile(  # noqa: C901
        self,
        tile_x: int,
        tile_y: int,
        tile_z: int,
        assets: Union[Sequence[str], str] | None = None,
        expression: str | None = None,
        asset_indexes: Dict[str, Indexes] | None = None,
        asset_as_band: bool = False,
        **kwargs: Any,
    ) -> ImageData:
        """Read and merge Tile from multiple assets."""
        assets = cast_to_sequence(assets)
        if assets and expression:
            warnings.warn(
                "Both expression and assets passed; expression will overwrite assets parameter.",
                ExpressionMixingWarning,
                stacklevel=2,
            )

        if expression:
            assets = self.parse_expression(expression, asset_as_band=asset_as_band)

        if not assets and self.default_assets:
            warnings.warn(
                f"No assets/expression passed, defaults to {self.default_assets}",
                UserWarning,
                stacklevel=2,
            )
            assets = self.default_assets

        if not assets:
            raise MissingAssets(
                "assets must be passed via `expression` or `assets` options, or via class-level `default_assets`."
            )

        asset_indexes = asset_indexes or {}

        # We fall back to `indexes` if provided
        indexes = kwargs.pop("indexes", None)

        def _reader(asset_name: str, *args: Any, **kwargs: Any) -> ImageData:
            idx = asset_indexes.get(asset_name) or indexes

            # Parse Asset `{asset}|{variable}`
            variable = asset_name.split("|")[1] if "|" in asset_name else None
            asset = asset_name.split("|")[0]

            read_options = {**kwargs, "variables": [variable]} if variable else kwargs

            # TODO: Parse Asset `{asset}|{bidx}` ? for COG

            asset_info = self._get_asset_info(asset)
            reader, options = self._get_reader(asset_info)
            uri = asset_info["url"]

            # TODO: add s3 alternate in STAC Items
            uri = uri.replace(
                "https://esa-zarr-sentinel-explorer-fra.s3.de.io.cloud.ovh.net/",
                "s3://esa-zarr-sentinel-explorer-fra/",
            )

            with self.ctx(**asset_info.get("env", {})):
                with reader(
                    uri,
                    tms=self.tms,
                    **{**self.reader_options, **options},
                ) as src:
                    # Note: Check if the `variable` name is a
                    metadata = asset_info.get("metadata", {})
                    if (bands := metadata.get("bands", {})) and (
                        variables := read_options.pop("variables", None)
                    ):
                        common_to_variable = {
                            b["eo:common_name"]
                            if "eo:common_name" in b
                            else b["name"]: b["name"]
                            for b in bands
                        }
                        read_options["variables"] = [
                            common_to_variable.get(v, v) for v in variables
                        ]

                    data = src.tile(*args, indexes=idx, **read_options)

                    self._update_statistics(
                        data,
                        indexes=idx,
                        statistics=asset_info.get("dataset_statistics"),
                    )

                    metadata = data.metadata or {}
                    if m := asset_info.get("metadata"):
                        metadata.update(m)
                    data.metadata = {asset: metadata}

                    if asset_as_band:
                        if len(data.band_names) > 1:
                            raise AssetAsBandError(
                                "Can't use `asset_as_band` for multibands asset"
                            )
                        data.band_names = [asset_name]
                    else:
                        data.band_names = [f"{asset_name}_{n}" for n in data.band_names]

                    return data

        # Filter assets based on tile bounds intersection to prevent NoDataInBounds exceptions
        tile_bbox = self.tms.xy_bounds(tile_x, tile_y, tile_z)
        valid_assets = []
        for asset_name in assets:
            asset = asset_name.split("|")[0]
            try:
                asset_info = self._get_asset_info(asset)
                reader, options = self._get_reader(asset_info)
                uri = asset_info["url"]

                # Quick bounds check without full data loading
                with self.ctx(**asset_info.get("env", {})):
                    with reader(uri, **{**self.reader_options, **options}) as src:
                        # Transform tile bbox to source CRS if needed
                        if self.tms.rasterio_crs != src.crs:
                            from rasterio.warp import transform_bounds

                            transformed_bbox = transform_bounds(
                                self.tms.rasterio_crs, src.crs, *tile_bbox
                            )
                        else:
                            transformed_bbox = tile_bbox

                        # Check if tile bbox intersects with source bounds
                        src_bounds = src.bounds
                        if (
                            transformed_bbox[2] > src_bounds[0]
                            and transformed_bbox[0] < src_bounds[2]
                            and transformed_bbox[3] > src_bounds[1]
                            and transformed_bbox[1] < src_bounds[3]
                        ):
                            valid_assets.append(asset_name)
            except Exception:
                # If bounds check fails, skip this asset
                continue

        # If no valid assets, return empty ImageData instead of failing
        if not valid_assets:
            empty_data = np.full((1, 256, 256), 0, dtype=np.float32)
            return ImageData(
                array=empty_data,
                crs=self.tms.rasterio_crs,
                bounds=tile_bbox,
                band_names=["empty"],
            )

        # Handle corrupted data gracefully - allow processing to continue even if some rasters fail
        img = multi_arrays(
            valid_assets,
            _reader,
            tile_x,
            tile_y,
            tile_z,
            **kwargs,
        )
        if expression:
            return img.apply_expression(expression)

        return img


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
        spatial_extent: Optional[BoundingBox] = None,
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
            max_items=processing_settings.max_items,
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

        # Use create_tasks with threads=0 to ensure lazy loading (partial functions)
        tasks = create_tasks(
            _reader,
            items,
            threads=0,  # Force no threading to use partial functions for lazy loading
            bbox=bbox,
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
            key_fn=lambda asset: asset.id,
            timestamp_fn=lambda asset: _props_to_datetime(asset.properties),
            allowed_exceptions=(TileOutsideBounds,),
        )
