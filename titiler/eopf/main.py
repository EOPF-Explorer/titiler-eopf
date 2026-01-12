"""titiler.eopf Application."""

import logging
import os
from typing import Annotated, Literal, Optional

import jinja2
import rasterio
import xarray
import zarr
from fastapi import FastAPI, Query
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.templating import Jinja2Templates
from starlette_cramjam.middleware import CompressionMiddleware

from titiler.cache import CacheKeyGenerator, TileCacheMiddleware
from titiler.cache.backends.redis import RedisCacheBackend
from titiler.cache.backends.s3 import S3StorageBackend
from titiler.cache.backends.s3_redis import S3RedisCacheBackend
from titiler.core.errors import DEFAULT_STATUS_CODES, add_exception_handlers
from titiler.core.factory import AlgorithmFactory, ColorMapFactory, TMSFactory
from titiler.core.middleware import CacheControlMiddleware, TotalTimeMiddleware
from titiler.core.models.OGC import Conformance, Landing
from titiler.core.resources.enums import MediaType
from titiler.core.utils import accept_media_type, create_html_response, update_openapi

from . import __version__ as titiler_version
from .cache_deps import setup_cache
from .dependencies import DatasetPathParams
from .extensions import (
    DatasetMetadataExtension,
    EOPFChunkVizExtension,
    EOPFViewerExtension,
)
from .factory import TilerFactory
from .settings import ApiSettings, EOPFCacheSettings

# Configure logging
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)

# Set up logger for this module
logger = logging.getLogger(__name__)
logger.info(f"Starting TiTiler EOPF application with log level: {log_level}")

settings = ApiSettings()
cache_settings = EOPFCacheSettings()


def setup_cache_system():
    """Setup cache backend and key generator."""
    if not cache_settings.enable:
        logger.info("Cache system disabled")
        return None, None

    logger.info(f"Setting up cache system with backend: {cache_settings.backend}")

    # Create cache key generator
    key_generator = CacheKeyGenerator(
        namespace=cache_settings.namespace,
        exclude_params=cache_settings.exclude_params,
        max_key_length=2048,
    )

    # Create cache backend based on configuration
    if cache_settings.backend == "redis" and cache_settings.redis:
        cache_backend = RedisCacheBackend(cache_settings.redis)
        logger.info(
            f"Redis cache configured: {cache_settings.redis.host}:{cache_settings.redis.port}"
        )

    elif cache_settings.backend == "s3" and cache_settings.s3:
        cache_backend = S3StorageBackend(cache_settings.s3)
        logger.info(f"S3 cache configured: {cache_settings.s3.bucket}")

    elif (
        cache_settings.backend == "s3-redis"
        and cache_settings.redis
        and cache_settings.s3
    ):
        cache_backend = S3RedisCacheBackend(
            redis_settings=cache_settings.redis, s3_settings=cache_settings.s3
        )
        logger.info(
            f"S3+Redis cache configured: Redis {cache_settings.redis.host}, S3 {cache_settings.s3.bucket}"
        )

    else:
        logger.warning(
            f"Invalid cache configuration for backend: {cache_settings.backend}"
        )
        return None, None

    # Setup dependency injection
    setup_cache(cache_backend, key_generator)

    logger.info("Cache system setup complete")
    return cache_backend, key_generator


# Initialize cache system
cache_backend, cache_key_generator = setup_cache_system()

# HTML templates
templates = Jinja2Templates(
    autoescape=jinja2.select_autoescape(["html", "xml"]),
    env=jinja2.Environment(
        loader=jinja2.ChoiceLoader(
            [
                jinja2.PackageLoader(__package__, "templates"),
                jinja2.PackageLoader("titiler.core", "templates"),
            ]
        )
    ),
)


app = FastAPI(
    title=settings.name,
    description="""

---

**Source Code**: <a href="https://github.com/EOPF-Explorer/titiler-eopf" target="_blank">https://github.com/EOPF-Explorer/titiler-eopfr</a>

---
    """,
    root_path=settings.root_path,
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
    templates=templates,
    extensions=[
        DatasetMetadataExtension(),
        EOPFViewerExtension(),
        EOPFChunkVizExtension(),
    ],
    path_dependency=DatasetPathParams,
    router_prefix="/collections/{collection_id}/items/{item_id}",
)
app.include_router(md.router, prefix="/collections/{collection_id}/items/{item_id}")

TITILER_CONFORMS_TO.update(md.conforms_to)

# TileMatrixSets endpoints
tms = TMSFactory(templates=templates)
app.include_router(tms.router, tags=["Tiling Schemes"])
TITILER_CONFORMS_TO.update(tms.conforms_to)

###############################################################################
# Algorithms endpoints
algorithms = AlgorithmFactory(templates=templates)
app.include_router(
    algorithms.router,
    tags=["Algorithms"],
)
TITILER_CONFORMS_TO.update(algorithms.conforms_to)

# Colormaps endpoints
cmaps = ColorMapFactory(templates=templates)
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

# Add tile cache middleware if caching is enabled
if cache_backend and cache_key_generator:
    app.add_middleware(
        TileCacheMiddleware,
        cache_backend=cache_backend,
        key_generator=cache_key_generator,
        cache_paths=cache_settings.cache_paths,
        default_ttl=cache_settings.default_ttl,
        cache_status_header="X-Cache",
    )
    logger.info("Tile cache middleware enabled")

app.add_middleware(
    CacheControlMiddleware,
    cachecontrol=settings.cachecontrol,
    exclude_path={r"/_mgmt*"},
)

if settings.debug:
    print(settings.debug)
    app.add_middleware(TotalTimeMiddleware)


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


@app.get("/_mgmt/cache", description="Cache Status", tags=["Cache Management"])
async def cache_status():
    """Get cache system status."""
    if not cache_backend:
        return {"cache": {"status": "disabled"}}

    try:
        # Try to get cache health
        is_healthy = await cache_backend.health_check()
        stats = (
            await cache_backend.get_stats()
            if hasattr(cache_backend, "get_stats")
            else {}
        )

        return {
            "cache": {
                "status": "enabled",
                "backend": cache_settings.backend,
                "healthy": is_healthy,
                "namespace": cache_settings.namespace,
                "default_ttl": cache_settings.default_ttl,
                "stats": stats,
                "settings": {
                    "tile_ttl": cache_settings.tile_ttl,
                    "metadata_ttl": cache_settings.metadata_ttl,
                    "exclude_params": cache_settings.exclude_params,
                    "cache_paths": cache_settings.cache_paths,
                },
            }
        }
    except Exception as e:
        return {
            "cache": {
                "status": "error",
                "error": str(e),
                "backend": cache_settings.backend,
            }
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
                "title": "List of Available TileMatrixSets",
                "href": str(request.url_for("tilematrixsets")),
                "type": "application/json",
                "rel": "http://www.opengis.net/def/rel/ogc/1.0/tiling-schemes",
            },
            {
                "title": "List of Available Algorithms",
                "href": str(request.url_for("available_algorithms")),
                "type": "application/json",
                "rel": "data",
            },
            {
                "title": "List of Available ColorMaps",
                "href": str(request.url_for("available_colormaps")),
                "type": "application/json",
                "rel": "data",
            },
            {
                "title": "titiler.eopf source code (external link)",
                "href": "https://github.com/EOPF-Explorer/titiler-eopf",
                "type": "text/html",
                "rel": "doc",
            },
        ],
    }

    if f:
        output_type = MediaType[f]
    else:
        accepted_media = [MediaType.html, MediaType.json]
        output_type = (
            accept_media_type(request.headers.get("accept", ""), accepted_media)
            or MediaType.json
        )

    if output_type == MediaType.html:
        return create_html_response(
            request,
            data,
            title="TiTiler-EOPF",
            template_name="landing",
            templates=templates,
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

    if f:
        output_type = MediaType[f]
    else:
        accepted_media = [MediaType.html, MediaType.json]
        output_type = (
            accept_media_type(request.headers.get("accept", ""), accepted_media)
            or MediaType.json
        )

    if output_type == MediaType.html:
        return create_html_response(
            request,
            data,
            title="Conformance",
            template_name="conformance",
            templates=templates,
        )

    return data
