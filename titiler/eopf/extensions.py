"""titiler.xarray Extensions."""

import json
import math
from typing import Annotated, Any
from urllib.parse import urlencode

import jinja2
import rasterio
from attrs import define
from fastapi import Depends, Query
from geojson_pydantic.features import Feature
from morecantile.models import crs_axis_inverted
from rasterio import windows
from rasterio.crs import CRS
from rasterio.warp import calculate_default_transform, transform_geom
from rio_tiler.constants import WGS84_CRS
from rio_tiler.utils import CRS_to_urn
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.templating import Jinja2Templates

from titiler.core.factory import FactoryExtension
from titiler.core.resources.enums import ImageType, MediaType
from titiler.core.resources.responses import GeoJSONResponse, XMLResponse
from titiler.core.utils import bounds_to_geometry, rio_crs_to_pyproj, tms_limits
from titiler.extensions.wmts import wmtsExtension

from .factory import TilerFactory
from .reader import MissingVariables

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
            level: Annotated[str, Query(description="Multiscale Level (matrix ID)")],
            src_path=Depends(factory.path_dependency),
        ):
            """return geojson."""
            with factory.reader(src_path) as src_dst:
                if multiscales := src_dst.datatree[group].attrs.get("multiscales"):
                    # Find matrix by id
                    matrix = next(
                        (
                            m
                            for m in multiscales["tile_matrix_set"]["tileMatrices"]
                            if m["id"] == level
                        ),
                        None,
                    )
                    if matrix is None:
                        raise ValueError(
                            f"Level '{level}' not found in multiscale matrices"
                        )

                    ds = src_dst.datatree[group][level].to_dataset()
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


@define
class EOPFwmtsExtension(wmtsExtension):
    """RESTful WMTS service Extension for TilerFactory."""

    def register(self, factory: TilerFactory):  # type: ignore [override] # noqa: C901
        """Register extension's endpoints."""

        @factory.router.get(
            "/WMTSCapabilities.xml",
            response_class=XMLResponse,
            responses={
                200: {
                    "content": {"application/xml": {}},
                    "description": "Return RESTful WMTS service capabilities document.",
                }
            },
            operation_id=f"{factory.operation_prefix}getWMTS",
        )
        def wmts(  # noqa: C901
            request: Request,
            tile_format: Annotated[
                ImageType,
                Query(description="Output image type. Default is png."),
            ] = ImageType.png,
            use_epsg: Annotated[
                bool,
                Query(
                    description="Use EPSG code, not opengis.net, for the ows:SupportedCRS in the TileMatrixSet (set to True to enable ArcMap compatability)"
                ),
            ] = False,
            minzoom: Annotated[
                int | None,
                Query(description="Overwrite default minzoom."),
            ] = None,
            maxzoom: Annotated[
                int | None,
                Query(description="Overwrite default maxzoom."),
            ] = None,
            src_path=Depends(factory.path_dependency),
            reader_params=Depends(factory.reader_dependency),
            tile_params=Depends(factory.tile_dependency),
            layer_params=Depends(factory.layer_dependency),
            dataset_params=Depends(factory.dataset_dependency),
            post_process=Depends(factory.process_dependency),
            colormap=Depends(factory.colormap_dependency),
            render_params=Depends(factory.render_dependency),
            env=Depends(factory.environment_dependency),
        ):
            """OGC RESTful WMTS endpoint."""
            with rasterio.Env(**env):
                with factory.reader(src_path, **reader_params.as_dict()) as src_dst:
                    variables = layer_params.variables or src_dst.parse_expression(
                        layer_params.expression
                    )
                    if not variables:
                        raise MissingVariables(
                            "`variables` must be passed via `expression` or `variables` options."
                        )

                    groups = {
                        group_var.split(":")[0] if ":" in group_var else "/"
                        for group_var in variables
                    }

            qs_key_to_remove = [
                "tile_format",
                "use_epsg",
                # Make sure tilesize is not ovewrriden from WMTS request
                "tilesize",
                # OGC WMTS parameters to ignore
                "service",
                "request",
                "acceptversions",
                "sections",
                "updatesequence",
                "acceptformats",
            ]

            qs = urlencode(
                [
                    (key, value)
                    for (key, value) in request.query_params._list
                    if key.lower() not in qs_key_to_remove
                ],
                doseq=True,
            )
            render: dict[str, Any] = {"name": "default", "query_string": qs}

            layers: list[dict[str, Any]] = []
            title = src_path if isinstance(src_path, str) else "TiTiler"

            bounds: tuple[float, float, float, float]
            for tms_id in factory.supported_tms.list():
                tms = factory.supported_tms.get(tms_id)
                try:
                    with factory.reader(
                        src_path, tms=tms, **reader_params.as_dict()
                    ) as src_dst:
                        minx, miny, maxx, maxy = zip(
                            *[src_dst.get_bounds(group, self.crs) for group in groups]
                        )
                        bounds = (min(minx), min(miny), max(maxx), max(maxy))

                        if minzoom is None:
                            minzoom = min(
                                [src_dst.get_minzoom(group) for group in groups]
                            )
                        if maxzoom is None:
                            maxzoom = max(
                                [src_dst.get_maxzoom(group) for group in groups]
                            )

                        tilematrixset_limits = tms_limits(
                            tms,
                            bounds,
                            zooms=(minzoom, maxzoom),
                            geographic_crs=self.crs,
                        )

                    route_params = {
                        "z": "{TileMatrix}",
                        "x": "{TileCol}",
                        "y": "{TileRow}",
                        "format": tile_format.value,
                        "tileMatrixSetId": tms_id,
                    }

                    bbox = bounds
                    bbox_crs_type = "WGS84BoundingBox"
                    bbox_crs_uri = "urn:ogc:def:crs:OGC:2:84"
                    if self.crs != WGS84_CRS:
                        bbox_crs_type = "BoundingBox"
                        bbox_crs_uri = CRS_to_urn(self.crs)  # type: ignore
                        # WGS88BoundingBox is always xy ordered, but BoundingBox must match the CRS order
                        proj_crs = rio_crs_to_pyproj(self.crs)
                        if crs_axis_inverted(proj_crs):
                            # match the bounding box coordinate order to the CRS
                            bbox = (bbox[1], bbox[0], bbox[3], bbox[2])

                    layers.append(
                        {
                            "title": f"{title}_{tms_id}_{render['name']}",
                            "identifier": f"{title}_{tms_id}_{render['name']}",
                            "tms_identifier": tms_id,
                            "tms_limits": tilematrixset_limits,
                            "tiles_url": factory.url_for(
                                request, "tile", **route_params
                            ),
                            "query_string": render["query_string"],
                            "bbox_crs_type": bbox_crs_type,
                            "bbox_crs_uri": bbox_crs_uri,
                            "bbox": bbox,
                        }
                    )

                except Exception as e:  # noqa
                    pass

            tileMatrixSets: list[dict[str, Any]] = []
            for tms_id in factory.supported_tms.list():
                tms = factory.supported_tms.get(tms_id)
                if use_epsg:
                    supported_crs = f"EPSG:{tms.crs.to_epsg()}"
                else:
                    supported_crs = tms.crs.srs

                tileMatrixSets.append(
                    {"id": tms_id, "crs": supported_crs, "matrices": tms.tileMatrices}
                )

            return self.templates.TemplateResponse(
                request,
                name="wmts.xml",
                context={
                    "layers": layers,
                    "tileMatrixSets": tileMatrixSets,
                    "media_type": tile_format.mediatype,
                },
                media_type="application/xml",
            )
