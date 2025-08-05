"""titiler.eopf.reader."""

from __future__ import annotations

import contextlib
import warnings
from functools import cache, cached_property
from typing import Any, Callable, Dict, List, Literal, Union

import attr
import obstore
import xarray
from morecantile import Tile, TileMatrixSet
from rasterio.crs import CRS
from rasterio.warp import calculate_default_transform
from rio_tiler.constants import WEB_MERCATOR_TMS, WGS84_CRS
from rio_tiler.errors import InvalidGeographicBounds
from rio_tiler.io.base import BaseReader
from rio_tiler.io.xarray import XarrayReader
from rio_tiler.models import BandStatistics, ImageData, Info, PointData
from rio_tiler.types import BBox
from zarr.storage import ObjectStore

sel_methods = Literal["nearest", "pad", "ffill", "backfill", "bfill"]


@cache
def open_dataset(src_path: str, **kwargs: Any) -> xarray.DataTree:
    """Open Xarray dataset

    Args:
        src_path (str): dataset path.

    Returns:
        xarray.DataTree

    """
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


def _validate_zarr(da: xarray.DataArray) -> bool:
    if "x" not in da.dims and "y" not in da.dims:
        try:
            _ = next(
                name
                for name in ["lat", "latitude", "LAT", "LATITUDE", "Lat"]
                if name in da.dims
            )
            _ = next(
                name
                for name in ["lon", "longitude", "LON", "LONGITUDE", "Lon"]
                if name in da.dims
            )
        except StopIteration:
            warnings.warn(
                f"Could not find valid coordinates dimension for `{da.name}`",
                UserWarning,
                stacklevel=3,
            )
            return False

    # NOTE: ref: https://github.com/EOPF-Explorer/data-model/issues/12
    if not da.rio.crs:
        warnings.warn(
            f"Could not find valid coordinates reference system (CRS) for `{da.name}`",
            UserWarning,
            stacklevel=3,
        )
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

    _ctx_stack: contextlib.ExitStack = attr.ib(init=False, factory=contextlib.ExitStack)

    def __attrs_post_init__(self):
        """Set bounds and CRS."""
        if not self.datatree:
            self.datatree = self._ctx_stack.enter_context(
                self.opener(self.input, **self.opener_options)
            )

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

            self.minzoom = self.minzoom if self.minzoom is not None else self._minzoom
            self.maxzoom = self.maxzoom if self.maxzoom is not None else self._maxzoom

        except:  # noqa
            self.bounds = (-180, -90, 180, 90)
            self.crs = WGS84_CRS
            self.minzoom = self.tms.minzoom
            self.maxzoom = self.tms.maxzoom

    def close(self):
        """Close xarray dataset."""
        self._ctx_stack.close()

    def __exit__(self, exc_type, exc_value, traceback):
        """Support using with Context Managers."""
        self.close()

    @cached_property
    def groups(self) -> List[str]:
        """return groups within the datatree."""
        groups: List[str] = []
        ms_groups: List[str] = []

        for g in self.datatree.groups:
            if "multiscales" in self.datatree[g].attrs:
                ms_groups.append(g)
                groups.append(g)
            else:
                # We skip if group is within a multiscale
                if any(g.startswith(msg) for msg in ms_groups):
                    continue

                elif self.datatree[g].data_vars:
                    groups.append(g)

        return groups

    @cached_property
    def variables(self) -> List[str]:
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

            variables.extend(
                f"{g}:{v}" for v in list(group.data_vars) if _validate_zarr(group[v])
            )

        return variables

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

            if all([bounds, height, width, dst_crs]):
                # Get the output resolution in the datatree CRS
                dst_transform, _, _ = calculate_default_transform(
                    dst_crs, ms_crs, width, height, *bounds
                )
                target_res = dst_transform.a

                scale = get_multiscale_level(ds, target_res)  # type: ignore

            # Select the multiscale group and variable
            da = ds[scale][variable]

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

        da = _arrange_dims(da)

        assert len(da.dims) in [
            2,
            3,
        ], "rio_tiler.io.xarray.DatasetReader can only work with 2D or 3D DataArray"

        return da

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
        variables: List[str],
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
        variables: List[str],
        tilesize: int = 256,
        sel: List[str] | None = None,
        method: sel_methods | None = None,
        **kwargs: Any,
    ) -> ImageData:
        """Read a Web Map tile from a dataset."""
        tile_bounds = tuple(self.tms.xy_bounds(Tile(x=tile_x, y=tile_y, z=tile_z)))
        dst_crs = self.tms.rasterio_crs

        img_stack: List[ImageData] = []

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
                img_stack.append(
                    da.tile(
                        tile_x,
                        tile_y,
                        tile_z,
                        *args,
                        tilesize=tilesize,
                        **kwargs,
                    )
                )

        return ImageData.create_from_list(img_stack)

    def part(  # type: ignore
        self,
        *args: Any,
        variables: List[str],
        sel: List[str] | None = None,
        method: sel_methods | None = None,
        **kwargs: Any,
    ) -> ImageData:
        """Read part of a dataset."""
        raise NotImplementedError

    def preview(  # type: ignore
        self,
        *args: Any,
        variables: List[str],
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
        variables: List[str],
        sel: List[str] | None = None,
        method: sel_methods | None = None,
        **kwargs: Any,
    ) -> PointData:
        """Read a pixel value from a dataset."""
        raise NotImplementedError

    def feature(  # type: ignore
        self,
        *args: Any,
        variables: List[str],
        sel: List[str] | None = None,
        method: sel_methods | None = None,
        **kwargs: Any,
    ) -> ImageData:
        """Read part of a dataset defined by a geojson feature."""
        raise NotImplementedError
