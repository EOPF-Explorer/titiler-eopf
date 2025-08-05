"""TiTiler.eopf factory."""

import logging
from typing import Any, Callable, Type

import rasterio
from attrs import define, field
from fastapi import Depends
from geojson_pydantic.features import Feature
from rasterio.warp import transform_bounds
from rio_tiler.constants import WGS84_CRS

from titiler.core.dependencies import CRSParams, DefaultDependency
from titiler.core.factory import TilerFactory as BaseTilerFactory
from titiler.core.models.responses import MultiBaseInfo, MultiBaseInfoGeoJSON
from titiler.core.resources.responses import GeoJSONResponse, JSONResponse
from titiler.core.utils import bounds_to_geometry
from titiler.xarray.dependencies import DatasetParams

from .dependencies import DatasetPathParams, LayerParams, VariablesParams
from .reader import GeoZarrReader

logger = logging.getLogger(__name__)


@define(kw_only=True)
class TilerFactory(BaseTilerFactory):
    """Xarray Tiler Factory."""

    reader: Type[GeoZarrReader] = GeoZarrReader

    path_dependency: Callable[..., Any] = DatasetPathParams

    reader_dependency: Type[DefaultDependency] = DefaultDependency

    # variable/sel/method options
    # Used in info/statistics
    variables_dependency: Type[DefaultDependency] = VariablesParams

    # Indexes Dependencies
    layer_dependency: Type[DefaultDependency] = LayerParams

    # Dataset Options (nodata, reproject)
    dataset_dependency: Type[DefaultDependency] = DatasetParams

    # Tile/Tilejson/WMTS Dependencies  (Not used in titiler.xarray)
    tile_dependency: Type[DefaultDependency] = DefaultDependency

    add_viewer: bool = True

    # endpoints disabled by default
    add_ogc_maps: bool = field(init=False, default=False)
    add_preview: bool = field(init=False, default=False)
    add_part: bool = field(init=False, default=False)

    def register_routes(self):
        """This Method register routes to the router."""
        self.info()

        self.tilesets()
        self.tile()
        if self.add_viewer:
            self.map_viewer()

        self.wmts()
        self.tilejson()

    # Custom /info endpoints
    def info(self):
        """Register /info endpoint."""

        @self.router.get(
            "/info",
            response_model=MultiBaseInfo,
            response_model_exclude_none=True,
            response_class=JSONResponse,
            responses={200: {"description": "Return dataset's basic info."}},
            operation_id=f"{self.operation_prefix}getInfo",
        )
        def info_endpoint(
            src_path=Depends(self.path_dependency),
            reader_params=Depends(self.reader_dependency),
            variables_params=Depends(self.variables_dependency),
            env=Depends(self.environment_dependency),
        ):
            """Return dataset's basic info."""
            with rasterio.Env(**env):
                logger.info(f"opening data with reader: {self.reader}")
                with self.reader(src_path, **reader_params.as_dict()) as src_dst:
                    return src_dst.info(**variables_params.as_dict())

        @self.router.get(
            "/info.geojson",
            response_model=MultiBaseInfoGeoJSON,
            response_model_exclude_none=True,
            response_class=GeoJSONResponse,
            responses={
                200: {
                    "content": {"application/geo+json": {}},
                    "description": "Return dataset's basic info as a GeoJSON feature.",
                }
            },
            operation_id=f"{self.operation_prefix}getInfoGeoJSON",
        )
        def info_geojson(
            src_path=Depends(self.path_dependency),
            reader_params=Depends(self.reader_dependency),
            variables_params=Depends(self.variables_dependency),
            crs=Depends(CRSParams),
            env=Depends(self.environment_dependency),
        ):
            """Return dataset's basic info as a GeoJSON feature."""
            with rasterio.Env(**env):
                logger.info(f"opening data with reader: {self.reader}")
                with self.reader(src_path, **reader_params.as_dict()) as src_dst:
                    info = src_dst.info(**variables_params.as_dict())

                    minx, miny, maxx, maxy = zip(
                        *[
                            transform_bounds(
                                info.crs,
                                crs or WGS84_CRS,
                                *info.bounds,
                                densify_pts=21,
                            )
                            for _, info in info.items()
                        ]
                    )
                    bounds = (min(minx), min(miny), max(maxx), max(maxy))
                    geometry = bounds_to_geometry(bounds)

                    return Feature(
                        type="Feature",
                        bbox=bounds,
                        geometry=geometry,
                        properties=info,
                    )

    # TODO:
    # overwrite tilejson and tileset endpoints
