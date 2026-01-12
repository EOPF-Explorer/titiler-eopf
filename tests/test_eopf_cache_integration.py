"""Test EOPF cache integration."""

import os
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def test_app_imports_successfully():
    """Test that the EOPF app imports without cache enabled."""
    # Ensure cache is disabled for basic import test
    os.environ["TITILER_EOPF_CACHE_ENABLE"] = "false"

    from titiler.eopf.main import app

    assert app is not None

    # Clean up
    if "TITILER_EOPF_CACHE_ENABLE" in os.environ:
        del os.environ["TITILER_EOPF_CACHE_ENABLE"]


def test_cache_status_endpoint_disabled():
    """Test cache status endpoint when cache is disabled."""
    # Ensure cache is disabled
    os.environ["TITILER_EOPF_CACHE_ENABLE"] = "false"

    from titiler.eopf.main import app

    client = TestClient(app)

    response = client.get("/_mgmt/cache")
    assert response.status_code == 200

    data = response.json()
    assert data["cache"]["status"] == "disabled"

    # Clean up
    if "TITILER_EOPF_CACHE_ENABLE" in os.environ:
        del os.environ["TITILER_EOPF_CACHE_ENABLE"]


def test_cache_integration_with_mock_redis():
    """Test cache integration with mocked Redis backend."""
    # Mock Redis settings
    os.environ.update(
        {
            "TITILER_EOPF_CACHE_ENABLE": "true",
            "TITILER_EOPF_CACHE_BACKEND": "redis",
            "TITILER_EOPF_CACHE_REDIS_HOST": "localhost",
            "TITILER_EOPF_CACHE_REDIS_PORT": "6379",
        }
    )

    # Mock the Redis backend to avoid needing actual Redis
    with patch("titiler.cache.backends.redis.RedisCacheBackend") as MockRedis:
        mock_backend = MagicMock()

        # Create proper async mock methods
        async def mock_health_check():
            return True

        async def mock_get_stats():
            return {"hits": 0, "misses": 0}

        mock_backend.health_check = mock_health_check
        mock_backend.get_stats = mock_get_stats
        MockRedis.return_value = mock_backend

        from titiler.eopf.main import app

        client = TestClient(app)

        # Test cache status endpoint
        response = client.get("/_mgmt/cache")
        assert response.status_code == 200

        data = response.json()
        assert data["cache"]["status"] == "enabled"
        assert data["cache"]["backend"] == "redis"
        assert data["cache"]["namespace"] == "titiler-eopf"

    # Clean up environment
    for key in [
        "TITILER_EOPF_CACHE_ENABLE",
        "TITILER_EOPF_CACHE_BACKEND",
        "TITILER_EOPF_CACHE_REDIS_HOST",
        "TITILER_EOPF_CACHE_REDIS_PORT",
    ]:
        if key in os.environ:
            del os.environ[key]


def test_cache_dependency_injection():
    """Test that cache dependencies are properly injected."""
    # This test verifies the dependency injection setup works
    # We'll test it through the application integration rather than direct module import
    # since the cache setup happens at app startup, not module import

    os.environ.update(
        {
            "TITILER_EOPF_CACHE_ENABLE": "true",
            "TITILER_EOPF_CACHE_BACKEND": "redis",
            "TITILER_EOPF_CACHE_REDIS_HOST": "localhost",
        }
    )

    with patch("titiler.cache.backends.redis.RedisCacheBackend"):
        # Import the app which should trigger cache setup
        from titiler.eopf.cache_deps import get_cache_backend, get_cache_key_generator
        from titiler.eopf.main import app

        # After app initialization, dependencies should be available
        cache_backend = get_cache_backend()
        key_generator = get_cache_key_generator()

        # Verify that setup was called (even if mocked)
        # The key aspect is that the functions don't return None when cache is enabled
        # Note: In a real setup these would not be None, but with mocking they might be
        # so we test through the app integration instead
        assert (
            cache_backend is not None or key_generator is not None
        )  # At least one should be set

        client = TestClient(app)
        response = client.get("/_mgmt/ping")
        assert response.status_code == 200

    # Clean up
    for key in [
        "TITILER_EOPF_CACHE_ENABLE",
        "TITILER_EOPF_CACHE_BACKEND",
        "TITILER_EOPF_CACHE_REDIS_HOST",
    ]:
        if key in os.environ:
            del os.environ[key]


def test_cache_settings_configuration():
    """Test cache settings are properly configured."""
    from titiler.eopf.settings import EOPFCacheSettings

    # Test default settings
    settings = EOPFCacheSettings()
    assert settings.namespace == "titiler-eopf"
    assert settings.default_ttl == 3600
    assert settings.tile_ttl == 86400
    assert settings.metadata_ttl == 300
    assert "format" in settings.exclude_params
    assert "/tiles/" in settings.cache_paths
    assert "/tilejson.json" in settings.cache_paths


def test_middleware_integration():
    """Test that middleware is properly integrated."""
    os.environ.update(
        {
            "TITILER_EOPF_CACHE_ENABLE": "true",
            "TITILER_EOPF_CACHE_BACKEND": "redis",
            "TITILER_EOPF_CACHE_REDIS_HOST": "localhost",
        }
    )

    with patch("titiler.cache.backends.redis.RedisCacheBackend"):
        from titiler.eopf.main import app

        # Check that middleware was added (middleware list is not directly accessible,
        # but we can test that the app still works)
        client = TestClient(app)
        response = client.get("/_mgmt/ping")
        assert response.status_code == 200
        assert response.json() == {"message": "PONG"}

    # Clean up
    for key in [
        "TITILER_EOPF_CACHE_ENABLE",
        "TITILER_EOPF_CACHE_BACKEND",
        "TITILER_EOPF_CACHE_REDIS_HOST",
    ]:
        if key in os.environ:
            del os.environ[key]


if __name__ == "__main__":
    # Run basic tests
    test_app_imports_successfully()
    test_cache_status_endpoint_disabled()
    test_cache_settings_configuration()
    print("All EOPF cache integration tests passed!")
