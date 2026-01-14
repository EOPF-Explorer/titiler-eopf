"""Function decorators for tile caching."""

import functools
import json
import logging
from typing import Any, Callable, Optional

from starlette.requests import Request
from starlette.responses import Response

from .backends import CacheBackend
from .utils import CacheKeyGenerator

logger = logging.getLogger(__name__)


def _find_request_in_args(*args, **kwargs) -> Optional[Request]:
    """Find request object in function arguments."""
    for arg in args:
        if isinstance(arg, Request):
            return arg
    return kwargs.get("request")


def _reconstruct_response_from_cache(cached_data: Any) -> Response:
    """Reconstruct HTTP response from cached data."""
    try:
        if isinstance(cached_data, bytes):
            response_data = json.loads(cached_data.decode("utf-8"))
        else:
            response_data = cached_data

        if isinstance(response_data, dict) and "content" in response_data:
            content = response_data["content"]

            # Decode base64 content if needed
            if response_data.get("content_type") == "base64":
                import base64

                content = base64.b64decode(content)

            return Response(
                content=content,
                status_code=response_data.get("status_code", 200),
                headers=response_data.get("headers", {}),
                media_type=response_data.get("media_type"),
            )
        else:
            # Simple content
            return Response(content=cached_data)
    except (json.JSONDecodeError, KeyError):
        # Fallback for non-JSON cached data
        return Response(content=cached_data)


async def _serialize_and_cache_response(
    response: Response, cache_backend: CacheBackend, cache_key: str, ttl: Optional[int]
) -> None:
    """Serialize and cache response data."""
    if not hasattr(response, "body"):
        return

    # Read body content
    body_content = response.body
    if hasattr(response, "body_iterator"):
        body_content = b""
        # Handle both async and sync iterators
        if hasattr(response.body_iterator, "__aiter__"):
            async for chunk in response.body_iterator:
                body_content += chunk
        else:
            for chunk in response.body_iterator:
                body_content += chunk

        # Reset body iterator with an async iterator
        async def body_generator():
            yield body_content

        response.body_iterator = body_generator()

    # Convert bytes to base64 for JSON serialization
    if isinstance(body_content, bytes):
        import base64

        content_data = base64.b64encode(body_content).decode("ascii")
        content_type = "base64"
    else:
        content_data = body_content
        content_type = "text"

    response_data = {
        "content": content_data,
        "content_type": content_type,
        "status_code": response.status_code,
        "headers": dict(response.headers),
        "media_type": getattr(response, "media_type", None),
    }

    # Store in cache
    serialized_data = json.dumps(response_data).encode("utf-8")
    await cache_backend.set(cache_key, serialized_data, ttl=ttl)


def _generate_cache_key(
    key_generator: CacheKeyGenerator,
    request: Request,
    cache_type: str,
    exclude_params: Optional[list[str]],
) -> str:
    """Generate cache key with temporary parameter exclusions."""
    # Temporarily add exclude_params to key generator
    original_excludes = key_generator.exclude_params.copy()
    if exclude_params:
        key_generator.exclude_params.update(exclude_params)

    try:
        cache_key = key_generator.from_request(request, cache_type)
        return cache_key
    finally:
        # Restore original excludes
        key_generator.exclude_params = original_excludes


async def _handle_cache_miss(
    func: Callable,
    cache_backend: CacheBackend,
    cache_key: str,
    ttl: Optional[int],
    *args,
    **kwargs,
) -> Response:
    """Handle cache miss by calling original function and caching response."""
    logger.debug(f"Cache MISS for {func.__name__}: {cache_key}")

    response = await func(*args, **kwargs)

    # Cache successful responses
    if hasattr(response, "status_code") and response.status_code == 200:
        try:
            await _serialize_and_cache_response(response, cache_backend, cache_key, ttl)
            response.headers["X-Cache"] = "MISS"
        except Exception as e:
            logger.error(f"Error caching response in {func.__name__}: {e}")
            response.headers["X-Cache"] = "ERROR"
    else:
        # Non-200 response
        if hasattr(response, "headers"):
            response.headers["X-Cache"] = "SKIP"

    return response


def cached_tile(
    cache_backend: CacheBackend,
    key_generator: CacheKeyGenerator,
    cache_type: str = "tile",
    ttl: Optional[int] = None,
    exclude_params: Optional[list[str]] = None,
) -> Callable:
    """Decorator for caching tile endpoint responses.

    Provides function-level caching for tile endpoints with configurable
    cache types, TTL values, and parameter exclusion.

    Args:
        cache_backend: Cache backend implementation
        key_generator: Cache key generator
        cache_type: Type of cache (e.g., "tile", "tilejson", "preview")
        ttl: Cache TTL in seconds (uses backend default if None)
        exclude_params: Additional parameters to exclude from cache key

    Returns:
        Decorated function with caching behavior

    Example:
        @cached_tile(cache_backend, key_generator, "tile", ttl=3600)
        async def get_tile(request: Request, z: int, x: int, y: int):
            # Generate tile
            return tile_response
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Response:
            # Find request object in args/kwargs
            request = _find_request_in_args(*args, **kwargs)
            if not request:
                logger.warning(
                    f"No request object found in {func.__name__}, skipping cache"
                )
                return await func(*args, **kwargs)

            # Generate cache key
            try:
                cache_key = _generate_cache_key(
                    key_generator, request, cache_type, exclude_params
                )
            except Exception as e:
                logger.error(f"Error generating cache key in {func.__name__}: {e}")
                response = await func(*args, **kwargs)
                if hasattr(response, "headers"):
                    response.headers["X-Cache"] = "ERROR"
                return response

            # Try to get from cache
            try:
                cached_data = await cache_backend.get(cache_key)
                if cached_data:
                    logger.debug(f"Cache HIT for {func.__name__}: {cache_key}")
                    response = _reconstruct_response_from_cache(cached_data)
                    response.headers["X-Cache"] = "HIT"
                    return response
            except Exception as e:
                logger.warning(f"Error retrieving from cache in {func.__name__}: {e}")

            # Cache miss - handle miss and caching
            try:
                return await _handle_cache_miss(
                    func, cache_backend, cache_key, ttl, *args, **kwargs
                )
            except Exception as e:
                logger.error(f"Error in cached function {func.__name__}: {e}")
                raise

        return wrapper

    return decorator


def cached_metadata(
    cache_backend: CacheBackend,
    key_generator: CacheKeyGenerator,
    cache_type: str = "metadata",
    ttl: Optional[int] = None,
) -> Callable:
    """Decorator for caching metadata endpoint responses.

    Specialized decorator for metadata endpoints like tilejson, info, etc.
    with appropriate cache settings and headers.

    Args:
        cache_backend: Cache backend implementation
        key_generator: Cache key generator
        cache_type: Type of cache (e.g., "tilejson", "info", "statistics")
        ttl: Cache TTL in seconds (uses backend default if None)

    Returns:
        Decorated function with metadata caching behavior
    """
    return cached_tile(
        cache_backend=cache_backend,
        key_generator=key_generator,
        cache_type=cache_type,
        ttl=ttl or 300,  # Default 5 minutes for metadata
        exclude_params=["callback", "format"],  # Common metadata params to exclude
    )


def cache_control(
    max_age: int = 3600, public: bool = True, immutable: bool = False
) -> Callable:
    """Decorator for adding Cache-Control headers to responses.

    Simple decorator to add browser/CDN cache control headers
    without backend caching.

    Args:
        max_age: Cache max age in seconds
        public: Whether cache can be shared (public vs private)
        immutable: Whether content is immutable

    Returns:
        Decorated function with cache control headers
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Response:
            response = await func(*args, **kwargs)

            if hasattr(response, "headers") and hasattr(response, "status_code"):
                if response.status_code == 200:
                    cache_directives = []

                    if public:
                        cache_directives.append("public")
                    else:
                        cache_directives.append("private")

                    cache_directives.append(f"max-age={max_age}")

                    if immutable:
                        cache_directives.append("immutable")

                    response.headers["Cache-Control"] = ", ".join(cache_directives)

            return response

        return wrapper

    return decorator


class CacheManager:
    """Context manager for cache operations in endpoints.

    Provides a convenient way to handle cache operations with
    proper error handling and logging.
    """

    def __init__(
        self,
        cache_backend: CacheBackend,
        key_generator: CacheKeyGenerator,
        request: Request,
        cache_type: str = "tile",
        ttl: Optional[int] = None,
    ):
        """Initialize cache manager.

        Args:
            cache_backend: Cache backend implementation
            key_generator: Cache key generator
            request: HTTP request
            cache_type: Type of cache
            ttl: Cache TTL in seconds
        """
        self.cache_backend = cache_backend
        self.key_generator = key_generator
        self.request = request
        self.cache_type = cache_type
        self.ttl = ttl
        self.cache_key = None

    async def __aenter__(self):
        """Enter cache context."""
        try:
            self.cache_key = self.key_generator.from_request(
                self.request, self.cache_type
            )

            # Try to get from cache
            cached_data = await self.cache_backend.get(self.cache_key)
            if cached_data:
                return {"hit": True, "data": cached_data}
            else:
                return {"hit": False, "data": None}

        except Exception as e:
            logger.error(f"Error in cache manager enter: {e}")
            return {"hit": False, "data": None, "error": str(e)}

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit cache context."""
        # Nothing to clean up
        pass

    async def store(self, data: Any) -> bool:
        """Store data in cache.

        Args:
            data: Data to store

        Returns:
            True if stored successfully
        """
        try:
            if self.cache_key:
                await self.cache_backend.set(self.cache_key, data, ttl=self.ttl)
                return True
        except Exception as e:
            logger.error(f"Error storing in cache: {e}")
        return False
