"""titiler.eopf.reader."""

from __future__ import annotations

import logging
import math
import os
import pickle
import re
import warnings
from functools import cache, cached_property, lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal
from urllib.parse import urlparse

import attr
import numpy
import obstore
import xarray
from affine import Affine
from morecantile import Tile, TileMatrixSet
from rasterio import windows
from rasterio.crs import CRS
from rasterio.features import bounds as featureBounds
from rasterio.transform import array_bounds, from_bounds
from rasterio.warp import calculate_default_transform, transform_bounds
from rio_tiler.constants import WEB_MERCATOR_TMS, WGS84_CRS
from rio_tiler.errors import (
    ExpressionMixingWarning,
    InvalidExpression,
    InvalidGeographicBounds,
    RioTilerError,
)
from rio_tiler.io.base import BaseReader
from rio_tiler.io.xarray import XarrayReader
from rio_tiler.models import BandStatistics, ImageData, Info, PointData
from rio_tiler.reader import _get_width_height, _missing_size
from rio_tiler.types import BBox
from xarray.backends.api import _maybe_create_default_indexes
from zarr.storage import ObjectStore

from titiler.xarray.io import _parse_dsl

from .cache import RedisCache
from .settings import CacheSettings

logger = logging.getLogger(__name__)

try:
    import redis

except ImportError:  # pragma: nocover
    redis = None  # type: ignore


try:
    from obstore.auth.boto3 import Boto3CredentialProvider

    HAS_BOTO3_PROVIDER = True
except ImportError:
    HAS_BOTO3_PROVIDER = False

sel_methods = Literal["nearest", "pad", "ffill", "backfill", "bfill"]

# GeoZarr V1
spatial_keys = {"spatial:shape", "spatial:transform"}


@lru_cache(maxsize=1)
def cache_settings() -> CacheSettings:
    """This function returns a cached instance of the CacheSettings object."""
    return CacheSettings()


class MissingVariables(RioTilerError):
    """Missing Variables."""


@cache
def open_dataset(src_path: str, **kwargs: Any) -> xarray.DataTree:
    """Open Xarray dataset

    Args:
        src_path (str): dataset path.

    Returns:
        xarray.DataTree

    """
    parsed = urlparse(src_path)
    if not parsed.scheme:
        src_path = str(Path(src_path).resolve())
        src_path = "file://" + src_path

    def _open_dataset(src_path: str) -> xarray.DataTree:
        # Check if AWS_PROFILE is set and we're dealing with an S3 URL
        aws_profile = os.environ.get("AWS_PROFILE")
        if aws_profile and parsed.scheme == "s3" and HAS_BOTO3_PROVIDER:
            # Use Boto3CredentialProvider for AWS profile support
            from obstore.store import S3Store

            # Extract bucket and key from S3 URL
            bucket = parsed.netloc
            key = parsed.path.lstrip("/")

            store = S3Store(
                bucket,
                credential_provider=Boto3CredentialProvider(),
                region=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
                endpoint=os.environ.get("AWS_ENDPOINT_URL", None),
                virtual_hosted_style_request=False,
                prefix=key,
            )

            # Create the zarr store with the configured S3 store
            zarr_store = ObjectStore(store=store, read_only=True)
        else:
            # Use the default obstore.store.from_url method
            store = obstore.store.from_url(src_path)
            zarr_store = ObjectStore(store=store, read_only=True)

        return xarray.open_datatree(
            zarr_store,
            decode_times=True,
            decode_coords="all",
            create_default_indexes=False,
            # By default xarray will try to load the consolidated metadata
            consolidated=True,
            engine="zarr",
        )

    if cache_settings().enable and cache_settings().host:
        pool = RedisCache.get_instance(
            cache_settings().host,  # type: ignore
            cache_settings().port,
            cache_settings().password,
        )
        cache_client = redis.Redis(connection_pool=pool)
        if data_bytes := cache_client.get(src_path):
            logger.info(f"Cache - found dataset in Cache {src_path}")
            dt = pickle.loads(data_bytes)
        else:
            dt = _open_dataset(src_path)
            logger.info(f"Cache - adding dataset in Cache {src_path}")
            cache_client.set(src_path, pickle.dumps(dt), ex=300)
    else:
        dt = _open_dataset(src_path)

    return dt


def get_multiscale_level(
    dt: xarray.DataTree,
    variable: str,
    target_res: float,
    zoom_level_strategy: Literal["AUTO", "LOWER", "UPPER"] = "AUTO",
) -> str:
    """Return the multiscale level corresponding to the desired resolution."""
    ms_resolutions: list[tuple[str, float]]
    # GeoZarr V1
    if "layout" in dt.attrs.get("multiscales", {}):
        ms_resolutions = [
            (
                ms["asset"],
                min(abs(ms["spatial:transform"][0]), abs(ms["spatial:transform"][4])),
            )
            for ms in dt.attrs["multiscales"]["layout"]
        ]

    # GeoZarr V0
    elif "tile_matrix_set" in dt.attrs.get("multiscales", {}):
        ms_resolutions = [
            (mt["id"], mt["cellSize"])
            for mt in dt.attrs["multiscales"]["tile_matrix_set"]["tileMatrices"]
            if variable in dt[mt["id"]].data_vars
        ]

    else:
        raise ValueError(
            "Multiscale group must have either 'tile_matrix_set' or 'layout' in its attributes."
        )

    # Based on aiocogeo:
    # https://github.com/geospatial-jeff/aiocogeo/blob/5a1d32c3f22c883354804168a87abb0a2ea1c328/aiocogeo/partial_reads.py#L113-L147
    percentage = {"AUTO": 50, "LOWER": 100, "UPPER": 0}.get(zoom_level_strategy, 50)

    # Iterate over zoom levels from lowest/coarsest to highest/finest. If the `target_res` is more than `percentage`
    # percent of the way from the zoom level below to the zoom level above, then upsample the zoom level below, else
    # downsample the zoom level above.
    available_resolutions = sorted(ms_resolutions, key=lambda x: x[1], reverse=True)
    if len(available_resolutions) == 1:
        return available_resolutions[0][0]

    for i in range(0, len(available_resolutions) - 1):
        _, res_current = available_resolutions[i]
        _, res_higher = available_resolutions[i + 1]
        threshold = res_higher - (res_higher - res_current) * (percentage / 100.0)
        if target_res > threshold or target_res == res_current:
            return available_resolutions[i][0]

    # Default level is the first ms level
    return ms_resolutions[0][0]


def _validate_zarr(ds: xarray.Dataset) -> bool:
    if "x" not in ds.dims and "y" not in ds.dims:
        try:
            _ = next(
                name
                for name in ["lat", "latitude", "LAT", "LATITUDE", "Lat"]
                if name in ds.dims
            )
            _ = next(
                name
                for name in ["lon", "longitude", "LON", "LONGITUDE", "Lon"]
                if name in ds.dims
            )
        except StopIteration:
            return False

    # NOTE: ref: https://github.com/EOPF-Explorer/data-model/issues/12
    if not ds.rio.crs:
        return False

    return True


def _arrange_dims(da: xarray.DataArray) -> xarray.DataArray:
    """Arrange coordinates and time dimensions.

    An rioxarray.exceptions.InvalidDimensionOrder error is raised if the coordinates are not in the correct order time, y, and x.
    See: https://github.com/corteva/rioxarray/discussions/674

    We conform to using x and y as the spatial dimension names..

    """
    if "x" not in da.dims and "y" not in da.dims:
        try:
            latitude_var_name = next(
                name
                for name in ["lat", "latitude", "LAT", "LATITUDE", "Lat"]
                if name in da.dims
            )
            longitude_var_name = next(
                name
                for name in ["lon", "longitude", "LON", "LONGITUDE", "Lon"]
                if name in da.dims
            )
        except StopIteration as e:
            raise ValueError(f"Couldn't find X/Y dimensions in {da.name}") from e

        da = da.rename({latitude_var_name: "y", longitude_var_name: "x"})

    if "TIME" in da.dims:
        da = da.rename({"TIME": "time"})

    if extra_dims := [d for d in da.dims if d not in ["x", "y"]]:
        da = da.transpose(*extra_dims, "y", "x")
    else:
        da = da.transpose("y", "x")

    # If min/max values are stored in `valid_range` we add them in `valid_min/valid_max`
    vmin, vmax = da.attrs.get("valid_min"), da.attrs.get("valid_max")
    if "valid_range" in da.attrs and not (vmin is not None and vmax is not None):
        valid_range = da.attrs.get("valid_range")
        da.attrs.update({"valid_min": valid_range[0], "valid_max": valid_range[1]})

    # Make sure we have a valid CRS
    crs = da.rio.crs
    if not crs:
        crs = WGS84_CRS
        da = da.rio.write_crs(crs)

    if crs == WGS84_CRS and (da.x > 180).any():
        # Adjust the longitude coordinates to the -180 to 180 range
        da = da.assign_coords(x=(da.x + 180) % 360 - 180)

        # Sort the dataset by the updated longitude coordinates
        da = da.sortby(da.x)

    return da


def _has_multiscales(conventions: list[dict]) -> bool:
    return next(
        (
            True
            for c in conventions
            # TODO: if c["name"] == "multiscales"
            if c["uuid"] == "d35379db-88df-4056-af3a-620245f8e347"
        ),
        False,
    )


def _has_spatial(conventions: list[dict]) -> bool:
    return next(
        (
            True
            for c in conventions
            # TODO: if c["name"] == "spatial:"
            if c["uuid"] == "689b58e2-cf7b-45e0-9fff-9cfc0883d6b4"
        ),
        False,
    )


def _has_proj(conventions: list[dict]) -> bool:
    return next(
        (
            True
            for c in conventions
            # TODO: if c["name"] == "proj:"
            if c["uuid"] == "f17cb550-5864-4468-aeb7-f3180cfb622f"
        ),
        False,
    )


def _get_proj_crs(attributes: dict) -> CRS:
    """Get CRS defined by PROJ conventions."""
    proj_string = next(
        (  # type: ignore
            attributes.get(key)
            for key in ["proj:code", "proj:wkt2", "proj:projjson"]
            if key in attributes
        )
    )
    return CRS.from_user_input(proj_string)


def _get_size(dims: list[str], shape: list[int]) -> tuple[int, int]:
    """Get Height/Width (x, y) dimension from shape/dimension zarr conventions."""
    x_dim = ["lon", "longitude", "easting", "x"]
    y_dim = ["lat", "latitude", "northing", "y"]
    lower_dims = [d.lower() for d in dims]
    try:
        name = next(d for d in x_dim if d in lower_dims)
        width = shape[lower_dims.index(name)]

        name = next(d for d in y_dim if d in lower_dims)
        height = shape[lower_dims.index(name)]
    except StopIteration as e:
        raise ValueError(f"Couldn't find X dimensions in {dims}") from e

    return width, height


def get_target_resolution(
    *,
    input_crs: CRS,
    output_crs: CRS,
    input_bounds: list[float],
    input_height: int,
    input_width: int,
    input_transform: Affine,
    output_bounds: list[float] | None = None,
    output_max_size: int | None = None,
    output_height: int | None = None,
    output_width: int | None = None,
) -> float:
    """Get Target Resolution."""
    # Get Target expected resolution in Dataset CRS
    # 1. Reprojection
    if output_crs and output_crs != input_crs:
        dst_transform = calculate_output_transform(
            input_crs,
            input_bounds,
            input_height,
            input_width,
            output_crs,
            # bounds is supposed to be in output_crs
            out_bounds=output_bounds,
            out_max_size=output_max_size,
            out_height=output_height,
            out_width=output_width,
        )
        return dst_transform.a

    # 2. No Reprojection
    # If no bounds we assume the full dataset bounds
    bounds = output_bounds or input_bounds
    window = windows.from_bounds(*bounds, transform=input_transform)
    if output_max_size:
        output_height, output_width = _get_width_height(
            output_max_size, round(window.height), round(window.width)
        )

    elif _missing_size(output_width, output_height):
        ratio = window.height / window.width
        if output_width:
            output_height = math.ceil(output_width * ratio)
        else:
            output_width = math.ceil(output_height / ratio)

    height = output_height or max(1, round(window.height))
    width = output_width or max(1, round(window.width))
    return from_bounds(*bounds, height=height, width=width).a


@attr.s
class GeoZarrReader(BaseReader):
    """Zarr dataset Reader.

    Attributes:
        input (str): dataset path.
        datatree (xarray.DataTree): Xarray datatree.
        tms (morecantile.TileMatrixSet): TileMatrixSet grid definition. Defaults to `WebMercatorQuad`.
        opener (Callable): Xarray datatree opener. Defaults to `open_dataset`.
        opener_options (dict): Options to forward to the opener callable.

    Examples:
        >>> with GeoZarrReader("geo-zarr-v1",) as src:
                print(src)

    """

    input: str = attr.ib()
    datatree: xarray.DataTree = attr.ib(default=None)

    tms: TileMatrixSet = attr.ib(default=WEB_MERCATOR_TMS)
    minzoom: int = attr.ib(default=None)
    maxzoom: int = attr.ib(default=None)

    opener: Callable[..., xarray.DataTree] = attr.ib(default=open_dataset)
    opener_options: Dict = attr.ib(factory=dict)

    groups: List[str] = attr.ib(init=False)
    variables: List[str] = attr.ib(init=False)

    # Cache for datasets with indexes created, keyed by datatree path.
    # Avoids re-loading coordinate arrays from S3 for the same group.
    _indexed_ds_cache: Dict[str, xarray.Dataset] = attr.ib(init=False, factory=dict)

    # Cache for per-scale bounds to avoid repeated rioxarray computation.
    _bounds_cache: Dict[str, tuple] = attr.ib(init=False, factory=dict)

    def _get_indexed_dataset(self, path: str) -> xarray.Dataset:
        """Get a dataset with default indexes, cached to avoid repeated S3 coordinate reads.

        When opening with create_default_indexes=False, coordinate arrays stay lazy.
        Creating indexes materializes them once into PandasIndex (in-memory).
        This cache ensures that cost is paid only once per unique datatree path.
        """
        if path not in self._indexed_ds_cache:
            ds = self.datatree[path].to_dataset()
            self._indexed_ds_cache[path] = _maybe_create_default_indexes(ds)
        return self._indexed_ds_cache[path]

    def _get_scale_bounds(self, scale_path: str) -> tuple:
        """Get bounds for a scale path, cached to avoid repeated rioxarray computation."""
        if scale_path not in self._bounds_cache:
            ds = self._get_indexed_dataset(scale_path)
            self._bounds_cache[scale_path] = tuple(ds.rio.bounds())
        return self._bounds_cache[scale_path]

    def _get_v1_dataarray(
        self,
        scale_path: str,
        variable: str,
        dims: list[str],
        layout_entries: list[dict],
        scale: str,
        crs: CRS | None = None,
    ) -> xarray.DataArray | None:
        """Get DataArray with synthetic coordinates from V1 spatial metadata.

        Builds coordinate arrays from spatial:transform + spatial:shape so that
        rioxarray can resolve bounds/transform without reading from S3.
        Returns None if spatial metadata is incomplete.
        """
        sel_transform = None
        sel_shape = None

        # Find spatial metadata for the selected scale in layout entries
        for mt in layout_entries:
            if mt["asset"] == scale:
                if spatial_keys.intersection(mt):
                    sel_shape = mt["spatial:shape"]
                    sel_transform = Affine(*mt["spatial:transform"])
                break

        # Fall back to scale group attributes
        if not sel_transform:
            scale_attrs = self.datatree[scale_path].attrs
            if spatial_keys.intersection(scale_attrs):
                sel_shape = scale_attrs["spatial:shape"]
                sel_transform = Affine(*scale_attrs["spatial:transform"])

        if not sel_transform or not sel_shape:
            return None

        # Determine x/y dimension names from spatial:dimensions
        lower_dims = {d.lower(): d for d in dims}
        x_name = next(
            (
                lower_dims[n]
                for n in ["x", "lon", "longitude", "easting"]
                if n in lower_dims
            ),
            None,
        )
        y_name = next(
            (
                lower_dims[n]
                for n in ["y", "lat", "latitude", "northing"]
                if n in lower_dims
            ),
            None,
        )
        if not x_name or not y_name:
            return None

        width, height = _get_size(dims, sel_shape)

        # Synthesize coordinate arrays from transform (pixel-center convention)
        x_coords = (
            numpy.arange(width) * sel_transform.a
            + sel_transform.c
            + sel_transform.a / 2
        )
        y_coords = (
            numpy.arange(height) * sel_transform.e
            + sel_transform.f
            + sel_transform.e / 2
        )

        # Get DataArray without creating indexes (no S3 coordinate reads)
        ds = self.datatree[scale_path].to_dataset()
        da = ds[variable]
        da = da.assign_coords({x_name: x_coords, y_name: y_coords})

        if crs:
            da = da.rio.write_crs(crs)

        # Override the stale GeoTransform stored in spatial_ref (from the
        # original on-disk coords) so rioxarray uses the correct transform.
        da = da.rio.write_transform(sel_transform)

        return da

    def __attrs_post_init__(self):
        """Set bounds and CRS."""
        if not self.datatree:
            self.datatree = self.opener(self.input, **self.opener_options)

        self.groups = self._get_groups()
        self.variables = self._get_variables()

        # There might not be global bounds/CRS for a Zarr Store
        try:
            ds = self.datatree.to_dataset()
            ds = _maybe_create_default_indexes(ds)
            self.bounds = tuple(ds.rio.bounds())
            self.crs = ds.rio.crs or "epsg:4326"

            # adds half x/y resolution on each values
            # https://github.com/corteva/rioxarray/issues/645#issuecomment-1461070634
            xres, yres = map(abs, ds.rio.resolution())
            if self.crs == WGS84_CRS and (
                self.bounds[0] + xres / 2 < -180
                or self.bounds[1] + yres / 2 < -90
                or self.bounds[2] - xres / 2 > 180
                or self.bounds[3] - yres / 2 > 90
            ):
                raise InvalidGeographicBounds(
                    f"Invalid geographic bounds: {self.bounds}. Must be within (-180, -90, 180, 90)."
                )

            self.transform = ds.rio.transform()
            self.height = ds.rio.height
            self.width = ds.rio.width

            # Default to user input or Dataset min/max zoom
            self.minzoom = self.minzoom if self.minzoom is not None else self._minzoom
            self.maxzoom = self.maxzoom if self.maxzoom is not None else self._maxzoom

        except:  # noqa
            self.crs = WGS84_CRS
            minx, miny, maxx, maxy = zip(
                *[self.get_bounds(group, self.crs) for group in self.groups]
            )
            self.bounds = (min(minx), min(miny), max(maxx), max(maxy))

            # Default to user input or TMS min/max zoom
            self.minzoom = (
                self.minzoom if self.minzoom is not None else self.tms.minzoom
            )
            self.maxzoom = (
                self.maxzoom if self.maxzoom is not None else self.tms.maxzoom
            )

    def _get_groups(self) -> List[str]:  # noqa: C901
        """return groups within the datatree."""
        groups: List[str] = []
        ms_groups: List[str] = []

        for g in self.datatree.groups:
            # GeoZarr V1
            if conventions := self.datatree[g].attrs.get("zarr_conventions"):
                # NOTE: should we also check for `statial:` and `proj:` attributes?
                is_geozarr = _has_spatial(conventions) and _has_proj(conventions)
                if _has_multiscales(conventions):
                    ms_groups.append(g)
                    # NOTE: Only support Multiscale groups with spatial/proj
                    if is_geozarr:
                        # validate spatial/proj?
                        groups.append(g)

                else:
                    # NOTE: We skip if group is within a multiscale
                    if any(g.startswith(msg) for msg in ms_groups):
                        continue

                    elif self.datatree[g].data_vars:
                        # NOTE: Only support groups with spatial/proj
                        if is_geozarr:
                            # validate spatial/proj?
                            groups.append(g)

            # GeoZarr V0
            elif "multiscales" in self.datatree[g].attrs:
                ms_groups.append(g)

                # Validate Group using First Level of MultiScale
                scale = self.datatree[g].attrs["multiscales"]["tile_matrix_set"][
                    "tileMatrices"
                ][0]["id"]
                ds = self.datatree[g][scale].to_dataset()
                # NOTE: _validate_zarr only checks dims and CRS attributes,
                # no need to create indexes (avoids eager S3 coordinate reads)
                if _validate_zarr(ds):
                    groups.append(g)

            else:
                # We skip if group is within a multiscale
                if any(g.startswith(msg) for msg in ms_groups):
                    continue

                elif self.datatree[g].data_vars:
                    ds = self.datatree[g].to_dataset()
                    # NOTE: _validate_zarr only checks dims and CRS attributes,
                    # no need to create indexes (avoids eager S3 coordinate reads)
                    if _validate_zarr(ds):
                        groups.append(g)

        return groups

    def _get_variables(self) -> List[str]:
        """Return available variables for a group."""
        variables: List[str] = []

        for g in self.groups:
            # Select a group
            tree = self.datatree[g]

            # If a Group is a Multiscale group then we collect variables from all scales
            # GeoZarr V1
            if _has_multiscales(tree.attrs.get("zarr_conventions", [])):
                all_vars = set()
                for ms_group in tree.groups:
                    all_vars.update(
                        {
                            var
                            for var, data_array in self.datatree[
                                ms_group
                            ].data_vars.items()
                            if data_array.ndim > 0
                        }
                    )
                variables.extend(f"{g}:{v}" for v in sorted(all_vars))

            # GeoZarr V0
            elif "multiscales" in tree.attrs:
                # Get all variables across all multiscale levels
                all_vars = set()
                for matrix in tree.attrs["multiscales"]["tile_matrix_set"][
                    "tileMatrices"
                ]:
                    scale = matrix["id"]
                    if scale in tree:
                        scale_group = tree[scale]
                        # Only include multidimensional data variables (not 0D attributes)
                        all_vars.update(
                            {
                                var
                                for var, data_array in scale_group.data_vars.items()
                                if data_array.ndim > 0
                            }
                        )

                variables.extend(f"{g}:{v}" for v in sorted(all_vars))
            else:
                # Only include multidimensional data variables (not 0D attributes)
                multidim_vars = [
                    var
                    for var, data_array in tree.data_vars.items()
                    if data_array.ndim > 0
                ]
                variables.extend(f"{g}:{v}" for v in multidim_vars)

        return variables

    def get_bounds(self, group: str, crs: CRS = WGS84_CRS) -> BBox:  # noqa: C901
        """Get BBox for a Group."""
        tree = self.datatree[group]

        # GeoZarr V1
        if dims := tree.attrs.get("spatial:dimensions"):
            bounds_crs = _get_proj_crs(tree.attrs)

            # Check top level group attributes
            bbox: list[float] | None = tree.attrs.get("spatial:bbox")
            shape: list[int] | None = None
            transform: Affine | None = None
            if not bbox:
                if spatial_keys.intersection(tree.attrs):
                    shape = tree.attrs["spatial:shape"]
                    transform = Affine(*tree.attrs["spatial:transform"])

                if _has_multiscales(tree.attrs.get("zarr_conventions", [])):
                    # NOTE: Check multiscale layout and group attributes
                    # NOTE: We check only the first Layout
                    scale_layout = tree.attrs["multiscales"]["layout"][0]
                    tree = tree[scale_layout["asset"]]

                    # NOTE: metadata can be stored at both level: Multiscale convention or Group Attributes
                    bbox = scale_layout.get("spatial:bbox") or tree.attrs.get(
                        "spatial:bbox"
                    )
                    if not shape and not transform:
                        if spatial_keys.intersection(scale_layout):
                            shape = scale_layout["spatial:shape"]
                            transform = Affine(*scale_layout["spatial:transform"])
                        elif spatial_keys.intersection(tree.attrs):
                            shape = tree.attrs["spatial:shape"]
                            transform = Affine(*tree.attrs["spatial:transform"])

                if not bbox:
                    if not shape:
                        dataset = self._get_indexed_dataset(tree.path)

                        width, height = dataset.rio.width, dataset.rio.height
                    else:
                        width, height = _get_size(dims, shape)

                    if not transform:
                        dataset = self._get_indexed_dataset(tree.path)
                        transform = dataset.rio.transform()

                    bbox = array_bounds(width, height, transform)  # type: ignore

        # GeoZarr V0
        elif ms := tree.attrs.get("multiscales"):
            scale = ms["tile_matrix_set"]["tileMatrices"][0]["id"]
            ds = self._get_indexed_dataset(
                f"{group}/{scale}" if group != "/" else scale
            )
            bbox = ds.rio.bounds()
            bounds_crs = ds.rio.crs

        # Not GeoZarr
        else:
            ds = self._get_indexed_dataset(group)
            bbox = ds.rio.bounds()
            bounds_crs = ds.rio.crs

        return transform_bounds(bounds_crs, crs, *bbox, densify_pts=21)  # type: ignore

    def _get_zoom(self, ds: xarray.Dataset) -> int:
        """Get MaxZoom for a Group."""
        crs = ds.rio.crs
        tms_crs = self.tms.rasterio_crs
        if crs != tms_crs:
            transform, _, _ = calculate_default_transform(
                crs,
                tms_crs,
                ds.rio.width,
                ds.rio.height,
                *ds.rio.bounds(),
            )
        else:
            transform = ds.rio.transform()

        resolution = max(abs(transform[0]), abs(transform[4]))
        return self.tms.zoom_for_res(resolution)

    # TODO: add cache
    def get_minzoom(self, group: str) -> int:  # noqa: C901
        """Get MinZoom for a Group."""
        tree = self.datatree[group]

        # GeoZarr V1
        if dims := tree.attrs.get("spatial:dimensions"):
            crs = _get_proj_crs(tree.attrs)

            bbox: list[float] | None = tree.attrs.get("spatial:bbox")
            shape: list[int] | None = None
            transform: Affine | None = None

            if spatial_keys.intersection(tree.attrs):
                shape = tree.attrs["spatial:shape"]
                transform = Affine(*tree.attrs["spatial:transform"])

            if _has_multiscales(tree.attrs.get("zarr_conventions", [])):
                # NOTE: is the last layout the lower resolution?
                layout = tree.attrs["multiscales"]["layout"][-1]
                tree = tree[layout["asset"]]

                # NOTE: metadata can be stored at both level: Multiscale convention or Group Attributes
                bbox = (
                    bbox or layout.get("spatial:bbox") or tree.attrs.get("spatial:bbox")
                )
                if spatial_keys.intersection(layout):
                    shape = layout["spatial:shape"]
                    transform = Affine(*layout["spatial:transform"])
                elif spatial_keys.intersection(tree.attrs):
                    shape = tree.attrs["spatial:shape"]
                    transform = Affine(*tree.attrs["spatial:transform"])

            if not transform:
                # Fall back to rioxarray transform
                transform = self._get_indexed_dataset(tree.path).rio.transform()

            try:
                tms_crs = self.tms.rasterio_crs
                if crs != tms_crs:
                    if shape:
                        width, height = _get_size(dims, shape)
                    else:
                        # Fall back to rioxarray shape
                        dataset = self._get_indexed_dataset(tree.path)
                        width, height = dataset.rio.width, dataset.rio.height

                    if not bbox:
                        # NOTE: we could also fall back to rio.bounds() here
                        # but we need height/width + transform to be available
                        # so we use it them to get the bounds
                        bbox = array_bounds(width, height, transform)  # type: ignore

                    transform, _, _ = calculate_default_transform(
                        crs,
                        tms_crs,
                        width,
                        height,
                        *bbox,  # type: ignore
                    )

                resolution = max(abs(transform[0]), abs(transform[4]))  # type: ignore
                return self.tms.zoom_for_res(resolution)

            except:  # noqa
                warnings.warn(
                    f"Cannot determine MinZoom for group {group}.",
                    UserWarning,
                    stacklevel=2,
                )

            return self.tms.minzoom

        # GeoZarr V0
        if ms := tree.attrs.get("multiscales"):
            # Select the last level (should be the lowest/coarsest resolution)
            scale = ms["tile_matrix_set"]["tileMatrices"][-1]["id"]
            ds = self._get_indexed_dataset(
                f"{group}/{scale}" if group != "/" else scale
            )
        else:
            ds = self._get_indexed_dataset(group)

        try:
            return self._get_zoom(ds)
        except:  # noqa
            print("error", ds)
            pass

        return self.tms.minzoom

    # TODO: add cache
    def get_maxzoom(self, group: str) -> int:  # noqa: C901
        """Get MaxZoom for a Group."""
        tree = self.datatree[group]

        # GeoZarr V1
        if dims := tree.attrs.get("spatial:dimensions"):
            crs = _get_proj_crs(tree.attrs)
            bbox: list[float] | None = tree.attrs.get("spatial:bbox")
            shape: list[int] | None = None
            transform: Affine | None = None

            if spatial_keys.intersection(tree.attrs):
                shape = tree.attrs["spatial:shape"]
                transform = Affine(*tree.attrs["spatial:transform"])

            if _has_multiscales(tree.attrs.get("zarr_conventions", [])):
                # NOTE: is the first layout the highest resolution?
                layout = tree.attrs["multiscales"]["layout"][0]
                tree = tree[layout["asset"]]

                # NOTE: metadata can be stored at both level: Multiscale convention or Group Attributes
                bbox = (
                    bbox or layout.get("spatial:bbox") or tree.attrs.get("spatial:bbox")
                )
                if spatial_keys.intersection(layout):
                    shape = layout["spatial:shape"]
                    transform = Affine(*layout["spatial:transform"])
                elif spatial_keys.intersection(tree.attrs):
                    shape = tree.attrs["spatial:shape"]
                    transform = Affine(*tree.attrs["spatial:transform"])

            if not transform:
                # Fall back to rioxarray transform
                transform = self._get_indexed_dataset(tree.path).rio.transform()

            try:
                tms_crs = self.tms.rasterio_crs
                if crs != tms_crs:
                    if shape:
                        width, height = _get_size(dims, shape)
                    else:
                        # Fall back to rioxarray shape
                        dataset = self._get_indexed_dataset(tree.path)
                        width, height = dataset.rio.width, dataset.rio.height

                    if not bbox:
                        # NOTE: we could also fall back to rio.bounds() here
                        # but we need height/width + transform to be available
                        # so we use it them to get the bounds
                        bbox = array_bounds(width, height, transform)  # type: ignore

                    transform, _, _ = calculate_default_transform(
                        crs,
                        tms_crs,
                        width,
                        height,
                        *bbox,  # type: ignore
                    )

                resolution = max(abs(transform[0]), abs(transform[4]))  # type: ignore
                return self.tms.zoom_for_res(resolution)

            except:  # noqa
                warnings.warn(
                    f"Cannot determine MaxZoom for group {group}.",
                    UserWarning,
                    stacklevel=2,
                )

            return self.tms.maxzoom

        # GeoZarr V0
        if ms := tree.attrs.get("multiscales"):
            # Select the first level (should be the highest/finest resolution)
            scale = ms["tile_matrix_set"]["tileMatrices"][0]["id"]
            ds = self._get_indexed_dataset(
                f"{group}/{scale}" if group != "/" else f"/{scale}"
            )
        else:
            ds = self._get_indexed_dataset(group)

        try:
            return self._get_zoom(ds)
        except:  # noqa
            print("error", ds)
            pass

        return self.tms.maxzoom

    def _get_variable(  # noqa: C901
        self,
        group: str,
        variable: str,
        *,
        sel: List[str] | None = None,
        # MultiScale Selection
        bounds: BBox | None = None,
        height: int | None = None,
        width: int | None = None,
        max_size: int | None = None,
        dst_crs: CRS | None = None,
    ) -> xarray.DataArray:
        """Get DataArray from xarray Dataset."""
        if max_size and (width or height):
            warnings.warn(
                "'max_size' will be ignored with with 'height' and 'width' set.",
                UserWarning,
                stacklevel=2,
            )
            max_size = None

        tree = self.datatree[group]

        bbox: list[float] | None = None
        transform: list[float] | Affine | None = None

        # GeoZarr V1
        if dims := tree.attrs.get("spatial:dimensions"):
            logger.info("Multiscale - Selection using GeoZarr V1 (Conventions)")

            bbox = tree.attrs.get("spatial:bbox")
            crs = _get_proj_crs(tree.attrs)

            if _has_multiscales(tree.attrs.get("zarr_conventions", [])):
                # NOTE: Default asset (where variable is present)
                # This assume, the Multiscale are ordered from higher resolution To lower resolution
                try:
                    layout = next(
                        (
                            mt
                            for mt in tree.attrs["multiscales"]["layout"]
                            if variable in tree[mt["asset"]].data_vars
                        )
                    )
                except StopIteration as e:
                    raise MissingVariables(
                        f"Variable '{variable}' not found in any multiscale level of group '{group}'"
                    ) from e

                scale = layout["asset"]  # Default asset from first layout

                shape: list[int] | None = None

                bbox = (
                    bbox
                    or layout.get("spatial:bbox")
                    or tree[scale].attrs.get("spatial:bbox")
                )
                if {"spatial:shape", "spatial:transform"}.intersection(layout):
                    shape = layout["spatial:shape"]
                    transform = Affine(*layout["spatial:transform"])
                elif {"spatial:shape", "spatial:transform"}.intersection(
                    tree[scale].attrs
                ):
                    shape = tree[scale].attrs["spatial:shape"]
                    transform = Affine(*tree[scale].attrs["spatial:transform"])

                layout_height: int
                layout_width: int
                if shape:
                    layout_width, layout_height = _get_size(dims, shape)
                else:
                    # Fall back to rioxarray shape (needs coordinate values)
                    scale_path = f"{group}/{scale}" if group != "/" else scale
                    dataset = self._get_indexed_dataset(scale_path)
                    layout_width, layout_height = dataset.rio.width, dataset.rio.height

                if not transform:
                    # Fall back to rioxarray transform (needs coordinate values)
                    scale_path = f"{group}/{scale}" if group != "/" else scale
                    dataset = self._get_indexed_dataset(scale_path)
                    transform = dataset.rio.transform()

                if not bbox:
                    bbox = array_bounds(layout_width, layout_height, transform)  # type: ignore

                # NOTE: Select a Multiscale Layer based on output resolution
                if any([bounds, height, width, max_size]):
                    target_res = get_target_resolution(
                        input_crs=crs,
                        output_crs=dst_crs,
                        input_bounds=bbox,  # type: ignore
                        input_height=layout_height,
                        input_width=layout_width,
                        input_transform=transform,  # type: ignore
                        output_bounds=bounds,
                        output_max_size=max_size,
                        output_height=height,
                        output_width=width,
                    )

                    scale = get_multiscale_level(tree, variable, target_res)  # type: ignore

                # Select the multiscale group and variable
                scale_path = f"{group}/{scale}" if group != "/" else scale

                # For V1, synthesize coordinates from layout metadata
                # to avoid S3 coordinate reads (sel requires indexes, so fall back)
                da = None
                if not sel:
                    da = self._get_v1_dataarray(
                        scale_path,
                        variable,
                        dims,
                        tree.attrs["multiscales"]["layout"],
                        scale,
                        crs=crs,
                    )
                if da is None:
                    ds = self._get_indexed_dataset(scale_path)
                    da = ds[variable]

                logger.info(
                    f"Multiscale - selecting group {group} with scale {scale} and variable {variable}"
                )

                # NOTE: Make sure the multiscale levels have the same CRS
                # ref: https://github.com/EOPF-Explorer/data-model/issues/12
                da = da.rio.write_crs(crs)

            else:
                # Select Variable (xarray.DataArray)
                # For V1 non-multiscale, synthesize coords from group attrs
                da = None
                if not sel and spatial_keys.intersection(tree.attrs):
                    v1_transform = Affine(*tree.attrs["spatial:transform"])
                    v1_shape = tree.attrs["spatial:shape"]
                    lower_dims = {d.lower(): d for d in dims}
                    x_name = next(
                        (
                            lower_dims[n]
                            for n in ["x", "lon", "longitude", "easting"]
                            if n in lower_dims
                        ),
                        None,
                    )
                    y_name = next(
                        (
                            lower_dims[n]
                            for n in ["y", "lat", "latitude", "northing"]
                            if n in lower_dims
                        ),
                        None,
                    )
                    if x_name and y_name:
                        width, height = _get_size(dims, v1_shape)
                        x_coords = (
                            numpy.arange(width) * v1_transform.a
                            + v1_transform.c
                            + v1_transform.a / 2
                        )
                        y_coords = (
                            numpy.arange(height) * v1_transform.e
                            + v1_transform.f
                            + v1_transform.e / 2
                        )
                        ds = self.datatree[group].to_dataset()
                        da = ds[variable]
                        da = da.assign_coords({x_name: x_coords, y_name: y_coords})
                        da = da.rio.write_crs(crs)
                        da = da.rio.write_transform(v1_transform)

                if da is None:
                    ds = self._get_indexed_dataset(group)
                    da = ds[variable]

        # GeoZarr V0
        elif ms := tree.attrs.get("multiscales"):
            logger.info("Multiscale - Selection using GeoZarr V0 (TMS)")
            crs = CRS.from_user_input(ms["tile_matrix_set"]["crs"])

            # NOTE: Default Scale (where variable is present)
            # This assume, the tile_matrix_set are ordered from higher resolution To lower resolution
            try:
                scale = next(
                    (
                        mt["id"]
                        for mt in ms["tile_matrix_set"]["tileMatrices"]
                        if variable in tree[mt["id"]].data_vars
                    )
                )
            except StopIteration as e:
                raise MissingVariables(
                    f"Variable '{variable}' not found in any multiscale level of group '{group}'"
                ) from e

            default_dataset = self._get_indexed_dataset(
                f"{group}/{scale}" if group != "/" else scale
            )
            transform = default_dataset.rio.transform()
            bbox = default_dataset.rio.bounds()
            layout_height = default_dataset.rio.height
            layout_width = default_dataset.rio.width

            if any([bounds, height, width, max_size]):
                target_res = get_target_resolution(
                    input_crs=crs,
                    output_crs=dst_crs,
                    input_bounds=bbox,  # type: ignore
                    input_height=layout_height,
                    input_width=layout_width,
                    input_transform=transform,  # type: ignore
                    output_bounds=bounds,
                    output_max_size=max_size,
                    output_height=height,
                    output_width=width,
                )
                scale = get_multiscale_level(tree, variable, target_res)  # type: ignore

            # Select the multiscale group and variable
            scale_path = f"{group}/{scale}" if group != "/" else scale
            ds = self._get_indexed_dataset(scale_path)
            da = ds[variable]

            logger.info(
                f"Multiscale - selecting group {group} with scale {scale} and variable {variable}"
            )

            # NOTE: Make sure the multiscale levels have the same CRS
            # ref: https://github.com/EOPF-Explorer/data-model/issues/12
            da = da.rio.write_crs(crs)

        else:
            # Select Variable (xarray.DataArray)
            ds = self._get_indexed_dataset(group)
            da = ds[variable]

        for selector in _parse_dsl(sel):
            dimension = selector["dimension"]
            values = selector["values"]
            method = selector["method"]

            # TODO: add more casting
            # cast string to dtype of the dimension
            if da[dimension].dtype != "O":
                values = [da[dimension].dtype.type(v) for v in values]

            da = da.sel(
                {dimension: values[0] if len(values) < 2 else values},
                method=method,
            )

        da = _arrange_dims(da)
        assert len(da.dims) in [
            2,
            3,
        ], "rio_tiler.io.xarray.DatasetReader can only work with 2D or 3D DataArray"

        return da

    @cached_property
    def _variable_idx(self) -> Dict[str, str]:
        return {v: f"var{ix}" for ix, v in enumerate(self.variables)}

    def parse_expression(self, expression: str) -> List[str]:
        """Parse rio-tiler band math expression."""
        if "eval" in expression:
            raise InvalidExpression("Invalid expression")

        input_assets = "|".join(re.escape(key) for key in self.variables)
        _re = re.compile(rf"(?<!\w)({input_assets})(?!\w)")
        variables = list(set(re.findall(_re, expression)))
        if not variables:
            raise InvalidExpression(
                f"Could not find any valid variables in '{expression}' expression"
            )

        return variables

    def _convert_expression_to_index(self, expression: str) -> str:
        input_assets = "|".join(re.escape(key) for key in self.variables)
        _re = re.compile(rf"(?<!\w)({input_assets})(?!\w)")
        return _re.sub(lambda x: self._variable_idx[x.group()], expression)

    def _convert_expression_from_index(self, expression: str) -> str:
        input_assets = "|".join(re.escape(key) for key in self._variable_idx.values())
        _re = re.compile(rf"(?<!\w)({input_assets})(?!\w)")
        _variable_idx = {v: k for k, v in self._variable_idx.items()}
        return _re.sub(lambda x: _variable_idx[x.group()], expression)

    def info(  # type: ignore
        self,
        *,
        variables: List[str] | None = None,
        sel: List[str] | None = None,
    ) -> Dict[str, Info]:
        """Return xarray.DataArray info.

        Variables that fail to load will be skipped and logged as warnings.
        """
        variables = variables or self.variables

        # Build result dictionary, skipping variables that failed
        result = {}
        for gv in variables:
            try:
                group, variable = gv.split(":") if ":" in gv else ("/", gv)
                if sel:
                    # When dimension selection is needed, use full _get_variable path
                    info_data = self._get_info_via_reader(
                        group,
                        variable,
                        gv,
                        sel,
                    )
                else:
                    # Fast path: build Info directly from metadata
                    info_data = self._build_info_fast(group, variable, gv)
                if info_data is not None:
                    result[gv] = info_data
            except Exception as e:
                logger.info(f"Failed to get info for variable '{gv}': {e!s}")
        return result

    def _get_info_via_reader(
        self,
        group: str,
        variable: str,
        full_name: str,
        sel: List[str],
    ) -> Info | None:
        """Get info via XarrayReader (fallback for sel/method cases)."""
        with XarrayReader(
            self._get_variable(group, variable, sel=sel),
        ) as da:
            return da.info()

    def _build_info_fast(  # noqa: C901
        self,
        group: str,
        variable: str,
        full_name: str,
    ) -> Info | None:
        """Build Info directly from metadata, bypassing XarrayReader overhead.

        Avoids the expensive XarrayReader.__init__ (bounds/transform/resolution
        computation via rioxarray) and redundant write_crs calls.
        """
        from rio_tiler.utils import CRS_to_uri

        tree = self.datatree[group]
        variable_name = full_name.split(":")[-1] if ":" in full_name else full_name

        # Get the raw DataArray and spatial metadata based on group type
        # GeoZarr V1
        if tree.attrs.get("spatial:dimensions"):
            crs = _get_proj_crs(tree.attrs)
            if _has_multiscales(tree.attrs.get("zarr_conventions", [])):
                try:
                    layout = next(
                        mt
                        for mt in tree.attrs["multiscales"]["layout"]
                        if variable in tree[mt["asset"]].data_vars
                    )
                except StopIteration as e:
                    raise MissingVariables(
                        f"Variable '{variable}' not found in any multiscale level of group '{group}'"
                    ) from e
                scale = layout["asset"]
                scale_path = f"{group}/{scale}" if group != "/" else scale
                da = self.datatree[scale_path][variable]

                # Try to get bounds from attributes
                bbox = tree.attrs.get("spatial:bbox")
                if not bbox:
                    bbox = layout.get("spatial:bbox") or tree[scale].attrs.get(
                        "spatial:bbox"
                    )
                if not bbox:
                    dims = tree.attrs["spatial:dimensions"]
                    shape = layout.get("spatial:shape") or tree[scale].attrs.get(
                        "spatial:shape"
                    )
                    transform = layout.get("spatial:transform") or tree[
                        scale
                    ].attrs.get("spatial:transform")
                    if shape and transform:
                        w, h = _get_size(dims, shape)
                        bbox = array_bounds(w, h, Affine(*transform))
                    else:
                        bbox = self._get_scale_bounds(scale_path)
                bounds = tuple(bbox)
            else:
                da = self.datatree[group][variable]
                bbox = tree.attrs.get("spatial:bbox")
                if not bbox:
                    bbox = self._get_scale_bounds(group)
                bounds = tuple(bbox)

        # GeoZarr V0
        elif ms := tree.attrs.get("multiscales"):
            crs = CRS.from_user_input(ms["tile_matrix_set"]["crs"])
            try:
                scale = next(
                    mt["id"]
                    for mt in ms["tile_matrix_set"]["tileMatrices"]
                    if variable in tree[mt["id"]].data_vars
                )
            except StopIteration as e:
                raise MissingVariables(
                    f"Variable '{variable}' not found in any multiscale level of group '{group}'"
                ) from e
            scale_path = f"{group}/{scale}" if group != "/" else scale
            da = self.datatree[scale_path][variable]
            bounds = self._get_scale_bounds(scale_path)

        # Plain group
        else:
            ds = self._get_indexed_dataset(group)
            crs = ds.rio.crs or CRS.from_user_input("epsg:4326")
            da = ds[variable]
            bounds = self._get_scale_bounds(group)

        # Get width/height from DataArray dimensions
        x_names = ["x", "lon", "longitude", "easting"]
        y_names = ["y", "lat", "latitude", "northing"]
        lower_dims = {d.lower(): d for d in da.dims}
        x_dim = next((lower_dims[n] for n in x_names if n in lower_dims), None)
        y_dim = next((lower_dims[n] for n in y_names if n in lower_dims), None)
        width = da.sizes[x_dim] if x_dim else 0
        height = da.sizes[y_dim] if y_dim else 0

        # Non-spatial dimensions
        spatial_exclude = {x_dim, y_dim, "spatial_ref", "crs_wkt", "grid_mapping"}
        non_spatial_dims = [d for d in da.dims if d not in spatial_exclude]

        metadata = [band.attrs for d in non_spatial_dims for band in da[d]] or [{}]
        count = 1
        for d in non_spatial_dims:
            count *= da.sizes[d]

        nodata_type = "Nodata" if da.rio.nodata is not None else "None"

        crs_str = CRS_to_uri(crs) or crs.to_wkt()

        meta = {
            "bounds": bounds,
            "crs": crs_str,
            "band_metadata": [(f"b{ix}", v) for ix, v in enumerate(metadata, 1)],
            "band_descriptions": [
                (f"b{ix}", variable_name) for ix in range(1, count + 1)
            ],
            "dtype": str(da.dtype),
            "nodata_type": nodata_type,
            "name": da.name,
            "count": count,
            "width": width,
            "height": height,
            "dimensions": da.dims,
            "attrs": {
                k: (v.tolist() if isinstance(v, (numpy.ndarray, numpy.generic)) else v)
                for k, v in da.attrs.items()
            },
        }
        return Info(**meta)

    def statistics(  # type: ignore
        self,
        *args: Any,
        variables: List[str] | None = None,
        expression: str | None = None,
        sel: List[str] | None = None,
        **kwargs: Any,
    ) -> Dict[str, Dict[str, BandStatistics]]:
        """Return statistics from a dataset."""
        raise NotImplementedError

    def tile(  # type: ignore
        self,
        tile_x: int,
        tile_y: int,
        tile_z: int,
        *args: Any,
        variables: List[str] | None = None,
        expression: str | None = None,
        tilesize: int = 256,
        sel: List[str] | None = None,
        **kwargs: Any,
    ) -> ImageData:
        """Read a Web Map tile from a dataset."""
        tile_bounds = tuple(self.tms.xy_bounds(Tile(x=tile_x, y=tile_y, z=tile_z)))
        dst_crs = self.tms.rasterio_crs

        img_stack: List[ImageData] = []

        if variables and expression:
            warnings.warn(
                "Both expression and assets passed; expression will overwrite assets parameter.",
                ExpressionMixingWarning,
                stacklevel=2,
            )

        if expression:
            variables = self.parse_expression(expression)

        if not variables:
            raise MissingVariables(
                "`variables` must be passed via `expression` or `variables` options."
            )

        for gv in variables:
            group, variable = gv.split(":") if ":" in gv else ("/", gv)
            with XarrayReader(
                self._get_variable(
                    group,
                    variable,
                    sel=sel,
                    bounds=tile_bounds,
                    height=tilesize,
                    width=tilesize,
                    dst_crs=dst_crs,
                ),
                tms=self.tms,
            ) as da:
                img = da.tile(
                    tile_x,
                    tile_y,
                    tile_z,
                    *args,
                    tilesize=tilesize,
                    **kwargs,
                )
                if expression:
                    if len(img.band_names) > 1:
                        raise ValueError("Can't use `expression` for multidim dataset")
                    # NOTE: create band_names in form of Var{ix} used later for expressions
                    img.band_names = [self._variable_idx[gv]]

                if len(img.band_names) > 1 or sel:
                    img.band_descriptions = [f"{gv}|{b}" for b in img.band_descriptions]
                else:
                    img.band_descriptions = [gv]

                img_stack.append(img)

        img = ImageData.create_from_list(img_stack)

        if expression:
            # NOTE: translate expression from {group:variable} to Var{ix}
            expression = self._convert_expression_to_index(expression)

            # NOTE: `apply_expression` method uses band_names (e.g b1) not band_descriptions
            img = img.apply_expression(expression)

            # NOTE: transform expression back
            img.band_descriptions = [
                self._convert_expression_from_index(b) for b in img.band_descriptions
            ]

        img.band_names = [f"b{ix + 1}" for ix in range(img.count)]
        img.assets = [self.input]

        return img

    def part(
        self,
        bbox: BBox,
        dst_crs: CRS | None = None,
        bounds_crs: CRS = WGS84_CRS,
        variables: List[str] | None = None,
        expression: str | None = None,
        max_size: int | None = None,
        height: int | None = None,
        width: int | None = None,
        sel: List[str] | None = None,
        **kwargs: Any,
    ) -> ImageData:
        """Read part of a dataset."""
        dst_crs = dst_crs or bounds_crs

        bounds_in_dst_crs = (
            transform_bounds(bounds_crs, dst_crs, *bbox, densify_pts=21)
            if dst_crs != bounds_crs
            else bbox
        )

        img_stack: List[ImageData] = []

        if variables and expression:
            warnings.warn(
                "Both expression and assets passed; expression will overwrite assets parameter.",
                ExpressionMixingWarning,
                stacklevel=2,
            )

        if expression:
            variables = self.parse_expression(expression)

        if not variables:
            raise MissingVariables(
                "`variables` must be passed via `expression` or `variables` options."
            )

        for gv in variables:
            group, variable = gv.split(":") if ":" in gv else ("/", gv)
            with XarrayReader(
                self._get_variable(
                    group,
                    variable,
                    sel=sel,
                    max_size=max_size,
                    height=height,
                    width=width,
                    bounds=bounds_in_dst_crs,
                    dst_crs=dst_crs,
                ),
                tms=self.tms,
            ) as da:
                img = da.part(
                    bbox,
                    dst_crs=dst_crs,
                    bounds_crs=bounds_crs,
                    max_size=max_size,
                    height=height,
                    width=width,
                    **kwargs,
                )
                if expression:
                    if len(img.band_names) > 1:
                        raise ValueError("Can't use `expression` for multidim dataset")
                    # NOTE: create band_names in form of Var{ix} used later for expressions
                    img.band_names = [self._variable_idx[gv]]

                if len(img.band_names) > 1 or sel:
                    img.band_descriptions = [f"{gv}|{b}" for b in img.band_descriptions]
                else:
                    img.band_descriptions = [gv]

                img_stack.append(img)

        img = ImageData.create_from_list(img_stack)

        if expression:
            # NOTE: translate expression from {group:variable} to Var{ix}
            expression = self._convert_expression_to_index(expression)

            # NOTE: `apply_expression` method uses band_names (e.g b1) not band_descriptions
            img = img.apply_expression(expression)

            # NOTE: transform expression back
            img.band_descriptions = [
                self._convert_expression_from_index(b) for b in img.band_descriptions
            ]

        img.band_names = [f"b{ix + 1}" for ix in range(img.count)]
        img.assets = [self.input]

        return img

    def preview(
        self,
        *args: Any,
        variables: List[str] | None = None,
        expression: str | None = None,
        max_size: int | None = 1024,
        height: int | None = None,
        width: int | None = None,
        sel: List[str] | None = None,
        dst_crs: CRS | None = None,
        **kwargs: Any,
    ) -> ImageData:
        """Return a preview of a dataset."""
        img_stack: List[ImageData] = []

        if variables and expression:
            warnings.warn(
                "Both expression and assets passed; expression will overwrite assets parameter.",
                ExpressionMixingWarning,
                stacklevel=2,
            )

        if expression:
            variables = self.parse_expression(expression)

        if not variables:
            raise MissingVariables(
                "`variables` must be passed via `expression` or `variables` options."
            )

        for gv in variables:
            group, variable = gv.split(":") if ":" in gv else ("/", gv)
            with XarrayReader(
                self._get_variable(
                    group,
                    variable,
                    sel=sel,
                    max_size=max_size,
                    height=height,
                    width=width,
                    dst_crs=dst_crs,
                ),
                tms=self.tms,
            ) as da:
                img = da.preview(
                    *args,
                    max_size=max_size,
                    height=height,
                    width=width,
                    dst_crs=dst_crs,
                    **kwargs,
                )
                if expression:
                    if len(img.band_names) > 1:
                        raise ValueError("Can't use `expression` for multidim dataset")
                    # NOTE: create band_names in form of Var{ix} used later for expressions
                    img.band_names = [self._variable_idx[gv]]

                if len(img.band_names) > 1 or sel:
                    img.band_descriptions = [f"{gv}|{b}" for b in img.band_descriptions]
                else:
                    img.band_descriptions = [gv]

                img_stack.append(img)

        img = ImageData.create_from_list(img_stack)

        if expression:
            # NOTE: translate expression from {group:variable} to Var{ix}
            expression = self._convert_expression_to_index(expression)

            # NOTE: `apply_expression` method uses band_names (e.g b1) not band_descriptions
            img = img.apply_expression(expression)

            # NOTE: transform expression back
            img.band_descriptions = [
                self._convert_expression_from_index(b) for b in img.band_descriptions
            ]

        img.band_names = [f"b{ix + 1}" for ix in range(img.count)]
        img.assets = [self.input]

        return img

    def point(  # type: ignore
        self,
        *args: Any,
        variables: List[str] | None = None,
        expression: str | None = None,
        sel: List[str] | None = None,
        **kwargs: Any,
    ) -> PointData:
        """Read a pixel value from a dataset."""
        pts_stack: List[PointData] = []

        if variables and expression:
            warnings.warn(
                "Both expression and assets passed; expression will overwrite assets parameter.",
                ExpressionMixingWarning,
                stacklevel=2,
            )

        if expression:
            variables = self.parse_expression(expression)

        if not variables:
            raise MissingVariables(
                "`variables` must be passed via `expression` or `variables` options."
            )

        for gv in variables:
            group, variable = gv.split(":") if ":" in gv else ("/", gv)
            with XarrayReader(
                self._get_variable(group, variable, sel=sel),
                tms=self.tms,
            ) as da:
                pt = da.point(*args, **kwargs)
                if expression:
                    if len(pt.band_names) > 1:
                        raise ValueError("Can't use `expression` for multidim dataset")
                    # NOTE: create band_names in form of Var{ix} used later for expressions
                    pt.band_names = [self._variable_idx[gv]]

                if len(pt.band_names) > 1 or sel:
                    pt.band_descriptions = [f"{gv}|{b}" for b in pt.band_descriptions]
                else:
                    pt.band_descriptions = [gv]

                pts_stack.append(pt)

        pt = PointData.create_from_list(pts_stack)
        if expression:
            # edit expression to avoid forbiden characters
            expression = self._convert_expression_to_index(expression)
            pt = pt.apply_expression(expression)
            # transform expression back
            pt.band_descriptions = [
                self._convert_expression_from_index(b) for b in pt.band_descriptions
            ]

        pt.band_names = [f"b{ix + 1}" for ix in range(pt.count)]
        pt.assets = [self.input]

        return pt

    def feature(  # type: ignore
        self,
        shape: Dict,
        shape_crs: CRS = WGS84_CRS,
        variables: List[str] | None = None,
        expression: str | None = None,
        sel: List[str] | None = None,
        max_size: int | None = 1024,
        height: int | None = None,
        width: int | None = None,
        dst_crs: CRS | None = None,
        **kwargs: Any,
    ) -> ImageData:
        """Read part of a dataset defined by a geojson feature."""

        dst_crs = dst_crs or shape_crs

        # Get BBOX of the polygon
        bbox = featureBounds(shape)

        bounds_in_dst_crs = (
            transform_bounds(shape_crs, dst_crs, *bbox, densify_pts=21)
            if dst_crs != shape_crs
            else bbox
        )

        img_stack: List[ImageData] = []

        if variables and expression:
            warnings.warn(
                "Both expression and assets passed; expression will overwrite assets parameter.",
                ExpressionMixingWarning,
                stacklevel=2,
            )

        if expression:
            variables = self.parse_expression(expression)

        if not variables:
            raise MissingVariables(
                "`variables` must be passed via `expression` or `variables` options."
            )

        for gv in variables:
            group, variable = gv.split(":") if ":" in gv else ("/", gv)
            with XarrayReader(
                self._get_variable(
                    group,
                    variable,
                    sel=sel,
                    max_size=max_size,
                    height=height,
                    width=width,
                    bounds=bounds_in_dst_crs,
                    dst_crs=dst_crs,
                ),
                tms=self.tms,
            ) as da:
                img = da.feature(
                    shape,
                    dst_crs=dst_crs,
                    shape_crs=shape_crs,
                    max_size=max_size,
                    height=height,
                    width=width,
                    **kwargs,
                )
                if expression:
                    if len(img.band_names) > 1:
                        raise ValueError("Can't use `expression` for multidim dataset")
                    # NOTE: create band_names in form of Var{ix} used later for expressions
                    img.band_names = [self._variable_idx[gv]]

                if len(img.band_names) > 1 or sel:
                    img.band_descriptions = [f"{gv}|{b}" for b in img.band_descriptions]
                else:
                    img.band_descriptions = [gv]

                img_stack.append(img)

        img = ImageData.create_from_list(img_stack)

        if expression:
            # NOTE: translate expression from {group:variable} to Var{ix}
            expression = self._convert_expression_to_index(expression)

            # NOTE: `apply_expression` method uses band_names (e.g b1) not band_descriptions
            img = img.apply_expression(expression)

            # NOTE: transform expression back
            img.band_descriptions = [
                self._convert_expression_from_index(b) for b in img.band_descriptions
            ]

        img.band_names = [f"b{ix + 1}" for ix in range(img.count)]
        img.assets = [self.input]

        return img


def calculate_output_transform(
    crs: CRS,
    bounds: BBox,
    height: int,
    width: int,
    out_crs: CRS,
    *,
    out_bounds: BBox | None = None,
    out_max_size: int | None = None,
    out_height: int | None = None,
    out_width: int | None = None,
) -> Affine:
    """Calculate Reprojected Dataset transform."""
    # 1. get the `whole` reprojected dataset transfrom, shape and bounds
    dst_transform, dst_width, dst_height = calculate_default_transform(
        crs,
        out_crs,
        width,
        height,
        *bounds,
    )

    # If no bounds we assume the full dataset bounds
    out_bounds = out_bounds or array_bounds(dst_height, dst_width, dst_transform)

    # output Bounds
    w, s, e, n = out_bounds

    # adjust dataset virtual output shape/transform
    dst_width = max(1, round((e - w) / dst_transform.a))
    dst_height = max(1, round((s - n) / dst_transform.e))

    # Output Transform in Output CRS
    dst_transform = from_bounds(w, s, e, n, dst_width, dst_height)

    # 2. adjust output size based on max_size if
    # - not input width/height
    # - max_size < dst_width and dst_height
    if out_max_size:
        out_height, out_width = _get_width_height(out_max_size, dst_height, dst_width)

    elif out_height or out_width:
        if not out_height or not out_width:
            # get the size's ratio of the reprojected dataset
            ratio = dst_height / dst_width
            if out_width:
                out_height = math.ceil(out_width * ratio)
            else:
                out_width = math.ceil(out_height / ratio)

    out_height = out_height or dst_height
    out_width = out_width or dst_width

    # Get the transform in the Dataset CRS
    transform, _, _ = calculate_default_transform(
        out_crs,
        crs,
        out_width,
        out_height,
        *out_bounds,
    )

    return transform
