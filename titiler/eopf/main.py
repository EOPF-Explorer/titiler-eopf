"""titiler.eopf Application."""

import logging
import os
from typing import Annotated, Literal, Optional

# Configure logging
log_level = os.getenv("LOG_LEVEL", "INFO")
logging.basicConfig(
    level=log_level,
    format="%(levelname)s - %(message)s",
)


import jinja2
import rasterio
import xarray
import zarr
from fastapi import FastAPI, Query
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.templating import Jinja2Templates
from starlette_cramjam.middleware import CompressionMiddleware

from titiler.core.errors import DEFAULT_STATUS_CODES, add_exception_handlers
from titiler.core.factory import AlgorithmFactory, ColorMapFactory, TMSFactory
from titiler.core.middleware import CacheControlMiddleware
from titiler.core.models.OGC import Conformance, Landing
from titiler.core.resources.enums import MediaType
from titiler.core.templating import create_html_response
from titiler.core.utils import accept_media_type, update_openapi

from . import __version__ as titiler_version
from .dependencies import DatasetPathParams
from .extensions import DatasetMetadataExtension
from .factory import TilerFactory
from .settings import ApiSettings

settings = ApiSettings()

# HTML templates
html_templates = Jinja2Templates(
    env=jinja2.Environment(
        loader=jinja2.ChoiceLoader(
            [
                jinja2.PackageLoader(__package__, "templates"),
                jinja2.PackageLoader("titiler.core.templating", "html"),
            ]
        )
    )
)

# Map templates
map_templates = Jinja2Templates(
    env=jinja2.Environment(
        loader=jinja2.ChoiceLoader(
            [
                jinja2.PackageLoader(__package__, "templates"),
                jinja2.PackageLoader("titiler.core", "templates"),
            ]
        )
    )
)

app = FastAPI(
    title=settings.name,
    description="""

---

**Source Code**: <a href="https://github.com/EOPF-Explorer/titiler-eopf" target="_blank">https://github.com/EOPF-Explorer/titiler-eopfr</a>

---
    """,
    openapi_url="/api",
    docs_url="/api.html",
    version=titiler_version,
)

update_openapi(app)

TITILER_CONFORMS_TO = {
    "http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/core",
    "http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/landing-page",
    "http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/oas30",
    "http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/html",
    "http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/json",
}


md = TilerFactory(
    templates=map_templates,
    extensions=[
        DatasetMetadataExtension(),
    ],
    path_dependency=DatasetPathParams,
    router_prefix="/collections/{collection_id}/items/{item_id}",
)
app.include_router(md.router, prefix="/collections/{collection_id}/items/{item_id}")

TITILER_CONFORMS_TO.update(md.conforms_to)

# TileMatrixSets endpoints
tms = TMSFactory()
app.include_router(tms.router, tags=["Tiling Schemes"])
TITILER_CONFORMS_TO.update(tms.conforms_to)

###############################################################################
# Algorithms endpoints
algorithms = AlgorithmFactory()
app.include_router(
    algorithms.router,
    tags=["Algorithms"],
)
TITILER_CONFORMS_TO.update(algorithms.conforms_to)

# Colormaps endpoints
cmaps = ColorMapFactory()
app.include_router(
    cmaps.router,
    tags=["ColorMaps"],
)
TITILER_CONFORMS_TO.update(cmaps.conforms_to)

add_exception_handlers(app, DEFAULT_STATUS_CODES)

# Set all CORS enabled origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=settings.cors_allow_methods,
    allow_headers=["*"],
)

app.add_middleware(
    CompressionMiddleware,
    minimum_size=0,
    exclude_mediatype={
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/jp2",
        "image/webp",
    },
    compression_level=6,
)

app.add_middleware(
    CacheControlMiddleware,
    cachecontrol=settings.cachecontrol,
    exclude_path={r"/_mgmt*"},
)


# Health Check Endpoints
@app.get("/_mgmt/ping", description="Liveliness", tags=["Liveliness/Readiness"])
def ping():
    """Ping."""
    return {"message": "PONG"}


@app.get("/_mgmt/health", description="Readiness", tags=["Liveliness/Readiness"])
def health():
    """Health check."""
    return {
        "status": "UP",
        "versions": {
            "titiler": titiler_version,
            "rasterio": rasterio.__version__,
            "gdal": rasterio.__gdal_version__,
            "proj": rasterio.__proj_version__,
            "geos": rasterio.__geos_version__,
            "xarray": xarray.__version__,
            "zarr": zarr.__version__,
        },
    }


@app.get(
    "/",
    response_model=Landing,
    response_model_exclude_none=True,
    responses={
        200: {
            "content": {
                "text/html": {},
                "application/json": {},
            }
        },
    },
    tags=["OGC Common"],
)
def landing(
    request: Request,
    f: Annotated[
        Optional[Literal["html", "json"]],
        Query(
            description="Response MediaType. Defaults to endpoint's default or value defined in `accept` header."
        ),
    ] = None,
):
    """Landing page."""
    data = {
        "title": settings.name,
        "links": [
            {
                "title": "Landing page",
                "href": str(request.url_for("landing")),
                "type": "text/html",
                "rel": "self",
            },
            {
                "title": "The API definition (JSON)",
                "href": str(request.url_for("openapi")),
                "type": "application/vnd.oai.openapi+json;version=3.0",
                "rel": "service-desc",
            },
            {
                "title": "The API documentation",
                "href": str(request.url_for("swagger_ui_html")),
                "type": "text/html",
                "rel": "service-doc",
            },
            {
                "title": "Conformance Declaration",
                "href": str(request.url_for("conformance")),
                "type": "text/html",
                "rel": "http://www.opengis.net/def/rel/ogc/1.0/conformance",
            },
            {
                "title": "titiler.eopf source code (external link)",
                "href": "https://github.com/EOPF-Explorer/titiler-eopf",
                "type": "text/html",
                "rel": "doc",
            },
        ],
    }

    output_type: Optional[MediaType]
    if f:
        output_type = MediaType[f]
    else:
        accepted_media = [MediaType.html, MediaType.json]
        output_type = accept_media_type(
            request.headers.get("accept", ""), accepted_media
        )

    if output_type == MediaType.html:
        return create_html_response(
            request,
            data,
            title="TiTiler-EOPF",
            template_name="landing",
            templates=html_templates,
        )

    return data


@app.get(
    "/conformance",
    response_model=Conformance,
    response_model_exclude_none=True,
    responses={
        200: {
            "content": {
                "text/html": {},
                "application/json": {},
            }
        },
    },
    tags=["OGC Common"],
)
def conformance(
    request: Request,
    f: Annotated[
        Optional[Literal["html", "json"]],
        Query(
            description="Response MediaType. Defaults to endpoint's default or value defined in `accept` header."
        ),
    ] = None,
):
    """Conformance classes.

    Called with `GET /conformance`.

    Returns:
        Conformance classes which the server conforms to.

    """
    data = {"conformsTo": sorted(TITILER_CONFORMS_TO)}

    output_type: Optional[MediaType]
    if f:
        output_type = MediaType[f]
    else:
        accepted_media = [MediaType.html, MediaType.json]
        output_type = accept_media_type(
            request.headers.get("accept", ""), accepted_media
        )

    if output_type == MediaType.html:
        return create_html_response(
            request,
            data,
            title="Conformance",
            template_name="conformance",
            templates=html_templates,
        )

    return data
