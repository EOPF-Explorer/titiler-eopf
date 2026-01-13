"""Cache management API endpoints for administrative operations."""

import logging
import time
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from titiler.cache.backends.base import CacheBackend
from titiler.cache.utils import CacheKeyGenerator

logger = logging.getLogger(__name__)


class InvalidateRequest(BaseModel):
    """Request model for cache invalidation."""

    patterns: List[str] = Field(description="Cache key patterns to invalidate")


class InvalidateResponse(BaseModel):
    """Response model for cache invalidation."""

    success: bool = Field(description="Whether invalidation was successful")
    invalidated_count: int = Field(description="Number of cache keys invalidated")
    failed_patterns: List[str] = Field(description="Patterns that failed to invalidate")
    execution_time_ms: float = Field(description="Execution time in milliseconds")


class CacheStats(BaseModel):
    """Cache statistics model."""

    backend_type: str = Field(description="Type of cache backend")
    namespace: str = Field(description="Cache namespace")
    total_keys: Optional[int] = Field(description="Total number of keys", default=None)
    cache_size_bytes: Optional[int] = Field(
        description="Total cache size", default=None
    )
    hit_rate: Optional[float] = Field(description="Cache hit rate", default=None)
    uptime_seconds: Optional[int] = Field(description="Backend uptime", default=None)


class CacheKey(BaseModel):
    """Cache key information model."""

    key: str = Field(description="Full cache key")
    cache_type: str = Field(description="Type of cached content (tile, tilejson, etc.)")
    created_at: Optional[str] = Field(
        description="ISO timestamp when key was created", default=None
    )
    ttl_seconds: Optional[int] = Field(
        description="Time to live in seconds", default=None
    )
    size_bytes: Optional[int] = Field(
        description="Size of cached data in bytes", default=None
    )


def _create_status_endpoint(
    cache_backend: CacheBackend, key_generator: CacheKeyGenerator
):
    """Create cache status endpoint."""

    async def get_cache_status():
        """Get cache status and statistics."""
        try:
            stats = CacheStats(
                backend_type=type(cache_backend)
                .__name__.replace("Backend", "")
                .lower(),
                namespace=key_generator.namespace,
            )

            if hasattr(cache_backend, "get_stats"):
                backend_stats = await cache_backend.get_stats()
                if isinstance(backend_stats, dict):
                    stats.total_keys = backend_stats.get("total_keys")
                    stats.cache_size_bytes = backend_stats.get("cache_size_bytes")
                    stats.hit_rate = backend_stats.get("hit_rate")
                    stats.uptime_seconds = backend_stats.get("uptime_seconds")

            return stats

        except Exception as e:
            logger.error(f"Error getting cache status: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error retrieving cache status: {str(e)}",
            ) from e

    return get_cache_status


def _create_invalidate_endpoint(cache_backend: CacheBackend):
    """Create cache invalidation endpoint."""

    async def invalidate_cache(request: InvalidateRequest):
        """Invalidate cache entries by patterns."""
        try:
            start_time = time.time()
            invalidated_count = 0
            failed_patterns = []

            for pattern in request.patterns:
                try:
                    if hasattr(cache_backend, "delete_pattern"):
                        count = await cache_backend.delete_pattern(pattern)
                        invalidated_count += count
                    elif hasattr(cache_backend, "clear_pattern"):
                        count = await cache_backend.clear_pattern(pattern)
                        invalidated_count += count
                    elif hasattr(cache_backend, "scan_keys"):
                        keys = await cache_backend.scan_keys(pattern)
                        for key in keys:
                            try:
                                await cache_backend.delete(key)
                                invalidated_count += 1
                            except Exception:
                                pass
                    else:
                        failed_patterns.append(pattern)
                        logger.warning(f"Pattern deletion not supported for: {pattern}")
                except Exception as e:
                    failed_patterns.append(pattern)
                    logger.error(f"Failed to invalidate pattern {pattern}: {e}")

            execution_time = (time.time() - start_time) * 1000

            return InvalidateResponse(
                success=len(failed_patterns) == 0,
                invalidated_count=invalidated_count,
                failed_patterns=failed_patterns,
                execution_time_ms=execution_time,
            )

        except Exception as e:
            logger.error(f"Error invalidating cache: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error invalidating cache: {str(e)}",
            ) from e

    return invalidate_cache


def create_cache_admin_router(
    cache_backend: Optional[CacheBackend] = None,
    key_generator: Optional[CacheKeyGenerator] = None,
    require_auth: bool = False,
) -> APIRouter:
    """Create cache administration router.

    Args:
        cache_backend: Cache backend instance
        key_generator: Cache key generator instance
        require_auth: Whether to require authentication (set False for development)

    Returns:
        FastAPI router with cache management endpoints
    """
    router = APIRouter(prefix="/admin/cache", tags=["Cache Administration"])

    if not cache_backend or not key_generator:
        # Return empty router if dependencies not available
        @router.get("/status")
        async def unavailable():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Cache backend not available",
            )

        return router

    # Add endpoints
    router.add_api_route(
        "/status",
        _create_status_endpoint(cache_backend, key_generator),
        methods=["GET"],
        response_model=CacheStats,
    )

    router.add_api_route(
        "/invalidate",
        _create_invalidate_endpoint(cache_backend),
        methods=["POST"],
        response_model=InvalidateResponse,
    )

    return router
