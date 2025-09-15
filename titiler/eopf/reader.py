"""titiler.eopf.reader."""

from __future__ import annotations

import contextlib
import re
import warnings
from functools import cache, cached_property
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Union
from urllib.parse import urlparse

import attr
import obstore
import xarray
from morecantile import Tile, TileMatrixSet
from rasterio.crs import CRS
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
from rio_tiler.types import BBox
from zarr.storage import ObjectStore

sel_methods = Literal["nearest", "pad", "ffill", "backfill", "bfill"]


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

    store = obstore.store.from_url(src_path)
    zarr_store = ObjectStore(store=store, read_only=True)
    ds = xarray.open_datatree(
        zarr_store,
        decode_times=True,
        decode_coords="all",
        consolidated=True,
        engine="zarr",
    )

    return ds


def get_multiscale_level(
    dt: xarray.DataTree,
    target_res: float,
    zoom_level_strategy: Literal["AUTO", "LOWER", "UPPER"] = "AUTO",
) -> str:
    """Return the multiscale level corresponding to the desired resolution."""
    ms_resolutions = [
        (mt["id"], mt["cellSize"])
        for mt in dt.attrs["multiscales"]["tile_matrix_set"]["tileMatrices"]
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


def get_multiscale_level_with_gcp(
    dt: xarray.DataTree,
    target_res: float,
    zoom_level_strategy: Literal["AUTO", "LOWER", "UPPER"] = "AUTO",
) -> str:
    """Return the multiscale level corresponding to the desired resolution, considering GCPs."""
    ms_resolutions = [
        (mt["id"], mt["cellSize"])
        for mt in dt.attrs["multiscales"]["tile_matrix_set"]["tileMatrices"]
    ]
    if len(ms_resolutions) == 1:
        return ms_resolutions[0][0]

    percentage = {"AUTO": 50, "LOWER": 100, "UPPER": 0}.get(zoom_level_strategy, 50)

    available_resolutions = sorted(ms_resolutions, key=lambda x: x[1], reverse=True)

    for i in range(0, len(available_resolutions) - 1):
        _, res_current = available_resolutions[i]
        _, res_higher = available_resolutions[i + 1]
        threshold = res_higher - (res_higher - res_current) * (percentage / 100.0)
        if target_res > threshold or target_res == res_current:
            return available_resolutions[i][0]

    return ms_resolutions[0][0]


def _validate_zarr(ds: xarray.Dataset) -> bool:
    if "x" not in ds.dims and "y" not in ds.dims:
        try:
            _ = next(
                name
                for name in [
                    "lat",
                    "latitude",
                    "LAT",
                    "LATITUDE",
                    "Lat",
                    "azimuth_time",
                ]
                if name in ds.dims
            )
            _ = next(
                name
                for name in [
                    "lon",
                    "longitude",
                    "LON",
                    "LONGITUDE",
                    "Lon",
                    "ground_range",
                ]
                if name in ds.dims
            )
        except StopIteration:
            return False

    # NOTE: ref: https://github.com/EOPF-Explorer/data-model/issues/12
    if not ds.rio.crs:
        return False

    return True


def _arrange_dims(da: xarray.DataArray, gcps: Any = None) -> xarray.DataArray:
    """Arrange coordinates and time dimensions.

    An rioxarray.exceptions.InvalidDimensionOrder error is raised if the coordinates are not in the correct order time, y, and x.
    See: https://github.com/corteva/rioxarray/discussions/674

    We conform to using x and y as the spatial dimension names..

    """
    transpose = False

    if gcps:
        da = da.rio.write_crs(da.rio.crs or "epsg:4326")
        da = da.rio.set_spatial_dims(
            x_dim="ground_range", y_dim="azimuth_time", inplace=False
        )
        gcps_interp = gcps.interp_like(da)
        da.assign_coords({"y": gcps_interp.latitude, "x": gcps_interp.longitude})

    elif "x" not in da.dims and "y" not in da.dims:
        try:
            latitude_var_name = next(
                name
                for name in [
                    "lat",
                    "latitude",
                    "LAT",
                    "LATITUDE",
                    "Lat",
                    "azimuth_time",
                ]
                if name in da.dims
            )
            longitude_var_name = next(
                name
                for name in [
                    "lon",
                    "longitude",
                    "LON",
                    "LONGITUDE",
                    "Lon",
                    "ground_range",
                ]
                if name in da.dims
            )
        except StopIteration as e:
            raise ValueError(f"Couldn't find X/Y dimensions in {da.name}") from e

        transpose = True

        da = da.rename({latitude_var_name: "y", longitude_var_name: "x"})

    if "TIME" in da.dims:
        da = da.rename({"TIME": "time"})

    if transpose:
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

    if transpose and crs == "epsg:4326" and (da.x > 180).any():
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

    _ctx_stack: contextlib.ExitStack = attr.ib(init=False, factory=contextlib.ExitStack)

    groups: List[str] = attr.ib(init=False)
    variables: List[str] = attr.ib(init=False)

    def __attrs_post_init__(self):
        """Set bounds and CRS."""
        if not self.datatree:
            self.datatree = self._ctx_stack.enter_context(
                self.opener(self.input, **self.opener_options)
            )

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

    def close(self):
        """Close xarray dataset."""
        self._ctx_stack.close()

    def __exit__(self, exc_type, exc_value, traceback):
        """Support using with Context Managers."""
        self.close()

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

            # If a Group is a Multiscale group then we select the first scale
            if "multiscales" in group.attrs:
                # Get id for the first multiscale group
                scale = group.attrs["multiscales"]["tile_matrix_set"]["tileMatrices"][
                    0
                ]["id"]
                group = group[scale]

            variables.extend(f"{g}:{v}" for v in list(group.data_vars))

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

        if "azimuth_time" in ds.dims and "ground_range" in ds.dims:
            ds.rio.set_spatial_dims(
                x_dim="ground_range", y_dim="azimuth_time", inplace=True
            )

        if ds.rio.get_gcps():
            transform, width, height = calculate_default_transform(
                ds.rio.crs,
                crs,
                ds.rio.width,
                ds.rio.height,
                gcps=ds.rio.get_gcps(),
            )
            bounds = (
                transform[2],
                transform[5] + height * transform[4],
                transform[2] + width * transform[0],
                transform[5],
            )
            return bounds

        return transform_bounds(ds.rio.crs, crs, *ds.rio.bounds(), densify_pts=21)

    def _get_zoom(self, ds: xarray.Dataset) -> int:
        """Get MaxZoom for a Group."""
        crs = ds.rio.crs
        tms_crs = self.tms.rasterio_crs
        if crs != tms_crs:
            if ds.rio.get_gcps():
                transform, _, _ = calculate_default_transform(
                    crs,
                    tms_crs,
                    ds.rio.width,
                    ds.rio.height,
                    gcps=ds.rio.get_gcps(),
                )
            else:
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

        if "azimuth_time" in ds.dims and "ground_range" in ds.dims:
            ds.rio.set_spatial_dims(
                x_dim="ground_range", y_dim="azimuth_time", inplace=True
            )

        try:
            return self._get_zoom(ds)
        except Exception as e:  # noqa
            print("error", ds)
            print("error details:", e)
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

        if "azimuth_time" in ds.dims and "ground_range" in ds.dims:
            ds.rio.set_spatial_dims(
                x_dim="ground_range", y_dim="azimuth_time", inplace=True
            )

        try:
            return self._get_zoom(ds)
        except Exception as e:  # noqa
            print("error", ds)
            print("error details:", e)
            pass

        return self.tms.maxzoom

    def _get_variable(
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
        if max_size and width and height:
            warnings.warn(
                "'max_size' will be ignored with with 'height' and 'width' set.",
                UserWarning,
                stacklevel=2,
            )

        gcps = None

        ds = self.datatree[group]
        if "multiscales" in ds.attrs:
            # Default to first scale
            scale = ds.attrs["multiscales"]["tile_matrix_set"]["tileMatrices"][0]["id"]
            ms_crs = CRS.from_user_input(
                ds.attrs["multiscales"]["tile_matrix_set"]["crs"]
            )

            # TODO: handle Max-Size and single width/height
            # TODO: handle when no reprojection
            # if max_size:
            #     height, width = _get_width_height(max_size, max_height, max_width)
            # elif _missing_size(width, height):
            #     ratio = max_height / max_width
            #     if width:
            #         height = math.ceil(width * ratio)
            #     else:
            #         width = math.ceil(height / ratio)

            dss = ds[scale].to_dataset()  # we use the first scale to check for GCPs
            if dss.rio.get_gcps():
                if "azimuth_time" in dss.dims and "ground_range" in dss.dims:
                    dss.rio.set_spatial_dims(
                        x_dim="ground_range", y_dim="azimuth_time", inplace=True
                    )
                ms_crs = dss.rio.crs or ms_crs
                transform, _, _ = calculate_default_transform(
                    ms_crs,
                    dst_crs or ms_crs,
                    dss.rio.width,
                    dss.rio.height,
                    gcps=dss.rio.get_gcps(),
                )
                target_res = max(abs(transform[0]), abs(transform[4]))

                scale = get_multiscale_level(ds, target_res)  # type: ignore

            elif all([bounds, height, width, dst_crs]):
                # Get the output resolution in the datatree CRS
                dst_transform, _, _ = calculate_default_transform(
                    dst_crs, ms_crs, width, height, *bounds
                )
                target_res = dst_transform.a

                scale = get_multiscale_level(ds, target_res)  # type: ignore

            # Select the multiscale group and variable
            da = ds[scale][variable]
            gcps = self.datatree[group.split("/")[1] + "/conditions/gcp"].to_dataset()

            # NOTE: Make sure the multiscale levels have the same CRS
            # ref: https://github.com/EOPF-Explorer/data-model/issues/12
            da = da.rio.write_crs(ms_crs)

        else:
            # Select Variable (xarray.DataArray)
            da = ds[variable]

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

        da = _arrange_dims(da, gcps=gcps)

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
        """Return xarray.DataArray info."""
        variables = variables or self.variables

        def _get_info(group_var: str):
            group, variable = (
                group_var.split(":") if ":" in group_var else ("/", group_var)
            )
            with XarrayReader(
                self._get_variable(group, variable, sel=sel, method=method),
            ) as da:
                return da.info()

        return {gv: _get_info(gv) for gv in variables}

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

    def part(  # type: ignore
        self,
        *args: Any,
        variables: List[str] | None = None,
        expression: str | None = None,
        sel: List[str] | None = None,
        method: sel_methods | None = None,
        **kwargs: Any,
    ) -> ImageData:
        """Read part of a dataset."""
        raise NotImplementedError

    def preview(  # type: ignore
        self,
        *args: Any,
        variables: List[str] | None = None,
        expression: str | None = None,
        max_size: int = 1024,
        sel: List[str] | None = None,
        method: sel_methods | None = None,
        **kwargs: Any,
    ) -> ImageData:
        """Return a preview of a dataset."""
        raise NotImplementedError

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
        *args: Any,
        variables: List[str] | None = None,
        expression: str | None = None,
        sel: List[str] | None = None,
        method: sel_methods | None = None,
        **kwargs: Any,
    ) -> ImageData:
        """Read part of a dataset defined by a geojson feature."""
        raise NotImplementedError
