"""Cache management API endpoints for administrative operations."""

import logging
import secrets
import time
from typing import Annotated, List, Optional

from fastapi import APIRouter, HTTPException, Response, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, SecretStr, StringConstraints

from titiler.cache.backends.base import CacheBackend
from titiler.cache.utils import CacheKeyGenerator

logger = logging.getLogger(__name__)

MIN_TOKEN_LENGTH = 16


class InvalidateRequest(BaseModel):
    """Request model for cache invalidation."""

    patterns: List[Annotated[str, StringConstraints(min_length=1, max_length=256)]] = (
        Field(
            min_length=1,
            max_length=100,
            description="Cache key patterns to invalidate",
        )
    )


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


def _create_status_endpoint(
    cache_backend: CacheBackend, key_generator: CacheKeyGenerator
):
    """Create cache status endpoint."""

    async def get_cache_status():
        """Get cache status and statistics."""
        try:
            backend_stats = await cache_backend.get_stats()
            return CacheStats(
                backend_type=type(cache_backend)
                .__name__.replace("Backend", "")
                .lower(),
                namespace=key_generator.namespace,
                total_keys=backend_stats.get("total_keys"),
                cache_size_bytes=backend_stats.get("cache_size_bytes"),
                hit_rate=backend_stats.get("hit_rate"),
                uptime_seconds=backend_stats.get("uptime_seconds"),
            )
        except Exception as e:
            logger.error(f"Error getting cache status: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error retrieving cache status",
            ) from e

    return get_cache_status


def _create_invalidate_endpoint(cache_backend: CacheBackend, namespace: str):
    """Create cache invalidation endpoint.

    Every pattern is confined to `namespace`: a pattern that does not already
    start with `<namespace>:` gets that prefix, so `*` means "this app's keys",
    never the whole Redis DB or S3 bucket.
    """
    ns = f"{namespace}:"

    async def invalidate_cache(request: InvalidateRequest):
        """Invalidate cache entries by patterns."""
        start_time = time.time()
        invalidated_count = 0
        failed_patterns = []

        # clear_pattern swallows backend errors and returns 0, so check the
        # backend is reachable first instead of reporting a silent success.
        health = await cache_backend.health_check()
        if health.get("status") != "connected":
            logger.error("Cache invalidation skipped: backend unhealthy")
            failed_patterns = list(request.patterns)
        else:
            for pattern in request.patterns:
                scoped = pattern if pattern.startswith(ns) else ns + pattern
                try:
                    invalidated_count += await cache_backend.clear_pattern(scoped)
                except Exception as e:
                    failed_patterns.append(pattern)
                    logger.error(f"Failed to invalidate pattern {scoped}: {e}")

        return InvalidateResponse(
            success=not failed_patterns,
            invalidated_count=invalidated_count,
            failed_patterns=failed_patterns,
            execution_time_ms=(time.time() - start_time) * 1000,
        )

    return invalidate_cache


def create_cache_admin_router(
    cache_backend: CacheBackend,
    key_generator: CacheKeyGenerator,
    token: SecretStr,
    prefix: str = "/admin/cache",
) -> APIRouter:
    """Create cache administration router.

    Every route requires `Authorization: Bearer <token>` and answers with
    `Cache-Control: no-store`. The router is left out of the OpenAPI schema.

    Args:
        cache_backend: Cache backend instance
        key_generator: Cache key generator instance
        token: Bearer token every request must present
        prefix: Path prefix the routes are mounted under

    Returns:
        FastAPI router with cache management endpoints

    Raises:
        ValueError: if the token or prefix is unusable, so the router can never
            be built open, nor crash the app at import.
    """
    expected = token.get_secret_value().strip()
    if len(expected) < MIN_TOKEN_LENGTH or not expected.isascii():
        raise ValueError(
            f"admin token must be at least {MIN_TOKEN_LENGTH} ASCII characters "
            "(surrounding whitespace is ignored)"
        )
    if not prefix.startswith("/") or prefix.endswith("/"):
        raise ValueError(
            f"admin prefix {prefix!r} must start with '/', must not end with '/' "
            "and must not be '/'"
        )
    expected_bytes = expected.encode()

    async def verify_token(
        response: Response,
        credentials: Annotated[
            Optional[HTTPAuthorizationCredentials],
            Security(HTTPBearer(auto_error=False)),
        ],
    ) -> None:
        """Reject requests without the expected bearer token."""
        if credentials is None or not secrets.compare_digest(
            credentials.credentials.encode(), expected_bytes
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing bearer token",
                headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
            )
        response.headers["Cache-Control"] = "no-store"

    router = APIRouter(
        prefix=prefix,
        tags=["Cache Administration"],
        dependencies=[Security(verify_token)],
        include_in_schema=False,
    )

    router.add_api_route(
        "/status",
        _create_status_endpoint(cache_backend, key_generator),
        methods=["GET"],
        response_model=CacheStats,
    )

    router.add_api_route(
        "/invalidate",
        _create_invalidate_endpoint(cache_backend, key_generator.namespace),
        methods=["POST"],
        response_model=InvalidateResponse,
    )

    return router
