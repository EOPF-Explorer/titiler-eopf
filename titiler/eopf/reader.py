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
from typing import Any, Callable, Dict, List, Literal, Union
from urllib.parse import urlparse

import attr
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
from rioxarray.exceptions import NoDataInBounds
from zarr.storage import ObjectStore

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
    ms_resolutions = [
        (mt["id"], mt["cellSize"])
        for mt in dt.attrs["multiscales"]["tile_matrix_set"]["tileMatrices"]
        if variable in dt[mt["id"]].data_vars
    ]
    if len(ms_resolutions) == 1:
        return ms_resolutions[0][0]

    # Based on aiocogeo:
    # https://github.com/geospatial-jeff/aiocogeo/blob/5a1d32c3f22c883354804168a87abb0a2ea1c328/aiocogeo/partial_reads.py#L113-L147
    percentage = {"AUTO": 50, "LOWER": 100, "UPPER": 0}.get(zoom_level_strategy, 50)

    # Iterate over zoom levels from lowest/coarsest to highest/finest. If the `target_res` is more than `percentage`
    # percent of the way from the zoom level below to the zoom level above, then upsample the zoom level below, else
    # downsample the zoom level above.
    available_resolutions = sorted(ms_resolutions, key=lambda x: x[1], reverse=True)

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
    crs = da.rio.crs or "epsg:4326"
    da = da.rio.write_crs(crs)

    if crs == "epsg:4326" and (da.x > 180).any():
        # Adjust the longitude coordinates to the -180 to 180 range
        da = da.assign_coords(x=(da.x + 180) % 360 - 180)

        # Sort the dataset by the updated longitude coordinates
        da = da.sortby(da.x)

    return da


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

    def __attrs_post_init__(self):
        """Set bounds and CRS."""
        if not self.datatree:
            self.datatree = self.opener(self.input, **self.opener_options)

        self.groups = self._get_groups()
        self.variables = self._get_variables()

        # There might not be global bounds/CRS for a Zarr Store
        try:
            ds = self.datatree.to_dataset()
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

    def _get_groups(self) -> List[str]:
        """return groups within the datatree."""
        groups: List[str] = []
        ms_groups: List[str] = []

        for g in self.datatree.groups:
            if "multiscales" in self.datatree[g].attrs:
                ms_groups.append(g)

                # Validate Group using First Level of MultiScale
                scale = self.datatree[g].attrs["multiscales"]["tile_matrix_set"][
                    "tileMatrices"
                ][0]["id"]
                ds = self.datatree[g][scale].to_dataset()
                if _validate_zarr(ds):
                    groups.append(g)

            else:
                # We skip if group is within a multiscale
                if any(g.startswith(msg) for msg in ms_groups):
                    continue

                elif self.datatree[g].data_vars:
                    ds = self.datatree[g].to_dataset()
                    if _validate_zarr(ds):
                        groups.append(g)

        return groups

    def _get_variables(self) -> List[str]:
        """Return available variables for a group."""
        variables: List[str] = []

        for g in self.groups:
            # Select a group
            group = self.datatree[g]

            # If a Group is a Multiscale group then we collect variables from all scales
            if "multiscales" in group.attrs:
                # Get all variables across all multiscale levels
                all_vars = set()
                for matrix in group.attrs["multiscales"]["tile_matrix_set"][
                    "tileMatrices"
                ]:
                    scale = matrix["id"]
                    if scale in group:
                        scale_group = group[scale]
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
                    for var, data_array in group.data_vars.items()
                    if data_array.ndim > 0
                ]
                variables.extend(f"{g}:{v}" for v in multidim_vars)

        return variables

    def get_bounds(self, group: str, crs: CRS = WGS84_CRS) -> BBox:
        """Get BBox for a Group."""
        if "multiscales" in self.datatree[group].attrs:
            scale = self.datatree[group].attrs["multiscales"]["tile_matrix_set"][
                "tileMatrices"
            ][0]["id"]
            ds = self.datatree[group][scale].to_dataset()
        else:
            ds = self.datatree[group].to_dataset()

        return transform_bounds(ds.rio.crs, crs, *ds.rio.bounds(), densify_pts=21)

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
    def get_minzoom(self, group: str) -> int:
        """Get MinZoom for a Group."""
        if "multiscales" in self.datatree[group].attrs:
            # Select the last level (should be the lowest/coarsest resolution)
            scale = self.datatree[group].attrs["multiscales"]["tile_matrix_set"][
                "tileMatrices"
            ][-1]["id"]
            ds = self.datatree[group][scale].to_dataset()
        else:
            ds = self.datatree[group].to_dataset()

        try:
            return self._get_zoom(ds)
        except:  # noqa
            print("error", ds)
            pass

        return self.tms.minzoom

    # TODO: add cache
    def get_maxzoom(self, group: str) -> int:
        """Get MaxZoom for a Group."""
        if "multiscales" in self.datatree[group].attrs:
            # Select the first level (should be the highest/finest resolution)
            scale = self.datatree[group].attrs["multiscales"]["tile_matrix_set"][
                "tileMatrices"
            ][0]["id"]
            ds = self.datatree[group][scale].to_dataset()
        else:
            ds = self.datatree[group].to_dataset()

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
        method: sel_methods | None = None,
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

        dt = self.datatree[group]
        if "multiscales" in dt.attrs:
            ms_crs = CRS.from_user_input(
                dt.attrs["multiscales"]["tile_matrix_set"]["crs"]
            )

            # NOTE: Default Scale (where variable is present)
            # This assume, the tile_matrix_set are ordered from higher resolution To lower resolution
            try:
                scale = next(
                    (
                        mt["id"]
                        for mt in dt.attrs["multiscales"]["tile_matrix_set"][
                            "tileMatrices"
                        ]
                        if variable in dt[mt["id"]].data_vars
                    )
                )
            except StopIteration as e:
                raise MissingVariables(
                    f"Variable '{variable}' not found in any multiscale level of group '{group}'"
                ) from e

            if any([bounds, height, width, max_size]):
                default_dataset = self.datatree[group][scale].to_dataset()

                # Get Target expected resolution in Dataset CRS
                # 1. Reprojection
                if dst_crs and dst_crs != ms_crs:
                    dst_transform = calculate_output_transform(
                        ms_crs,
                        default_dataset.rio.bounds(),
                        default_dataset.rio.height,
                        default_dataset.rio.width,
                        dst_crs,
                        # bounds is supposed to be in dst_crs
                        out_bounds=bounds,
                        out_max_size=max_size,
                        out_height=height,
                        out_width=width,
                    )
                    target_res = dst_transform.a

                # 2. No Reprojection
                else:
                    # If no bounds we assume the full dataset bounds
                    bounds = bounds or default_dataset.rio.bounds()

                    window = windows.from_bounds(
                        *bounds, transform=default_dataset.rio.transform()
                    )
                    if max_size:
                        height, width = _get_width_height(
                            max_size, round(window.height), round(window.width)
                        )

                    elif _missing_size(width, height):
                        ratio = window.height / window.width
                        if width:
                            height = math.ceil(width * ratio)
                        else:
                            width = math.ceil(height / ratio)

                    height = height or max(1, round(window.height))
                    width = width or max(1, round(window.width))

                    target_res = from_bounds(*bounds, height=height, width=width).a

                scale = get_multiscale_level(dt, variable, target_res)  # type: ignore

            # Select the multiscale group and variable
            da = dt[scale][variable]

            logger.info(
                f"Multiscale - selecting group {group} with scale {scale} and variable {variable}"
            )

            # NOTE: Make sure the multiscale levels have the same CRS
            # ref: https://github.com/EOPF-Explorer/data-model/issues/12
            da = da.rio.write_crs(ms_crs)

        else:
            # Select Variable (xarray.DataArray)
            da = dt[variable]

        if sel:
            _idx: Dict[str, List] = {}
            for s in sel:
                val: Union[str, slice]
                dim, val = s.split("=")

                # cast string to dtype of the dimension
                if da[dim].dtype != "O":
                    val = da[dim].dtype.type(val)

                if dim in _idx:
                    _idx[dim].append(val)
                else:
                    _idx[dim] = [val]

            sel_idx = {k: v[0] if len(v) < 2 else v for k, v in _idx.items()}
            da = da.sel(sel_idx, method=method)

        da = _arrange_dims(da)

        assert len(da.dims) in [
            2,
            3,
        ], "rio_tiler.io.xarray.DatasetReader can only work with 2D or 3D DataArray"

        return da

    @cached_property
    def _variable_idx(self) -> Dict[str, str]:
        return {v: f"Var{ix}" for ix, v in enumerate(self.variables)}

    def parse_expression(self, expression: str) -> List[str]:
        """Parse rio-tiler band math expression."""
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
        method: sel_methods | None = None,
    ) -> Dict[str, Info]:
        """Return xarray.DataArray info.

        Variables that fail to load will be skipped and logged as warnings.
        """
        variables = variables or self.variables

        def _get_info_safe(group_var: str) -> Info | None:
            """Get info for a single variable, with error handling."""
            try:
                group, variable = (
                    group_var.split(":") if ":" in group_var else ("/", group_var)
                )
                with XarrayReader(
                    self._get_variable(group, variable, sel=sel, method=method),
                ) as da:
                    info = da.info()
                    # Fix band descriptions to use actual variable name
                    variable_name = group_var.split(":")[-1] if ":" in group_var else group_var
                    if info.band_descriptions:
                        # Replace the band description with the actual variable name
                        info.band_descriptions = [
                            (band_idx, variable_name) for band_idx, _ in info.band_descriptions
                        ]
                    return info
            except Exception as e:
                logger.info(f"Failed to get info for variable '{group_var}': {e!s}")
                return None

        # Build result dictionary, skipping variables that failed
        result = {}
        for gv in variables:
            info_data = _get_info_safe(gv)
            if info_data is not None:
                result[gv] = info_data
        return result

    def statistics(  # type: ignore
        self,
        *args: Any,
        variables: List[str] | None = None,
        expression: str | None = None,
        sel: List[str] | None = None,
        method: sel_methods | None = None,
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
        method: sel_methods | None = None,
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
            try:
                with XarrayReader(
                    self._get_variable(
                        group,
                        variable,
                        sel=sel,
                        method=method,
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
                        img.band_names = [self._variable_idx[gv]]
                    else:
                        # Extract variable name from group:variable format
                        variable_name = gv.split(":")[-1] if ":" in gv else gv
                        img.band_names = [variable_name]

                    img_stack.append(img)
            except NoDataInBounds as e:
                logger.warning(f"No data found for variable '{gv}' in tile bounds: {str(e)}. Skipping this variable.")
                # Continue processing other variables instead of failing completely
                continue

        if not img_stack:
            raise NoDataInBounds("No data found in bounds for any of the requested variables.")

        img = ImageData.create_from_list(img_stack)

        if expression:
            # edit expression to avoid forbiden characters
            expression = self._convert_expression_to_index(expression)
            img = img.apply_expression(expression)
            # transform expression back
            img.band_names = [
                self._convert_expression_from_index(b) for b in img.band_names
            ]

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
        method: sel_methods | None = None,
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
            try:
                with XarrayReader(
                    self._get_variable(
                        group,
                        variable,
                        sel=sel,
                        method=method,
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
                        img.band_names = [self._variable_idx[gv]]
                    else:
                        # Extract variable name from group:variable format
                        variable_name = gv.split(":")[-1] if ":" in gv else gv
                        img.band_names = [variable_name]

                    img_stack.append(img)
            except NoDataInBounds as e:
                logger.warning(f"No data found for variable '{gv}' in bounds: {str(e)}. Skipping this variable.")
                # Continue processing other variables instead of failing completely
                continue

        if not img_stack:
            raise NoDataInBounds("No data found in bounds for any of the requested variables.")

        img = ImageData.create_from_list(img_stack)

        if expression:
            # edit expression to avoid forbiden characters
            expression = self._convert_expression_to_index(expression)
            img = img.apply_expression(expression)
            # transform expression back
            img.band_names = [
                self._convert_expression_from_index(b) for b in img.band_names
            ]

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
        method: sel_methods | None = None,
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
            try:
                with XarrayReader(
                    self._get_variable(
                        group,
                        variable,
                        sel=sel,
                        method=method,
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
                        img.band_names = [self._variable_idx[gv]]
                    else:
                        # Extract variable name from group:variable format
                        variable_name = gv.split(":")[-1] if ":" in gv else gv
                        img.band_names = [variable_name]

                    img_stack.append(img)
            except NoDataInBounds as e:
                logger.warning(f"No data found for variable '{gv}' in preview bounds: {str(e)}. Skipping this variable.")
                # Continue processing other variables instead of failing completely
                continue

        if not img_stack:
            raise NoDataInBounds("No data found in bounds for any of the requested variables.")

        img = ImageData.create_from_list(img_stack)

        if expression:
            # edit expression to avoid forbiden characters
            expression = self._convert_expression_to_index(expression)
            img = img.apply_expression(expression)
            # transform expression back
            img.band_names = [
                self._convert_expression_from_index(b) for b in img.band_names
            ]

        img.assets = [self.input]

        return img

    def point(  # type: ignore
        self,
        *args: Any,
        variables: List[str] | None = None,
        expression: str | None = None,
        sel: List[str] | None = None,
        method: sel_methods | None = None,
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
                self._get_variable(group, variable, sel=sel, method=method),
                tms=self.tms,
            ) as da:
                pt = da.point(*args, **kwargs)
                if expression:
                    if len(pt.band_names) > 1:
                        raise ValueError("Can't use `expression` for multidim dataset")
                    pt.band_names = [self._variable_idx[gv]]
                else:
                    # Extract variable name from group:variable format
                    variable_name = gv.split(":")[-1] if ":" in gv else gv
                    pt.band_names = [variable_name]

                pts_stack.append(pt)

        pt = PointData.create_from_list(pts_stack)
        if expression:
            # edit expression to avoid forbiden characters
            expression = self._convert_expression_to_index(expression)
            pt = pt.apply_expression(expression)
            # transform expression back
            pt.band_names = [
                self._convert_expression_from_index(b) for b in pt.band_names
            ]

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
        method: sel_methods | None = None,
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
                    method=method,
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
                    img.band_names = [self._variable_idx[gv]]
                else:
                    # Extract variable name from group:variable format
                    variable_name = gv.split(":")[-1] if ":" in gv else gv
                    img.band_names = [variable_name]

                img_stack.append(img)

        img = ImageData.create_from_list(img_stack)

        if expression:
            # edit expression to avoid forbiden characters
            expression = self._convert_expression_to_index(expression)
            img = img.apply_expression(expression)
            # transform expression back
            img.band_names = [
                self._convert_expression_from_index(b) for b in img.band_names
            ]

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
