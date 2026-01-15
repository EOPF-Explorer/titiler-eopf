"""Datatree cache helpers for sync/async compatibility."""

import logging
import pickle
from typing import Any, Callable, Optional

from .backends.base import CacheBackend
from .utils.keys import CacheKeyGenerator

logger = logging.getLogger(__name__)


def get_cached_datatree(
    src_path: str,
    loader_func: Callable[[str], Any],
    cache_backend: Optional[CacheBackend] = None,
    key_generator: Optional[CacheKeyGenerator] = None,
    ttl: int = 300,
) -> Any:
    """Get datatree from cache or load and cache it.

    Args:
        src_path: Source path for the dataset
        loader_func: Function to load the datatree if not cached
        cache_backend: Cache backend instance
        key_generator: Cache key generator instance
        ttl: Cache TTL in seconds

    Returns:
        Loaded datatree
    """
    if not cache_backend or not key_generator:
        logger.info("No cache backend available, loading datatree directly")
        return loader_func(src_path)

    # Generate structured cache key
    cache_key = key_generator.from_path_and_params(
        path=src_path,
        cache_type="datatree",
    )

    # Try to get from cache using sync Redis access
    cache_client = _get_redis_client(cache_backend)
    if not cache_client:
        logger.info("No Redis client available, loading datatree directly")
        return loader_func(src_path)

    # Check cache
    try:
        if data_bytes := cache_client.get(cache_key):
            logger.info(f"Cache HIT - found datatree: {cache_key}")
            return pickle.loads(data_bytes)
    except Exception as e:
        logger.warning(f"Cache read error, loading directly: {e}")
        return loader_func(src_path)

    # Cache miss - load and store
    logger.info(f"Cache MISS - loading datatree: {cache_key}")
    datatree = loader_func(src_path)

    try:
        cache_client.set(cache_key, pickle.dumps(datatree), ex=ttl)
        logger.info(f"Cache STORE - datatree cached: {cache_key}")
    except Exception as e:
        logger.warning(f"Cache store error: {e}")

    return datatree


def _get_redis_client(cache_backend: CacheBackend):
    """Get Redis client from cache backend."""
    # For Redis backend
    if hasattr(cache_backend, "_redis_client"):
        return cache_backend._redis_client

    # For S3+Redis backend
    if hasattr(cache_backend, "redis_backend") and hasattr(
        cache_backend.redis_backend, "_redis_client"
    ):
        return cache_backend.redis_backend._redis_client

    return None


def invalidate_datatree_cache(
    src_path: str,
    cache_backend: Optional[CacheBackend] = None,
    key_generator: Optional[CacheKeyGenerator] = None,
) -> bool:
    """Invalidate cached datatree for a source path.

    Args:
        src_path: Source path for the dataset
        cache_backend: Cache backend instance
        key_generator: Cache key generator instance

    Returns:
        True if invalidation succeeded
    """
    if not cache_backend or not key_generator:
        return False

    try:
        cache_key = key_generator.from_path_and_params(
            path=src_path,
            cache_type="datatree",
        )

        cache_client = _get_redis_client(cache_backend)
        if cache_client:
            result = cache_client.delete(cache_key)
            logger.info(f"Invalidated datatree cache: {cache_key} (deleted: {result})")
            return bool(result)

    except Exception as e:
        logger.error(f"Failed to invalidate datatree cache for {src_path}: {e}")

    return False
