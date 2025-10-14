"""titiler.xarray Extensions."""

import json
import math
from typing import Annotated

import jinja2
from attrs import define
from fastapi import Depends, Query
from geojson_pydantic.features import Feature
from rasterio import windows
from rasterio.crs import CRS
from rasterio.warp import calculate_default_transform, transform_geom
from rio_tiler.constants import WGS84_CRS
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.templating import Jinja2Templates

from titiler.core.factory import FactoryExtension
from titiler.core.resources.enums import MediaType
from titiler.core.resources.responses import GeoJSONResponse
from titiler.core.utils import bounds_to_geometry

from .factory import TilerFactory

jinja2_env = jinja2.Environment(
    autoescape=jinja2.select_autoescape(["html"]),
    loader=jinja2.ChoiceLoader([jinja2.PackageLoader(__package__, "templates")]),
)
DEFAULT_TEMPLATES = Jinja2Templates(env=jinja2_env)


@define
class DatasetMetadataExtension(FactoryExtension):
    """Add dataset metadata endpoints to a Factory."""

    def register(self, factory: TilerFactory):
        """Register endpoint to the tiler factory."""

        @factory.router.get(
            "/dataset/",
            responses={
                200: {
                    "description": "Returns the HTML representation of the Xarray DataTree.",
                    "content": {
                        MediaType.html.value: {},
                    },
                },
            },
            response_class=HTMLResponse,
        )
        def dataset_metadata_html(src_path=Depends(factory.path_dependency)):
            """Returns the HTML representation of the Xarray Dataset."""
            with factory.reader(src_path) as ds:
                return HTMLResponse(ds.datatree._repr_html_())

        @factory.router.get(
            "/dataset/dict",
            responses={
                200: {"description": "Returns the full Xarray dataset as a dictionary."}
            },
        )
        def dataset_metadata_dict(src_path=Depends(factory.path_dependency)):
            """Returns the full Xarray dataset as a dictionary."""
            with factory.reader(src_path) as ds:
                return {
                    k: g.to_dataset().to_dict(data=False)
                    for k, g in ds.datatree.subtree_with_keys
                }

        @factory.router.get(
            "/dataset/groups",
            response_model=list[str],
            responses={
                200: {"description": "Returns the list of groups in the DataTree."}
            },
        )
        def dataset_groups(src_path=Depends(factory.path_dependency)):
            """Returns the list of groups in the DataTree."""
            with factory.reader(src_path) as ds:
                return ds.groups

        @factory.router.get(
            "/dataset/keys",
            response_model=list[str],
            responses={
                200: {
                    "description": "Returns the list of keys/variables in the DataTree."
                }
            },
        )
        def dataset_variables(src_path=Depends(factory.path_dependency)):
            """Returns the list of keys/variables in the DataTree."""
            with factory.reader(src_path) as ds:
                return ds.variables


@define
class EOPFViewerExtension(FactoryExtension):
    """Add /viewer endpoint to the TilerFactory."""

    templates: Jinja2Templates = DEFAULT_TEMPLATES

    def register(self, factory: TilerFactory):
        """Register endpoint to the tiler factory."""

        @factory.router.get(
            "/viewer",
            response_class=HTMLResponse,
            operation_id=f"{factory.operation_prefix}getViewer",
        )
        def html_viewer(request: Request):
            """Viewer."""
            return self.templates.TemplateResponse(
                request,
                name="viewer.html",
                context={
                    "tilejson_endpoint": factory.url_for(
                        request,
                        "tilejson",
                        tileMatrixSetId="WebMercatorQuad",
                    ),
                    "info_endpoint": factory.url_for(request, "info_geojson"),
                },
                media_type="text/html",
            )


def _dims(total: int, chop: int):
    """Given a total number of pixels, chop into equal chunks.

    yeilds (offset, size) tuples
    >>> list(dims(512, 256))
    [(0, 256), (256, 256)]
    >>> list(dims(502, 256))
    [(0, 256), (256, 246)]
    >>> list(dims(522, 256))
    [(0, 256), (256, 256), (512, 10)]
    """
    for a in range(int(math.ceil(total / chop))):
        offset = a * chop
        yield offset, chop


def bbox_to_feature(
    bbox: tuple[float, float, float, float],
    properties: dict | None = None,
) -> dict:
    """Create a GeoJSON feature polygon from a bounding box."""
    # Dateline crossing dataset
    if bbox[0] > bbox[2]:
        bounds_left = [-180, bbox[1], bbox[2], bbox[3]]
        bounds_right = [bbox[0], bbox[1], 180, bbox[3]]

        features = [
            {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [bounds_left[0], bounds_left[3]],
                            [bounds_left[0], bounds_left[1]],
                            [bounds_left[2], bounds_left[1]],
                            [bounds_left[2], bounds_left[3]],
                            [bounds_left[0], bounds_left[3]],
                        ]
                    ],
                },
                "properties": properties or {},
                "type": "Feature",
            },
            {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [bounds_right[0], bounds_right[3]],
                            [bounds_right[0], bounds_right[1]],
                            [bounds_right[2], bounds_right[1]],
                            [bounds_right[2], bounds_right[3]],
                            [bounds_right[0], bounds_right[3]],
                        ]
                    ],
                },
                "properties": properties or {},
                "type": "Feature",
            },
        ]
    else:
        features = [
            {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [bbox[0], bbox[3]],
                            [bbox[0], bbox[1]],
                            [bbox[2], bbox[1]],
                            [bbox[2], bbox[3]],
                            [bbox[0], bbox[3]],
                        ]
                    ],
                },
                "properties": properties or {},
                "type": "Feature",
            },
        ]

    return {"type": "FeatureCollection", "features": features}


@define
class EOPFChunkVizExtension(FactoryExtension):
    """Add /chunks.html endpoint to the TilerFactory."""

    templates: Jinja2Templates = DEFAULT_TEMPLATES

    def register(self, factory: TilerFactory):  # noqa: C901
        """Register endpoint to the tiler factory."""

        @factory.router.get(
            "/chunks.html",
            response_class=HTMLResponse,
            operation_id=f"{factory.operation_prefix}getChunkViewer",
        )
        def chunk_viewer(
            request: Request,
            src_path=Depends(factory.path_dependency),
        ):
            """Chunk Viewer."""
            with factory.reader(src_path) as src_dst:
                groups = src_dst.groups
                minx, miny, maxx, maxy = zip(
                    *[src_dst.get_bounds(group, WGS84_CRS) for group in groups]
                )
                bounds = (min(minx), min(miny), max(maxx), max(maxy))
                geojson = Feature(
                    type="Feature",
                    bbox=bounds,
                    geometry=bounds_to_geometry(bounds),
                    properties={},
                ).model_dump_json(exclude_none=True)

                metadata = {}
                for group in groups:
                    # get MultiScale info
                    levels = []
                    if multiscales := src_dst.datatree[group].attrs.get("multiscales"):
                        raw_res = None

                        scale = src_dst.datatree[group].attrs["multiscales"][
                            "tile_matrix_set"
                        ]["tileMatrices"][0]["id"]
                        ds = src_dst.datatree[group][scale].to_dataset()
                        crs = CRS.from_user_input(multiscales["tile_matrix_set"]["crs"])
                        bounds = ds.rio.bounds()
                        width = ds.rio.width
                        height = ds.rio.height

                        for mat in multiscales["tile_matrix_set"]["tileMatrices"]:
                            raw_res = mat["cellSize"] if raw_res is None else raw_res
                            decimation = mat["cellSize"] / raw_res

                            dst_affine, _, _ = calculate_default_transform(
                                crs,
                                src_dst.tms.rasterio_crs,
                                math.ceil(width / decimation),
                                math.ceil(height / decimation),
                                *bounds,
                            )
                            resolution = max(abs(dst_affine[0]), abs(dst_affine[4]))
                            zoom = src_dst.tms.zoom_for_res(resolution)

                            levels.append(
                                {
                                    "Level": mat["id"],
                                    "Width": math.ceil(width / decimation),
                                    "Height": math.ceil(height / decimation),
                                    "ChunkSize": (mat["tileWidth"], mat["tileHeight"]),
                                    "Decimation": decimation,
                                    "MercatorZoom": zoom,
                                    "MercatorResolution": resolution,
                                    "Variables": list(
                                        {
                                            var
                                            for var, data_array in ds.data_vars.items()
                                            if data_array.ndim > 0
                                        }
                                    ),
                                }
                            )

                    else:
                        ds = src_dst.datatree[group].to_dataset()
                        preferred_chunks = ds.encoding.get("preferred_chunks", {})
                        if {"x", "y"}.intersection(preferred_chunks):
                            chunkxsize = preferred_chunks["x"]
                            chunkysize = preferred_chunks["y"]
                        else:
                            chunkxsize = ds.rio.width
                            chunkysize = ds.rio.height

                        dst_affine, _, _ = calculate_default_transform(
                            ds.rio.crs,
                            src_dst.tms.rasterio_crs,
                            ds.rio.width,
                            ds.rio.height,
                            *ds.rio.bounds(),
                        )
                        resolution = max(abs(dst_affine[0]), abs(dst_affine[4]))
                        zoom = src_dst.tms.zoom_for_res(resolution)

                        levels.append(
                            {
                                "Level": "0",
                                "Width": ds.rio.width,
                                "Height": ds.rio.height,
                                "ChunkSize": (chunkxsize, chunkysize),
                                "Decimation": 1,
                                "MercatorZoom": zoom,
                                "MercatorResolution": resolution,
                                "Variables": list(
                                    {
                                        var
                                        for var, data_array in ds.data_vars.items()
                                        if data_array.ndim > 0
                                    }
                                ),
                            }
                        )
                    metadata[group] = levels

            return self.templates.TemplateResponse(
                request,
                name="chunks.html",
                context={
                    "geojson": geojson,
                    "metadata": json.dumps(metadata),
                    "grid_endpoint": factory.url_for(request, "chunk_grid"),
                    "tile_endpoint": factory.url_for(
                        request,
                        "tile",
                        z="${z}",
                        x="${x}",
                        y="${y}",
                        tileMatrixSetId="WebMercatorQuad",
                    ),
                },
                media_type="text/html",
            )

        @factory.router.get(
            r"/chunk.geojson",
            response_model_exclude_none=True,
            response_class=GeoJSONResponse,
        )
        def chunk_grid(
            group: Annotated[str, Query(description="Group")],
            level: Annotated[int, Query(description="Multiscale Level")],
            src_path=Depends(factory.path_dependency),
        ):
            """return geojson."""
            with factory.reader(src_path) as src_dst:
                if multiscales := src_dst.datatree[group].attrs.get("multiscales"):
                    matrix = multiscales["tile_matrix_set"]["tileMatrices"][level]
                    scale = matrix["id"]
                    ds = src_dst.datatree[group][scale].to_dataset()
                    blockysize = matrix["tileHeight"]
                    blockxsize = matrix["tileWidth"]
                    crs = CRS.from_user_input(multiscales["tile_matrix_set"]["crs"])

                else:
                    ds = src_dst.datatree[group].to_dataset()
                    chunksizes = (
                        ds.chunksizes
                        if ds.chunksizes
                        else (ds.rio.height, ds.rio.width)
                    )
                    blockysize = chunksizes[0]
                    blockxsize = chunksizes[1]
                    crs = ds.rio.crs or WGS84_CRS

                transform = ds.rio.transform()
                # try:
                feats = []
                winds = (
                    windows.Window(col_off=col_off, row_off=row_off, width=w, height=h)
                    for row_off, h in _dims(ds.rio.height, blockysize)
                    for col_off, w in _dims(ds.rio.width, blockxsize)
                )
                for window in winds:
                    fc = bbox_to_feature(windows.bounds(window, transform))
                    for feat in fc.get("features", []):
                        if crs != WGS84_CRS:
                            geom = transform_geom(crs, WGS84_CRS, feat["geometry"])
                        else:
                            geom = feat["geometry"]

                        feats.append(
                            {
                                "type": "Feature",
                                "geometry": geom,
                                "properties": {"window": str(window)},
                            }
                        )

            return {"type": "FeatureCollection", "features": feats}
