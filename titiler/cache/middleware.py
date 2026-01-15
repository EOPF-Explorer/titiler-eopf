"""Cache middleware for automatic tile caching."""

import logging
import time
from typing import Callable, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from .backends import CacheBackend
from .utils import CacheKeyGenerator

logger = logging.getLogger(__name__)


class TileCacheMiddleware(BaseHTTPMiddleware):
    """Middleware for automatic tile caching.

    Intercepts HTTP requests to tile endpoints and serves cached responses
    when available. Stores successful responses in the cache for future use.
    Adds X-Cache headers to indicate cache status (HIT/MISS/ERROR).
    """

    def __init__(
        self,
        app: ASGIApp,
        cache_backend: CacheBackend,
        key_generator: CacheKeyGenerator,
        cache_paths: Optional[list[str]] = None,
        cache_methods: Optional[list[str]] = None,
        default_ttl: int = 3600,
        cache_status_header: str = "X-Cache",
    ):
        """Initialize tile cache middleware.

        Args:
            app: ASGI application
            cache_backend: Cache backend implementation
            key_generator: Cache key generator
            cache_paths: URL path patterns to cache (defaults to tile endpoints)
            cache_methods: HTTP methods to cache (defaults to GET only)
            default_ttl: Default cache TTL in seconds
            cache_status_header: Header name for cache status
        """
        super().__init__(app)
        self.cache_backend = cache_backend
        self.key_generator = key_generator
        self.cache_paths = cache_paths or [
            "/tiles/",
            "/tilejson.json",
            "/preview",
            "/crop/",
            "/statistics",
            "/info.json",
        ]
        self.cache_methods = set(cache_methods or ["GET"])
        self.default_ttl = default_ttl
        self.cache_status_header = cache_status_header

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Response]
    ) -> Response:
        """Process request through cache middleware.

        Args:
            request: HTTP request
            call_next: Next middleware/endpoint handler

        Returns:
            HTTP response with cache headers
        """
        # Skip non-cacheable requests
        if not self._should_cache_request(request):
            response = await call_next(request)
            response.headers[self.cache_status_header] = "SKIP"
            return response

        # Generate cache key
        try:
            cache_type = self._determine_cache_type(request.url.path)
            cache_key = self.key_generator.from_request(request, cache_type)
        except Exception as e:
            logger.error(f"Error generating cache key: {e}")
            response = await call_next(request)
            response.headers[self.cache_status_header] = "ERROR"
            return response

        # Try to get from cache
        try:
            cached_response = await self._get_cached_response(cache_key)
            if cached_response:
                logger.debug(f"Cache HIT for key: {cache_key}")
                cached_response.headers[self.cache_status_header] = "HIT"
                return cached_response
        except Exception as e:
            logger.warning(f"Error retrieving from cache: {e}")

        # Cache miss - call next handler
        logger.debug(f"Cache MISS for key: {cache_key}")
        start_time = time.time()

        try:
            response = await call_next(request)
            process_time = time.time() - start_time

            # Cache successful responses
            if response.status_code == 200:
                try:
                    await self._cache_response(cache_key, response, process_time)
                    response.headers[self.cache_status_header] = "MISS"
                except Exception as e:
                    logger.error(f"Error caching response: {e}")
                    response.headers[self.cache_status_header] = "ERROR"
            else:
                response.headers[self.cache_status_header] = "MISS"

            return response

        except Exception as e:
            logger.error(f"Error processing request: {e}")
            # Return error response with cache status
            from starlette.responses import JSONResponse

            error_response = JSONResponse(
                {"error": "Internal server error"}, status_code=500
            )
            error_response.headers[self.cache_status_header] = "ERROR"
            return error_response

    def _should_cache_request(self, request: Request) -> bool:
        """Determine if request should be cached.

        Args:
            request: HTTP request

        Returns:
            True if request should be cached
        """
        # Check HTTP method
        if request.method not in self.cache_methods:
            return False

        # Check path patterns
        path = request.url.path
        return any(cache_path in path for cache_path in self.cache_paths)

    def _determine_cache_type(self, path: str) -> str:
        """Determine cache type from URL path.

        Args:
            path: URL path

        Returns:
            Cache type string
        """
        if "/tiles/" in path:
            return "tile"
        elif path.endswith("/tilejson.json"):
            return "tilejson"
        elif "/preview" in path:
            return "preview"
        elif "/crop/" in path:
            return "crop"
        elif "/statistics" in path:
            return "statistics"
        elif path.endswith("/info.json"):
            return "info"
        elif "/bounds" in path:
            return "bounds"
        else:
            return "unknown"

    async def _get_cached_response(self, cache_key: str) -> Optional[Response]:
        """Retrieve cached response.

        Args:
            cache_key: Cache key

        Returns:
            Cached response or None
        """
        cached_data = await self.cache_backend.get(cache_key)
        if not cached_data:
            return None

        # Deserialize cached response
        try:
            # Handle serialized JSON data
            if isinstance(cached_data, bytes):
                import json

                response_data = json.loads(cached_data.decode("utf-8"))
            else:
                response_data = cached_data

            if isinstance(response_data, dict):
                content = response_data.get("content", b"")

                # Decode base64 content if needed
                if response_data.get("content_type") == "base64":
                    import base64

                    content = base64.b64decode(content)

                # Reconstruct response
                response = Response(
                    content=content,
                    status_code=response_data.get("status_code", 200),
                    headers=response_data.get("headers", {}),
                    media_type=response_data.get("media_type"),
                )
                return response
            else:
                # Simple byte content
                return Response(content=cached_data)

        except Exception as e:
            logger.error(f"Error deserializing cached response: {e}")
            return None

    async def _cache_response(
        self, cache_key: str, response: Response, process_time: float
    ) -> None:
        """Cache response data.

        Args:
            cache_key: Cache key
            response: HTTP response
            process_time: Time taken to process request
        """
        try:
            # Read response body
            response_body = b""

            # Handle both async and sync iterators
            if hasattr(response.body_iterator, "__aiter__"):
                async for chunk in response.body_iterator:
                    response_body += chunk
            else:
                for chunk in response.body_iterator:
                    response_body += chunk

            # Replace original response body iterator with an async generator
            async def body_generator():
                yield response_body

            response.body_iterator = body_generator()

            # Convert bytes to base64 for JSON serialization
            if isinstance(response_body, bytes):
                import base64

                content_data = base64.b64encode(response_body).decode("ascii")
                content_type = "base64"
            else:
                content_data = response_body
                content_type = "text"

            # Serialize response data
            response_data = {
                "content": content_data,
                "content_type": content_type,
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "media_type": response.media_type,
                "cached_at": time.time(),
                "process_time": process_time,
            }

            # Store in cache
            import json

            serialized_data = json.dumps(response_data).encode("utf-8")
            await self.cache_backend.set(
                cache_key, serialized_data, ttl=self.default_ttl
            )

        except Exception as e:
            logger.error(f"Error caching response: {e}")
            raise


class CacheControlMiddleware(BaseHTTPMiddleware):
    """Middleware for adding cache control headers.

    Adds appropriate Cache-Control headers to responses to control
    browser and CDN caching behavior.
    """

    def __init__(
        self,
        app: ASGIApp,
        tile_max_age: int = 3600,
        metadata_max_age: int = 300,
        no_cache_paths: Optional[list[str]] = None,
    ):
        """Initialize cache control middleware.

        Args:
            app: ASGI application
            tile_max_age: Max age for tile responses (seconds)
            metadata_max_age: Max age for metadata responses (seconds)
            no_cache_paths: Paths that should not be cached by browsers
        """
        super().__init__(app)
        self.tile_max_age = tile_max_age
        self.metadata_max_age = metadata_max_age
        self.no_cache_paths = no_cache_paths or ["/health", "/metrics", "/admin/"]

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Response]
    ) -> Response:
        """Add cache control headers to response.

        Args:
            request: HTTP request
            call_next: Next middleware/endpoint handler

        Returns:
            Response with cache control headers
        """
        response = await call_next(request)

        # Skip cache headers for non-GET requests
        if request.method != "GET":
            return response

        path = request.url.path

        # No cache paths
        if any(no_cache_path in path for no_cache_path in self.no_cache_paths):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response

        # Determine appropriate cache control
        if "/tiles/" in path and response.status_code == 200:
            # Tile responses - long cache
            response.headers["Cache-Control"] = f"public, max-age={self.tile_max_age}"
        elif (
            any(endpoint in path for endpoint in ["/tilejson.json", "/info.json"])
            and response.status_code == 200
        ):
            # Metadata responses - shorter cache
            response.headers["Cache-Control"] = (
                f"public, max-age={self.metadata_max_age}"
            )
        elif response.status_code == 200:
            # Other successful responses - moderate cache
            response.headers["Cache-Control"] = (
                f"public, max-age={self.metadata_max_age}"
            )

        return response
