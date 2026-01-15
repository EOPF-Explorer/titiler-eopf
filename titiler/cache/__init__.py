"""TiTiler Cache Extension.

A modular, Redis-referenced S3-backed tile caching system designed as a
reusable titiler extension with parameter exclusion lists, pattern matching
invalidation, and integrated health check monitoring.
"""

__version__ = "0.1.0"

from .admin import create_cache_admin_router
from .backends.base import CacheBackend
from .decorators import CacheManager, cache_control, cached_metadata, cached_tile
from .middleware import CacheControlMiddleware, TileCacheMiddleware
from .settings import CacheRedisSettings, CacheS3Settings, CacheSettings
from .utils import CacheKeyGenerator

__all__ = [
    "CacheBackend",
    "CacheSettings",
    "CacheRedisSettings",
    "CacheS3Settings",
    "TileCacheMiddleware",
    "CacheControlMiddleware",
    "CacheKeyGenerator",
    "cached_tile",
    "cached_metadata",
    "cache_control",
    "CacheManager",
    "create_cache_admin_router",
]
