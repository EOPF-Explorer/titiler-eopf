"""TiTiler Cache Extension.

A modular, Redis-referenced S3-backed tile caching system designed as a
reusable titiler extension with parameter exclusion lists, pattern matching
invalidation, and integrated health check monitoring.
"""

__version__ = "0.1.0"

from .backends.base import CacheBackend
from .settings import CacheRedisSettings, CacheS3Settings, CacheSettings

__all__ = ["CacheBackend", "CacheSettings", "CacheRedisSettings", "CacheS3Settings"]
