"""titiler-openeo app."""

import logging

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from openeo_pg_parser_networkx.process_registry import Process
from starlette.middleware.cors import CORSMiddleware
from starlette_cramjam.middleware import CompressionMiddleware

from titiler.openeo.auth import get_auth
from titiler.openeo.errors import ExceptionHandler, OpenEOException
from titiler.openeo.factory import EndpointsFactory
from titiler.openeo.middleware import DynamicCacheControlMiddleware
from titiler.openeo.services import get_store, get_tile_store
from titiler.openeo.settings import ApiSettings, AuthSettings, BackendSettings
from titiler.openeo.stacapi import stacApiBackend

from .. import __version__ as titiler_version
from .processes import PROCESS_SPECIFICATIONS, process_registry
from .processes.implementations.io import LoadCollection

STAC_VERSION = "1.0.0"

api_settings = ApiSettings()
auth_settings = AuthSettings()

# BackendSettings requires stac_api_url and service_store_url to be set via environment variables
try:
    backend_settings = BackendSettings()
except Exception as err:
    raise ValueError(
        "Missing required environment variables for BackendSettings. "
        "Please set TITILER_OPENEO_STAC_API_URL and TITILER_OPENEO_STORE_URL"
    ) from err

stac_client = stacApiBackend(str(backend_settings.stac_api_url))  # type: ignore
service_store = get_store(str(backend_settings.store_url))
tile_store = (
    get_tile_store(backend_settings.tile_store_url)
    if backend_settings.tile_store_url
    else None
)
auth = get_auth(auth_settings, store=service_store)

###############################################################################
app = FastAPI(
    title=api_settings.name,
    openapi_url="/api",
    docs_url="/api.html",
    description="""TiTiler-EOPF backend for openEO.""",
    version=titiler_version,
    root_path=api_settings.root_path,
    debug=api_settings.debug,
)

# Set all CORS enabled origins
if api_settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=api_settings.cors_origins,
        allow_credentials=True,
        allow_methods=api_settings.cors_allow_methods,
        allow_headers=["*"],
        expose_headers=["*"],
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
    DynamicCacheControlMiddleware,
    static_paths=["/static/"],
    dynamic_paths=[
        "/processes/",
        "/jobs/",
        "/collections/",
        "/services/",
        "/results/",
    ],
)

# Register backend specific load_collection methods
loaders = LoadCollection(stac_client)  # type: ignore
process_registry["load_collection"] = process_registry["load_collection"] = Process(
    spec=PROCESS_SPECIFICATIONS["load_collection"],
    implementation=loaders.load_collection,
)

# loaders = LoadStac()  # type: ignore
# process_registry["load_stac"] = Process(
#     spec=PROCESS_SPECIFICATIONS["load_stac"],
#     implementation=loaders.load_stac,
# )

# Register OpenEO endpoints
# Create endpoints with optional tile_store
factory_args = {
    "services_store": service_store,
    "stac_client": stac_client,
    "process_registry": process_registry,
    "auth": auth,
    "default_services_file": backend_settings.default_services_file,
}
if tile_store:
    factory_args["tile_store"] = tile_store

endpoints = EndpointsFactory(
    **factory_args,
    load_nodes_ids=[
        "load_collection",
        "load_zarr",
    ],
)
app.include_router(endpoints.router)
app.endpoints = endpoints

# Create exception handler instance
exception_handler = ExceptionHandler(logger=logging.getLogger(__name__))

# Add OpenEO-specific exception handlers
app.add_exception_handler(OpenEOException, exception_handler.openeo_exception_handler)
app.add_exception_handler(
    RequestValidationError, exception_handler.validation_exception_handler
)
app.add_exception_handler(HTTPException, exception_handler.http_exception_handler)
app.add_exception_handler(Exception, exception_handler.general_exception_handler)
