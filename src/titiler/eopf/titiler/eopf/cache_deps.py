"""Cache dependency injection for titiler-eopf."""

from typing import Annotated

from fastapi import Depends

from titiler.cache import CacheKeyGenerator
from titiler.cache.backends import CacheBackend

# Global cache instances (initialized at startup)
_cache_backend: CacheBackend | None = None
_cache_key_generator: CacheKeyGenerator | None = None


def get_cache_backend() -> CacheBackend | None:
    """Get cache backend dependency.

    Returns:
        Cache backend instance or None if caching disabled
    """
    return _cache_backend


def get_cache_key_generator() -> CacheKeyGenerator | None:
    """Get cache key generator dependency.

    Returns:
        Cache key generator instance or None if caching disabled
    """
    return _cache_key_generator


def setup_cache(cache_backend: CacheBackend, key_generator: CacheKeyGenerator) -> None:
    """Setup cache dependencies.

    Args:
        cache_backend: Cache backend instance
        key_generator: Cache key generator instance
    """
    global _cache_backend, _cache_key_generator
    _cache_backend = cache_backend
    _cache_key_generator = key_generator


# Dependency injection aliases
CacheBackendDep = Annotated[CacheBackend | None, Depends(get_cache_backend)]
CacheKeyGeneratorDep = Annotated[
    CacheKeyGenerator | None, Depends(get_cache_key_generator)
]
