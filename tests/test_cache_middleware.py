"""Tests for cache middleware."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.testclient import TestClient

from titiler.cache.middleware import CacheControlMiddleware, TileCacheMiddleware
from titiler.cache.utils import CacheKeyGenerator


class MockCacheBackend:
    """Mock cache backend for testing."""

    def __init__(self):
        """Initialize mock cache backend."""
        self.storage = {}
        self.get_calls = []
        self.set_calls = []

    async def get(self, key: str):
        """Get value from mock storage."""
        self.get_calls.append(key)
        return self.storage.get(key)

    async def set(self, key: str, value, ttl=None):
        """Set value in mock storage."""
        self.set_calls.append((key, value, ttl))
        self.storage[key] = value

    async def delete(self, key: str):
        """Delete value from mock storage."""
        self.storage.pop(key, None)

    async def exists(self, key: str):
        """Check if key exists in mock storage."""
        return key in self.storage

    async def clear_pattern(self, pattern: str):
        """Clear pattern - no-op for mock."""
        pass


class TestTileCacheMiddleware:
    """Test tile cache middleware functionality."""

    def test_middleware_initialization(self):
        """Test middleware initialization with various parameters."""
        cache_backend = MockCacheBackend()
        key_generator = CacheKeyGenerator("test-app")

        # Default initialization
        middleware = TileCacheMiddleware(
            app=None, cache_backend=cache_backend, key_generator=key_generator
        )

        assert middleware.cache_backend == cache_backend
        assert middleware.key_generator == key_generator
        assert "/tiles/" in middleware.cache_paths
        assert "GET" in middleware.cache_methods
        assert middleware.default_ttl == 3600
        assert middleware.cache_status_header == "X-Cache"

        # Custom initialization
        middleware = TileCacheMiddleware(
            app=None,
            cache_backend=cache_backend,
            key_generator=key_generator,
            cache_paths=["/custom/tiles/"],
            cache_methods=["GET", "POST"],
            default_ttl=7200,
            cache_status_header="X-Custom-Cache",
        )

        assert middleware.cache_paths == ["/custom/tiles/"]
        assert middleware.cache_methods == {"GET", "POST"}
        assert middleware.default_ttl == 7200
        assert middleware.cache_status_header == "X-Custom-Cache"

    def test_should_cache_request(self):
        """Test request caching logic."""
        cache_backend = MockCacheBackend()
        key_generator = CacheKeyGenerator("test-app")
        middleware = TileCacheMiddleware(
            app=None, cache_backend=cache_backend, key_generator=key_generator
        )

        # Mock request objects
        class MockRequest:
            def __init__(self, method, path):
                self.method = method
                self.url = MagicMock()
                self.url.path = path

        # Should cache GET requests to tile paths
        assert middleware._should_cache_request(
            MockRequest("GET", "/tiles/10/512/384.png")
        )
        assert middleware._should_cache_request(MockRequest("GET", "/tilejson.json"))
        assert middleware._should_cache_request(MockRequest("GET", "/preview"))

        # Should not cache POST requests
        assert not middleware._should_cache_request(
            MockRequest("POST", "/tiles/10/512/384.png")
        )

        # Should not cache non-tile paths
        assert not middleware._should_cache_request(MockRequest("GET", "/health"))
        assert not middleware._should_cache_request(MockRequest("GET", "/admin/"))

    def test_determine_cache_type(self):
        """Test cache type determination from paths."""
        cache_backend = MockCacheBackend()
        key_generator = CacheKeyGenerator("test-app")
        middleware = TileCacheMiddleware(
            app=None, cache_backend=cache_backend, key_generator=key_generator
        )

        assert middleware._determine_cache_type("/tiles/10/512/384.png") == "tile"
        assert middleware._determine_cache_type("/tilejson.json") == "tilejson"
        assert middleware._determine_cache_type("/preview") == "preview"
        assert middleware._determine_cache_type("/crop/bbox") == "crop"
        assert middleware._determine_cache_type("/statistics") == "statistics"
        assert middleware._determine_cache_type("/info.json") == "info"
        assert middleware._determine_cache_type("/unknown/path") == "unknown"

    @pytest.mark.asyncio
    async def test_cache_hit_flow(self):
        """Test middleware behavior on cache hit."""
        cache_backend = MockCacheBackend()
        key_generator = CacheKeyGenerator("test-app")

        # Pre-populate cache with proper base64 encoded content
        import base64

        tile_data = b"cached tile data"
        cached_response_data = {
            "content": base64.b64encode(tile_data).decode("ascii"),
            "content_type": "base64",
            "status_code": 200,
            "headers": {"Content-Type": "image/png"},
            "media_type": "image/png",
        }

        # Mock request for key generation
        class MockRequest:
            def __init__(self):
                self.method = "GET"
                self.url = MagicMock()
                self.url.path = "/tiles/10/512/384.png"
                self.query_params = {}

        # Generate the actual cache key that would be used
        test_request = MockRequest()
        expected_key = key_generator.from_request(test_request, "tile")
        cache_backend.storage[expected_key] = cached_response_data

        middleware = TileCacheMiddleware(
            app=None, cache_backend=cache_backend, key_generator=key_generator
        )

        request = MockRequest()

        # Mock call_next (should not be called on cache hit)
        call_next = AsyncMock()

        # Process request
        response = await middleware.dispatch(request, call_next)

        # Verify cache hit
        assert (
            response is not None
        ), f"Response is None, cache keys: {list(cache_backend.storage.keys())}"
        assert hasattr(
            response, "headers"
        ), f"Response doesn't have headers: {response}"
        assert response.headers["X-Cache"] == "HIT"
        assert response.status_code == 200
        assert response.body == tile_data  # Check content is properly decoded
        call_next.assert_not_called()  # Should not call next handler on cache hit

    @pytest.mark.asyncio
    async def test_cache_miss_flow(self):
        """Test middleware behavior on cache miss."""
        cache_backend = MockCacheBackend()
        key_generator = CacheKeyGenerator("test-app")

        middleware = TileCacheMiddleware(
            app=None, cache_backend=cache_backend, key_generator=key_generator
        )

        # Mock request
        class MockRequest:
            def __init__(self):
                self.method = "GET"
                self.url = MagicMock()
                self.url.path = "/tiles/10/512/384.png"
                self.query_params = {}

        request = MockRequest()

        # Mock successful response
        mock_response = Response(
            content=b"generated tile data",
            status_code=200,
            headers={"Content-Type": "image/png"},
            media_type="image/png",
        )
        mock_response.body_iterator = iter([b"generated tile data"])

        # Mock call_next
        call_next = AsyncMock(return_value=mock_response)

        # Process request
        response = await middleware.dispatch(request, call_next)

        # Verify cache miss and caching
        assert response.headers["X-Cache"] == "MISS"
        assert response.status_code == 200
        call_next.assert_called_once()

        # Verify data was cached
        assert len(cache_backend.set_calls) == 1


class TestCacheControlMiddleware:
    """Test cache control middleware functionality."""

    def test_middleware_initialization(self):
        """Test cache control middleware initialization."""
        middleware = CacheControlMiddleware(
            app=None,
            tile_max_age=7200,
            metadata_max_age=600,
            no_cache_paths=["/admin/", "/health"],
        )

        assert middleware.tile_max_age == 7200
        assert middleware.metadata_max_age == 600
        assert "/admin/" in middleware.no_cache_paths
        assert "/health" in middleware.no_cache_paths

    @pytest.mark.asyncio
    async def test_cache_control_headers(self):
        """Test addition of cache control headers."""
        middleware = CacheControlMiddleware(
            app=None, tile_max_age=3600, metadata_max_age=300
        )

        # Mock request and response
        class MockRequest:
            def __init__(self, method, path):
                self.method = method
                self.url = MagicMock()
                self.url.path = path

        # Test tile response
        request = MockRequest("GET", "/tiles/10/512/384.png")
        mock_response = Response(content=b"tile", status_code=200)
        call_next = AsyncMock(return_value=mock_response)

        response = await middleware.dispatch(request, call_next)

        assert "Cache-Control" in response.headers
        assert "max-age=3600" in response.headers["Cache-Control"]
        assert "public" in response.headers["Cache-Control"]

        # Test metadata response
        request = MockRequest("GET", "/tilejson.json")
        mock_response = Response(content=b'{"name":"test"}', status_code=200)
        call_next = AsyncMock(return_value=mock_response)

        response = await middleware.dispatch(request, call_next)

        assert "Cache-Control" in response.headers
        assert "max-age=300" in response.headers["Cache-Control"]

        # Test no-cache path
        request = MockRequest("GET", "/health")
        mock_response = Response(content=b"ok", status_code=200)
        call_next = AsyncMock(return_value=mock_response)

        response = await middleware.dispatch(request, call_next)

        assert "Cache-Control" in response.headers
        assert "no-cache" in response.headers["Cache-Control"]
        assert "Pragma" in response.headers
        assert "Expires" in response.headers


class TestMiddlewareIntegration:
    """Test middleware integration with Starlette/FastAPI applications."""

    def test_middleware_integration(self):
        """Test middleware integration with real application."""
        cache_backend = MockCacheBackend()
        key_generator = CacheKeyGenerator("test-app")

        # Create test application
        app = Starlette()

        # Add middleware
        app.add_middleware(
            TileCacheMiddleware,
            cache_backend=cache_backend,
            key_generator=key_generator,
        )
        app.add_middleware(CacheControlMiddleware)

        # Add test route
        @app.route("/tiles/{z}/{x}/{y}")
        async def get_tile(request):
            return Response(content=b"test tile", media_type="image/png")

        # Test with client
        client = TestClient(app)

        # First request should miss cache
        response1 = client.get("/tiles/10/512/384")
        assert response1.status_code == 200
        assert response1.headers.get("X-Cache") in [
            "MISS",
            "SKIP",
        ]  # Depends on implementation
        assert "Cache-Control" in response1.headers

        # Note: TestClient doesn't preserve async behavior needed for proper cache testing
        # In real usage, the second request would hit the cache
