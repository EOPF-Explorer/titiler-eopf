"""Tests for datatree cache helpers."""

from unittest.mock import Mock, patch

from titiler.cache.datatree_helpers import (
    _get_redis_client,
    get_cached_datatree,
    invalidate_datatree_cache,
)


class TestDatatreeCacheHelpers:
    """Test datatree cache helper functions."""

    def test_get_cached_datatree_no_cache_backend(self):
        """Test get_cached_datatree when no cache backend is available."""
        mock_loader = Mock(return_value="test_datatree")

        result = get_cached_datatree(
            src_path="s3://bucket/test.zarr",
            loader_func=mock_loader,
            cache_backend=None,
            key_generator=None,
        )

        assert result == "test_datatree"
        mock_loader.assert_called_once_with("s3://bucket/test.zarr")

    def test_get_cached_datatree_no_redis_client(self):
        """Test get_cached_datatree when Redis client is not available."""
        mock_cache_backend = Mock()
        mock_key_generator = Mock()
        mock_loader = Mock(return_value="test_datatree")

        # Mock that no Redis client is available
        with patch(
            "titiler.cache.datatree_helpers._get_redis_client", return_value=None
        ):
            result = get_cached_datatree(
                src_path="s3://bucket/test.zarr",
                loader_func=mock_loader,
                cache_backend=mock_cache_backend,
                key_generator=mock_key_generator,
            )

        assert result == "test_datatree"
        mock_loader.assert_called_once_with("s3://bucket/test.zarr")

    def test_get_cached_datatree_cache_hit(self):
        """Test get_cached_datatree with cache hit."""
        import pickle

        mock_cache_backend = Mock()
        mock_key_generator = Mock()
        mock_key_generator.from_path_and_params.return_value = (
            "test:datatree:s3:bucket:test:noparams"
        )

        mock_redis_client = Mock()
        cached_data = pickle.dumps("cached_datatree")
        mock_redis_client.get.return_value = cached_data

        mock_loader = Mock()  # Should not be called

        with patch(
            "titiler.cache.datatree_helpers._get_redis_client",
            return_value=mock_redis_client,
        ):
            result = get_cached_datatree(
                src_path="s3://bucket/test.zarr",
                loader_func=mock_loader,
                cache_backend=mock_cache_backend,
                key_generator=mock_key_generator,
            )

        assert result == "cached_datatree"
        mock_redis_client.get.assert_called_once_with(
            "test:datatree:s3:bucket:test:noparams"
        )
        mock_loader.assert_not_called()

    def test_get_cached_datatree_cache_miss(self):
        """Test get_cached_datatree with cache miss."""
        mock_cache_backend = Mock()
        mock_key_generator = Mock()
        mock_key_generator.from_path_and_params.return_value = (
            "test:datatree:s3:bucket:test:noparams"
        )

        mock_redis_client = Mock()
        mock_redis_client.get.return_value = None  # Cache miss

        mock_loader = Mock(return_value="new_datatree")

        with patch(
            "titiler.cache.datatree_helpers._get_redis_client",
            return_value=mock_redis_client,
        ):
            result = get_cached_datatree(
                src_path="s3://bucket/test.zarr",
                loader_func=mock_loader,
                cache_backend=mock_cache_backend,
                key_generator=mock_key_generator,
                ttl=300,
            )

        assert result == "new_datatree"
        mock_redis_client.get.assert_called_once_with(
            "test:datatree:s3:bucket:test:noparams"
        )
        mock_redis_client.set.assert_called_once()
        mock_loader.assert_called_once_with("s3://bucket/test.zarr")

    def test_get_redis_client_redis_backend(self):
        """Test _get_redis_client with Redis backend."""
        mock_cache_backend = Mock()
        mock_redis_client = Mock()
        mock_cache_backend._redis_client = mock_redis_client

        result = _get_redis_client(mock_cache_backend)
        assert result == mock_redis_client

    def test_get_redis_client_s3_redis_backend(self):
        """Test _get_redis_client with S3+Redis backend."""
        mock_cache_backend = Mock()
        mock_redis_backend = Mock()
        mock_redis_client = Mock()
        mock_redis_backend._redis_client = mock_redis_client
        mock_cache_backend.redis_backend = mock_redis_backend

        # Remove _redis_client attribute to force S3+Redis path
        del mock_cache_backend._redis_client

        result = _get_redis_client(mock_cache_backend)
        assert result == mock_redis_client

    def test_get_redis_client_no_redis(self):
        """Test _get_redis_client when no Redis client available."""
        mock_cache_backend = Mock()
        # Remove attributes to simulate no Redis client
        del mock_cache_backend._redis_client
        del mock_cache_backend.redis_backend

        result = _get_redis_client(mock_cache_backend)
        assert result is None

    def test_invalidate_datatree_cache_success(self):
        """Test successful datatree cache invalidation."""
        mock_cache_backend = Mock()
        mock_key_generator = Mock()
        mock_key_generator.from_path_and_params.return_value = (
            "test:datatree:s3:bucket:test:noparams"
        )

        mock_redis_client = Mock()
        mock_redis_client.delete.return_value = 1  # Successfully deleted 1 key

        with patch(
            "titiler.cache.datatree_helpers._get_redis_client",
            return_value=mock_redis_client,
        ):
            result = invalidate_datatree_cache(
                src_path="s3://bucket/test.zarr",
                cache_backend=mock_cache_backend,
                key_generator=mock_key_generator,
            )

        assert result is True
        mock_redis_client.delete.assert_called_once_with(
            "test:datatree:s3:bucket:test:noparams"
        )

    def test_invalidate_datatree_cache_no_backend(self):
        """Test datatree cache invalidation with no backend."""
        result = invalidate_datatree_cache(
            src_path="s3://bucket/test.zarr", cache_backend=None, key_generator=None
        )

        assert result is False


class TestDatatreePatterns:
    """Test datatree cache pattern generation."""

    def test_datatree_pattern_s3_url(self):
        """Test pattern generation for S3 URLs."""
        from titiler.cache.utils import CacheKeyGenerator

        generator = CacheKeyGenerator("test-app")

        # Test S3 URL
        pattern = generator.get_pattern_for_datatree("s3://bucket/path/to/file.zarr")
        assert pattern == "test-app:datatree:s3:bucket:path:to:*"

    def test_datatree_pattern_http_url(self):
        """Test pattern generation for HTTP URLs."""
        from titiler.cache.utils import CacheKeyGenerator

        generator = CacheKeyGenerator("test-app")

        # Test HTTP URL
        pattern = generator.get_pattern_for_datatree(
            "http://example.com/path/to/file.zarr"
        )
        assert pattern == "test-app:datatree:http:example_com:path:to:*"

    def test_datatree_pattern_https_url(self):
        """Test pattern generation for HTTPS URLs."""
        from titiler.cache.utils import CacheKeyGenerator

        generator = CacheKeyGenerator("test-app")

        # Test HTTPS URL
        pattern = generator.get_pattern_for_datatree(
            "https://api.example.com/data/file.zarr"
        )
        assert pattern == "test-app:datatree:https:api_example_com:data:*"

    def test_datatree_pattern_file_path(self):
        """Test pattern generation for file paths."""
        from titiler.cache.utils import CacheKeyGenerator

        generator = CacheKeyGenerator("test-app")

        # Test file path
        pattern = generator.get_pattern_for_datatree("/test/file.zarr")
        assert pattern == "test-app:datatree:file:test:*"

    def test_datatree_pattern_fallback(self):
        """Test pattern generation fallback."""
        from titiler.cache.utils import CacheKeyGenerator

        generator = CacheKeyGenerator("test-app")

        # Test unhandled format
        pattern = generator.get_pattern_for_datatree("weird://format/file.zarr")
        assert pattern == "test-app:datatree:*file.zarr*"

    def test_datatree_pattern_single_filename(self):
        """Test pattern generation for single filename."""
        from titiler.cache.utils import CacheKeyGenerator

        generator = CacheKeyGenerator("test-app")

        # Test single filename
        pattern = generator.get_pattern_for_datatree("file.zarr")
        assert pattern == "test-app:datatree:*file.zarr*"
