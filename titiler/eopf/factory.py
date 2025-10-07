"""TiTiler.eopf factory."""

import logging
from typing import Annotated, Any, Callable, Literal, Optional, Type
from urllib.parse import urlencode

import rasterio
from attrs import define, field
from fastapi import Depends, Path, Query
from geojson_pydantic.features import Feature
from morecantile.models import crs_axis_inverted
from rio_tiler.constants import WGS84_CRS
from rio_tiler.utils import CRS_to_uri, CRS_to_urn
from starlette.requests import Request
from starlette.routing import NoMatchFound

from titiler.core.dependencies import CRSParams, DefaultDependency
from titiler.core.factory import TilerFactory as BaseTilerFactory
from titiler.core.models.mapbox import TileJSON
from titiler.core.models.OGC import TileSet, TileSetList
from titiler.core.models.responses import MultiBaseInfo, MultiBaseInfoGeoJSON
from titiler.core.resources.enums import ImageType
from titiler.core.resources.responses import GeoJSONResponse, JSONResponse, XMLResponse
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
    # Used in info/statistics endpoints
    variables_dependency: Type[DefaultDependency] = VariablesParams

    # Variables/Expression/Indexes Options
    # User in /tiles/... endpoints
    layer_dependency: Type[DefaultDependency] = LayerParams

    # Dataset Options (nodata, reproject)
    dataset_dependency: Type[DefaultDependency] = DatasetParams

    # Tile/Tilejson/WMTS Dependencies  (Not used in titiler.xarray)
    tile_dependency: Type[DefaultDependency] = DefaultDependency

    add_ogc_maps: bool = field(default=True)
    add_part: bool = field(default=True)
    add_preview: bool = field(default=True)

    def register_routes(self):
        """This Method register routes to the router."""
        self.bounds()
        self.info()
        # self.statistics()

        self.tilesets()
        self.tile()
        if self.add_viewer:
            self.map_viewer()

        self.wmts()
        self.tilejson()

        self.point()

        # Optional Routes
        if self.add_preview:
            self.preview()

        if self.add_part:
            self.part()

        if self.add_ogc_maps:
            self.ogc_maps()

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
                    variables = variables_params.variables or src_dst.variables
                    return src_dst.info(variables=variables)

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
                    variables = variables_params.variables or src_dst.variables
                    groups = {
                        group_var.split(":")[0] if ":" in group_var else "/"
                        for group_var in variables
                    }
                    minx, miny, maxx, maxy = zip(
                        *[
                            src_dst.get_bounds(group, crs or WGS84_CRS)
                            for group in groups
                        ]
                    )
                    bounds = (min(minx), min(miny), max(maxx), max(maxy))
                    geometry = bounds_to_geometry(bounds)

                    return Feature(
                        type="Feature",
                        bbox=bounds,
                        geometry=geometry,
                        properties=src_dst.info(variables=variables),
                    )

    ############################################################################
    # /tileset
    ############################################################################
    def tilesets(self):
        """Register OGC tilesets endpoints."""

        @self.router.get(
            "/tiles",
            response_model=TileSetList,
            response_class=JSONResponse,
            response_model_exclude_none=True,
            responses={
                200: {
                    "content": {
                        "application/json": {},
                    }
                }
            },
            summary="Retrieve a list of available raster tilesets for the specified dataset.",
            operation_id=f"{self.operation_prefix}getTileSetList",
        )
        async def tileset_list(
            request: Request,
            src_path=Depends(self.path_dependency),
            reader_params=Depends(self.reader_dependency),
            layer_params=Depends(self.layer_dependency),
            crs=Depends(CRSParams),
            env=Depends(self.environment_dependency),
        ):
            """Retrieve a list of available raster tilesets for the specified dataset."""
            with rasterio.Env(**env):
                with self.reader(src_path, **reader_params.as_dict()) as src_dst:
                    variables = layer_params.variables or src_dst.parse_expression(
                        layer_params.expression
                    )
                    groups = {
                        group_var.split(":")[0] if ":" in group_var else "/"
                        for group_var in variables
                    }
                    minx, miny, maxx, maxy = zip(
                        *[src_dst.get_bounds(group) for group in groups]
                    )
                    bounds = (min(minx), min(miny), max(maxx), max(maxy))

            collection_bbox = {
                "lowerLeft": [bounds[0], bounds[1]],
                "upperRight": [bounds[2], bounds[3]],
                "crs": CRS_to_uri(crs or WGS84_CRS),
            }

            qs = [
                (key, value)
                for (key, value) in request.query_params._list
                if key.lower() not in ["crs"]
            ]
            query_string = f"?{urlencode(qs)}" if qs else ""

            tilesets = []
            for tms in self.supported_tms.list():
                tileset = {
                    "title": f"tileset tiled using {tms} TileMatrixSet",
                    "dataType": "map",
                    "crs": self.supported_tms.get(tms).crs,
                    "boundingBox": collection_bbox,
                    "links": [
                        {
                            "href": self.url_for(
                                request, "tileset", tileMatrixSetId=tms
                            )
                            + query_string,
                            "rel": "self",
                            "type": "application/json",
                            "title": f"Tileset tiled using {tms} TileMatrixSet",
                        },
                        {
                            "href": self.url_for(
                                request,
                                "tile",
                                tileMatrixSetId=tms,
                                z="{z}",
                                x="{x}",
                                y="{y}",
                            )
                            + query_string,
                            "rel": "tile",
                            "title": "Templated link for retrieving Raster tiles",
                        },
                    ],
                }

                try:
                    tileset["links"].append(
                        {
                            "href": str(
                                request.url_for("tilematrixset", tileMatrixSetId=tms)
                            ),
                            "rel": "http://www.opengis.net/def/rel/ogc/1.0/tiling-scheme",
                            "type": "application/json",
                            "title": f"Definition of '{tms}' tileMatrixSet",
                        }
                    )
                except NoMatchFound:
                    pass

                tilesets.append(tileset)

            data = TileSetList.model_validate({"tilesets": tilesets})
            return data

        @self.router.get(
            "/tiles/{tileMatrixSetId}",
            response_model=TileSet,
            response_class=JSONResponse,
            response_model_exclude_none=True,
            responses={200: {"content": {"application/json": {}}}},
            summary="Retrieve the raster tileset metadata for the specified dataset and tiling scheme (tile matrix set).",
            operation_id=f"{self.operation_prefix}getTileSet",
        )
        async def tileset(
            request: Request,
            tileMatrixSetId: Annotated[
                Literal[tuple(self.supported_tms.list())],
                Path(
                    description="Identifier selecting one of the TileMatrixSetId supported."
                ),
            ],
            src_path=Depends(self.path_dependency),
            reader_params=Depends(self.reader_dependency),
            layer_params=Depends(self.layer_dependency),
            env=Depends(self.environment_dependency),
        ):
            """Retrieve the raster tileset metadata for the specified dataset and tiling scheme (tile matrix set)."""
            tms = self.supported_tms.get(tileMatrixSetId)
            with rasterio.Env(**env):
                with self.reader(
                    src_path, tms=tms, **reader_params.as_dict()
                ) as src_dst:
                    variables = layer_params.variables or src_dst.parse_expression(
                        layer_params.expression
                    )
                    groups = list(
                        {
                            group_var.split(":")[0] if ":" in group_var else "/"
                            for group_var in variables
                        }
                    )
                    crs = tms.rasterio_geographic_crs
                    minx, miny, maxx, maxy = zip(
                        *[src_dst.get_bounds(group, crs) for group in groups]
                    )
                    bounds = (min(minx), min(miny), max(maxx), max(maxy))

                    minzoom = min([src_dst.get_minzoom(group) for group in groups])
                    maxzoom = max([src_dst.get_maxzoom(group) for group in groups])

                    collection_bbox = {
                        "lowerLeft": [bounds[0], bounds[1]],
                        "upperRight": [bounds[2], bounds[3]],
                        "crs": CRS_to_uri(crs),
                    }

                    tilematrix_limit = []
                    for zoom in range(minzoom, maxzoom + 1, 1):
                        matrix = tms.matrix(zoom)
                        ulTile = tms.tile(bounds[0], bounds[3], int(matrix.id))
                        lrTile = tms.tile(bounds[2], bounds[1], int(matrix.id))
                        minx, maxx = (min(ulTile.x, lrTile.x), max(ulTile.x, lrTile.x))
                        miny, maxy = (min(ulTile.y, lrTile.y), max(ulTile.y, lrTile.y))
                        tilematrix_limit.append(
                            {
                                "tileMatrix": matrix.id,
                                "minTileRow": max(miny, 0),
                                "maxTileRow": min(maxy, matrix.matrixHeight),
                                "minTileCol": max(minx, 0),
                                "maxTileCol": min(maxx, matrix.matrixWidth),
                            }
                        )

            query_string = (
                f"?{urlencode(request.query_params._list)}"
                if request.query_params._list
                else ""
            )

            links = [
                {
                    "href": self.url_for(
                        request,
                        "tileset",
                        tileMatrixSetId=tileMatrixSetId,
                    ),
                    "rel": "self",
                    "type": "application/json",
                    "title": f"Tileset tiled using {tileMatrixSetId} TileMatrixSet",
                },
                {
                    "href": self.url_for(
                        request,
                        "tile",
                        tileMatrixSetId=tileMatrixSetId,
                        z="{z}",
                        x="{x}",
                        y="{y}",
                    )
                    + query_string,
                    "rel": "tile",
                    "title": "Templated link for retrieving Raster tiles",
                    "templated": True,
                },
            ]
            try:
                links.append(
                    {
                        "href": str(
                            request.url_for(
                                "tilematrixset", tileMatrixSetId=tileMatrixSetId
                            )
                        ),
                        "rel": "http://www.opengis.net/def/rel/ogc/1.0/tiling-scheme",
                        "type": "application/json",
                        "title": f"Definition of '{tileMatrixSetId}' tileMatrixSet",
                    }
                )
            except NoMatchFound:
                pass

            if self.add_viewer:
                links.append(
                    {
                        "href": self.url_for(
                            request,
                            "map_viewer",
                            tileMatrixSetId=tileMatrixSetId,
                        )
                        + query_string,
                        "type": "text/html",
                        "rel": "data",
                        "title": f"Map viewer for '{tileMatrixSetId}' tileMatrixSet",
                    }
                )

            data = TileSet.model_validate(
                {
                    "title": f"tileset tiled using {tileMatrixSetId} TileMatrixSet",
                    "dataType": "map",
                    "crs": tms.crs,
                    "boundingBox": collection_bbox,
                    "links": links,
                    "tileMatrixSetLimits": tilematrix_limit,
                }
            )

            return data

    def tilejson(self):  # noqa: C901
        """Register /tilejson.json endpoint."""

        @self.router.get(
            "/{tileMatrixSetId}/tilejson.json",
            response_model=TileJSON,
            responses={200: {"description": "Return a tilejson"}},
            response_model_exclude_none=True,
            operation_id=f"{self.operation_prefix}getTileJSON",
        )
        def tilejson(
            request: Request,
            tileMatrixSetId: Annotated[
                Literal[tuple(self.supported_tms.list())],
                Path(
                    description="Identifier selecting one of the TileMatrixSetId supported."
                ),
            ],
            tile_format: Annotated[
                Optional[ImageType],
                Query(
                    description="Default will be automatically defined if the output image needs a mask (png) or not (jpeg).",
                ),
            ] = None,
            tile_scale: Annotated[
                int,
                Query(
                    gt=0, lt=4, description="Tile size scale. 1=256x256, 2=512x512..."
                ),
            ] = 1,
            minzoom: Annotated[
                Optional[int],
                Query(description="Overwrite default minzoom."),
            ] = None,
            maxzoom: Annotated[
                Optional[int],
                Query(description="Overwrite default maxzoom."),
            ] = None,
            src_path=Depends(self.path_dependency),
            reader_params=Depends(self.reader_dependency),
            tile_params=Depends(self.tile_dependency),
            layer_params=Depends(self.layer_dependency),
            dataset_params=Depends(self.dataset_dependency),
            post_process=Depends(self.process_dependency),
            colormap=Depends(self.colormap_dependency),
            render_params=Depends(self.render_dependency),
            env=Depends(self.environment_dependency),
        ):
            """Return TileJSON document for a dataset."""
            route_params = {
                "z": "{z}",
                "x": "{x}",
                "y": "{y}",
                "scale": tile_scale,
                "tileMatrixSetId": tileMatrixSetId,
            }
            if tile_format:
                route_params["format"] = tile_format.value
            tiles_url = self.url_for(request, "tile", **route_params)

            qs_key_to_remove = [
                "tilematrixsetid",
                "tile_format",
                "tile_scale",
                "minzoom",
                "maxzoom",
            ]
            qs = [
                (key, value)
                for (key, value) in request.query_params._list
                if key.lower() not in qs_key_to_remove
            ]
            if qs:
                tiles_url += f"?{urlencode(qs)}"

            tms = self.supported_tms.get(tileMatrixSetId)
            with rasterio.Env(**env):
                logger.info(f"opening data with reader: {self.reader}")
                with self.reader(
                    src_path, tms=tms, **reader_params.as_dict()
                ) as src_dst:
                    variables = layer_params.variables or src_dst.parse_expression(
                        layer_params.expression
                    )
                    groups = {
                        group_var.split(":")[0] if ":" in group_var else "/"
                        for group_var in variables
                    }
                    minx, miny, maxx, maxy = zip(
                        *[
                            src_dst.get_bounds(group, tms.rasterio_geographic_crs)
                            for group in groups
                        ]
                    )
                    bounds = (min(minx), min(miny), max(maxx), max(maxy))

                    if minzoom is None:
                        minzoom = min([src_dst.get_minzoom(group) for group in groups])
                    if maxzoom is None:
                        maxzoom = max([src_dst.get_maxzoom(group) for group in groups])

                    return {
                        "bounds": bounds,
                        "minzoom": minzoom,
                        "maxzoom": maxzoom,
                        "tiles": [tiles_url],
                    }

    def wmts(self):  # noqa: C901
        """Register /wmts endpoint."""

        @self.router.get(
            "/{tileMatrixSetId}/WMTSCapabilities.xml",
            response_class=XMLResponse,
            operation_id=f"{self.operation_prefix}getWMTS",
        )
        def wmts(
            request: Request,
            tileMatrixSetId: Annotated[
                Literal[tuple(self.supported_tms.list())],
                Path(
                    description="Identifier selecting one of the TileMatrixSetId supported."
                ),
            ],
            tile_format: Annotated[
                ImageType,
                Query(description="Output image type. Default is png."),
            ] = ImageType.png,
            tile_scale: Annotated[
                int,
                Query(
                    gt=0, lt=4, description="Tile size scale. 1=256x256, 2=512x512..."
                ),
            ] = 1,
            minzoom: Annotated[
                Optional[int],
                Query(description="Overwrite default minzoom."),
            ] = None,
            maxzoom: Annotated[
                Optional[int],
                Query(description="Overwrite default maxzoom."),
            ] = None,
            use_epsg: Annotated[
                bool,
                Query(
                    description="Use EPSG code, not opengis.net, for the ows:SupportedCRS in the TileMatrixSet (set to True to enable ArcMap compatability)"
                ),
            ] = False,
            src_path=Depends(self.path_dependency),
            reader_params=Depends(self.reader_dependency),
            tile_params=Depends(self.tile_dependency),
            layer_params=Depends(self.layer_dependency),
            dataset_params=Depends(self.dataset_dependency),
            post_process=Depends(self.process_dependency),
            colormap=Depends(self.colormap_dependency),
            render_params=Depends(self.render_dependency),
            env=Depends(self.environment_dependency),
        ):
            """OGC WMTS endpoint."""
            route_params = {
                "z": "{TileMatrix}",
                "x": "{TileCol}",
                "y": "{TileRow}",
                "scale": tile_scale,
                "format": tile_format.value,
                "tileMatrixSetId": tileMatrixSetId,
            }
            tiles_url = self.url_for(request, "tile", **route_params)

            qs_key_to_remove = [
                "tilematrixsetid",
                "tile_format",
                "tile_scale",
                "minzoom",
                "maxzoom",
                "service",
                "use_epsg",
                "request",
            ]
            qs = [
                (key, value)
                for (key, value) in request.query_params._list
                if key.lower() not in qs_key_to_remove
            ]

            tms = self.supported_tms.get(tileMatrixSetId)
            with rasterio.Env(**env):
                logger.info(f"opening data with reader: {self.reader}")
                with self.reader(
                    src_path, tms=tms, **reader_params.as_dict()
                ) as src_dst:
                    variables = layer_params.variables or src_dst.parse_expression(
                        layer_params.expression
                    )
                    groups = {
                        group_var.split(":")[0] if ":" in group_var else "/"
                        for group_var in variables
                    }
                    minx, miny, maxx, maxy = zip(
                        *[
                            src_dst.get_bounds(group, tms.rasterio_geographic_crs)
                            for group in groups
                        ]
                    )
                    bounds = (min(minx), min(miny), max(maxx), max(maxy))

                    if minzoom is None:
                        minzoom = min([src_dst.get_minzoom(group) for group in groups])
                    if maxzoom is None:
                        maxzoom = max([src_dst.get_maxzoom(group) for group in groups])

            tileMatrix = []
            for zoom in range(minzoom, maxzoom + 1):
                matrix = tms.matrix(zoom)
                tm = f"""
                        <TileMatrix>
                            <ows:Identifier>{matrix.id}</ows:Identifier>
                            <ScaleDenominator>{matrix.scaleDenominator}</ScaleDenominator>
                            <TopLeftCorner>{matrix.pointOfOrigin[0]} {matrix.pointOfOrigin[1]}</TopLeftCorner>
                            <TileWidth>{matrix.tileWidth}</TileWidth>
                            <TileHeight>{matrix.tileHeight}</TileHeight>
                            <MatrixWidth>{matrix.matrixWidth}</MatrixWidth>
                            <MatrixHeight>{matrix.matrixHeight}</MatrixHeight>
                        </TileMatrix>"""
                tileMatrix.append(tm)

            if use_epsg:
                supported_crs = f"EPSG:{tms.crs.to_epsg()}"
            else:
                supported_crs = tms.crs.srs

            bbox_crs_type = "WGS84BoundingBox"
            bbox_crs_uri = "urn:ogc:def:crs:OGC:2:84"
            if tms.rasterio_geographic_crs != WGS84_CRS:
                bbox_crs_type = "BoundingBox"
                bbox_crs_uri = CRS_to_urn(tms.rasterio_geographic_crs)
                # WGS88BoundingBox is always xy ordered, but BoundingBox must match the CRS order
                if crs_axis_inverted(tms.geographic_crs):
                    # match the bounding box coordinate order to the CRS
                    bounds = (bounds[1], bounds[0], bounds[3], bounds[2])

            layers = [
                {
                    "title": "TiTiler",
                    "name": "default",
                    "tiles_url": tiles_url,
                    "query_string": urlencode(qs, doseq=True) if qs else None,
                    "bounds": bounds,
                },
            ]

            return self.templates.TemplateResponse(
                request,
                name="wmts.xml",
                context={
                    "tileMatrixSetId": tms.id,
                    "tileMatrix": tileMatrix,
                    "supported_crs": supported_crs,
                    "bbox_crs_type": bbox_crs_type,
                    "bbox_crs_uri": bbox_crs_uri,
                    "layers": layers,
                    "media_type": tile_format.mediatype,
                },
                media_type="application/xml",
            )
