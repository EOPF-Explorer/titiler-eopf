"""Tests for cache key generation utilities."""

from fastapi import FastAPI
from starlette.testclient import TestClient

from titiler.cache.utils import CacheKeyGenerator


class TestCacheKeyGenerator:
    """Test cache key generation functionality."""

    def test_initialization(self):
        """Test CacheKeyGenerator initialization."""
        generator = CacheKeyGenerator("test-app")
        assert generator.namespace == "test-app"
        assert generator.exclude_params == set()
        assert generator.max_key_length == 2048

        generator = CacheKeyGenerator(
            "test-app", exclude_params=["format", "buffer"], max_key_length=100
        )
        assert generator.exclude_params == {"format", "buffer"}
        assert generator.max_key_length == 100

    def test_path_parsing(self):
        """Test URL path parsing."""
        generator = CacheKeyGenerator("test")

        # Test basic path parsing
        assert generator._parse_path("/tiles/10/512/384") == [
            "tiles",
            "10",
            "512",
            "384",
        ]
        assert generator._parse_path("/") == []
        assert generator._parse_path("") == []

        # Test file extension removal
        assert generator._parse_path("/tiles/10/512/384.png") == [
            "tiles",
            "10",
            "512",
            "384",
        ]
        assert generator._parse_path("/tilejson.json") == ["tilejson"]

        # Test complex paths
        path = "/collections/test/items/item1/tiles/WebMercatorQuad/10/512/384.png"
        expected = [
            "collections",
            "test",
            "items",
            "item1",
            "tiles",
            "WebMercatorQuad",
            "10",
            "512",
            "384",
        ]
        assert generator._parse_path(path) == expected

    def test_parameter_filtering(self):
        """Test query parameter filtering."""
        generator = CacheKeyGenerator("test", exclude_params=["format", "buffer"])

        # Test basic filtering
        params = {"rescale": "0,255", "colormap_name": "viridis", "format": "png"}
        filtered = generator._filter_query_params(params)
        assert filtered == {"rescale": "0,255", "colormap_name": "viridis"}
        assert "format" not in filtered

        # Test empty parameters
        assert generator._filter_query_params({}) == {}

        # Test case-insensitive exclusion
        params = {"FORMAT": "png", "Buffer": "5", "rescale": "0,255"}
        filtered = generator._filter_query_params(params)
        assert filtered == {"rescale": "0,255"}

    def test_params_hash_generation(self):
        """Test parameter hash generation."""
        generator = CacheKeyGenerator("test")

        # Test empty parameters
        assert generator._generate_params_hash({}) == "noparams"

        # Test deterministic hash generation
        params1 = {"rescale": "0,255", "colormap_name": "viridis"}
        params2 = {"colormap_name": "viridis", "rescale": "0,255"}  # Different order
        hash1 = generator._generate_params_hash(params1)
        hash2 = generator._generate_params_hash(params2)
        assert hash1 == hash2  # Should be identical despite different order
        assert len(hash1) == 8  # Should be 8 characters

    def test_cache_key_from_path_and_params(self):
        """Test cache key generation from path and parameters."""
        generator = CacheKeyGenerator("titiler-eopf", exclude_params=["format"])

        # Test basic key generation
        path = "/collections/test/items/item1/tiles/10/512/384"
        params = {"rescale": "0,255", "colormap_name": "viridis", "format": "png"}
        key = generator.from_path_and_params(path, params, "tile")

        expected_parts = [
            "titiler-eopf",
            "tile",
            "collections",
            "test",
            "items",
            "item1",
            "tiles",
            "10",
            "512",
            "384",
        ]
        assert all(part in key for part in expected_parts)
        assert "format" not in key  # Should be excluded

        # Test key consistency
        key1 = generator.from_path_and_params(path, params, "tile")
        key2 = generator.from_path_and_params(path, params, "tile")
        assert key1 == key2

    def test_cache_key_max_length_handling(self):
        """Test cache key length limiting."""
        generator = CacheKeyGenerator("test", max_key_length=50)

        # Create a very long path that would exceed max_key_length
        long_path = "/collections/very-long-collection-name-that-exceeds-limits/items/very-long-item-name/tiles/WebMercatorQuad/18/123456/789012"
        long_params = {"very_long_parameter_name": "very_long_parameter_value"}

        key = generator.from_path_and_params(long_path, long_params, "tile")
        assert len(key) <= 50
        assert key.startswith("test:tile:hash:")

    def test_pattern_generation(self):
        """Test Redis pattern generation."""
        generator = CacheKeyGenerator("titiler-eopf")

        # Test collection pattern
        pattern = generator.get_pattern_for_collection("test-collection")
        assert pattern == "titiler-eopf:*:collections:test-collection:*"

        # Test item pattern
        pattern = generator.get_pattern_for_item("test-collection", "test-item")
        assert pattern == "titiler-eopf:*:collections:test-collection:items:test-item:*"

        # Test cache type pattern
        pattern = generator.get_pattern_for_cache_type("tile")
        assert pattern == "titiler-eopf:tile:*"


class TestRequestIntegration:
    """Test integration with HTTP requests."""

    def test_request_key_generation(self):
        """Test cache key generation from actual requests."""
        app = FastAPI()

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        client = TestClient(app)
        generator = CacheKeyGenerator("test-app")

        # Make a request to get request object
        with client:
            response = client.get("/test?rescale=0,255&colormap_name=viridis")
            assert response.status_code == 200

        # We can't easily get the request object from TestClient,
        # so we'll simulate it
        from starlette.datastructures import URL, QueryParams

        # Create mock request
        url = URL(
            "http://testserver/collections/test/items/item1/tiles/10/512/384?rescale=0,255&colormap_name=viridis"
        )
        query_params = QueryParams("rescale=0,255&colormap_name=viridis")

        # Mock request object
        class MockRequest:
            def __init__(self, url, query_params):
                self.url = url
                self.query_params = query_params

        mock_request = MockRequest(url, query_params)
        key = generator.from_request(mock_request, "tile")

        # Verify key structure
        assert key.startswith("test-app:tile:")
        assert "collections" in key
        assert "test" in key
        assert "items" in key
        assert "item1" in key

    def test_extra_params_handling(self):
        """Test handling of extra parameters in request-based key generation."""
        generator = CacheKeyGenerator("test-app")

        # Create minimal mock request
        from starlette.datastructures import URL, QueryParams

        class MockRequest:
            def __init__(self, url, query_params):
                self.url = url
                self.query_params = query_params

        url = URL("http://testserver/test")
        query_params = QueryParams("param1=value1")
        mock_request = MockRequest(url, query_params)

        # Test with extra parameters
        extra_params = {"user_id": "123", "session": "abc"}
        key = generator.from_request(mock_request, "tile", extra_params)

        # Key should be deterministic regardless of extra param order
        extra_params_reversed = {"session": "abc", "user_id": "123"}
        key2 = generator.from_request(mock_request, "tile", extra_params_reversed)
        assert key == key2


class TestEOPFRealWorldKeys:
    """Test cache key generation with real-world EOPF Explorer URLs."""

    def test_complex_eopf_tile_url(self):
        """Test cache key generation for complex EOPF tile URL."""
        generator = CacheKeyGenerator("titiler-eopf")

        # Real EOPF Explorer tile URL
        path = "/raster/collections/sentinel-2-l2a-staging/items/S2B_MSIL2A_20251115T091139_N0511_R050_T35SLU_20251115T111807/tiles/WebMercatorQuad/14/9330/6490@1x"
        params = {
            "rescale": "0,1",
            "color_formula": "gamma rgb 1.3, sigmoidal rgb 6 0.1, saturation 1.2",
            "variables": [
                "/measurements/reflectance:b04",
                "/measurements/reflectance:b03",
                "/measurements/reflectance:b02",
            ],
            "bidx": "1",
            "nodata": "0",
        }

        # Generate cache key
        key = generator.from_path_and_params(path, params, "tile")

        # Verify key structure
        assert key.startswith("titiler-eopf:tile:")
        assert "sentinel-2-l2a-staging" in key
        assert "S2B_MSIL2A_20251115T091139_N0511_R050_T35SLU_20251115T111807" in key
        assert "WebMercatorQuad" in key
        assert "14" in key  # zoom level
        assert "9330" in key  # x coordinate
        assert "6490" in key  # y coordinate

        # Key should be deterministic
        key2 = generator.from_path_and_params(path, params, "tile")
        assert key == key2

        # Verify path parsing handled the @1x suffix correctly
        parsed_path = generator._parse_path(path)
        assert parsed_path[-1] == "6490@1x"  # Should preserve @1x in path

    def test_eopf_url_with_url_encoding(self):
        """Test cache key generation with URL-encoded parameters."""
        generator = CacheKeyGenerator("titiler-eopf")

        # URL with encoded parameters (as they would appear in HTTP request)
        path = "/raster/collections/sentinel-2-l2a-staging/items/S2B_MSIL2A_20251115T091139_N0511_R050_T35SLU_20251115T111807/tiles/WebMercatorQuad/14/9330/6490@1x"

        # Parameters with URL decoding applied (as they would be in request.query_params)
        decoded_params = {
            "rescale": "0,1",  # Was 0%2C1
            "color_formula": "gamma rgb 1.3, sigmoidal rgb 6 0.1, saturation 1.2",  # Spaces and commas decoded
            "variables": "/measurements/reflectance:b04",  # Was %2Fmeasurements%2Freflectance%3Ab04
            "bidx": "1",
            "nodata": "0",
        }

        key = generator.from_path_and_params(path, decoded_params, "tile")

        # Should handle decoded parameters correctly
        assert key.startswith("titiler-eopf:tile:")
        assert len(key) <= generator.max_key_length

    def test_eopf_multiple_variables_handling(self):
        """Test handling of multiple 'variables' parameters."""
        generator = CacheKeyGenerator("titiler-eopf")

        path = "/raster/collections/test-collection/items/test-item/tiles/WebMercatorQuad/10/512/384"

        # Test with list of variables (as would come from FastAPI query parsing)
        params_with_list = {
            "variables": [
                "/measurements/reflectance:b04",
                "/measurements/reflectance:b03",
                "/measurements/reflectance:b02",
            ],
            "bidx": "1",
        }

        # Test with single variable (first value taken)
        params_single = {
            "variables": "/measurements/reflectance:b04",  # Only first value
            "bidx": "1",
        }

        key_list = generator.from_path_and_params(path, params_with_list, "tile")
        key_single = generator.from_path_and_params(path, params_single, "tile")

        # Should be deterministic - takes first value from list
        assert key_list == key_single

    def test_eopf_long_collection_item_names(self):
        """Test handling of very long collection and item names."""
        generator = CacheKeyGenerator("titiler-eopf")

        # Very long path similar to real EOPF data
        long_path = "/raster/collections/sentinel-2-l2a-staging-with-very-long-name-that-could-cause-issues/items/S2B_MSIL2A_20251115T091139_N0511_R050_T35SLU_20251115T111807_EXTENDED_WITH_MORE_METADATA/tiles/WebMercatorQuad/14/9330/6490"

        complex_params = {
            "rescale": "0,1",
            "color_formula": "gamma rgb 1.3, sigmoidal rgb 6 0.1, saturation 1.2",
            "variables": "/measurements/reflectance:b04",
            "bidx": "1",
            "nodata": "0",
            "additional_very_long_parameter_name": "very_long_parameter_value_that_adds_length",
        }

        key = generator.from_path_and_params(long_path, complex_params, "tile")

        # Should handle long keys appropriately
        assert len(key) <= generator.max_key_length

        # If key is hashed due to length, should start with namespace:type:hash:
        if len(key) >= generator.max_key_length - 50:  # Close to limit
            parts = key.split(":")
            if "hash" in parts:
                assert parts[0] == "titiler-eopf"
                assert parts[1] == "tile"
                assert parts[2] == "hash"

    def test_eopf_parameter_exclusion(self):
        """Test parameter exclusion for EOPF-specific parameters."""
        # Exclude format and callback parameters commonly used in EOPF
        generator = CacheKeyGenerator(
            "titiler-eopf", exclude_params=["format", "callback", "buffer"]
        )

        path = (
            "/raster/collections/test/items/test-item/tiles/WebMercatorQuad/10/512/384"
        )

        params_with_excluded = {
            "rescale": "0,1",
            "variables": "/measurements/reflectance:b04",
            "format": "png",  # Should be excluded
            "callback": "jsonp_callback",  # Should be excluded
            "buffer": "10",  # Should be excluded
            "bidx": "1",  # Should be included
        }

        params_without_excluded = {
            "rescale": "0,1",
            "variables": "/measurements/reflectance:b04",
            "bidx": "1",
        }

        key_with = generator.from_path_and_params(path, params_with_excluded, "tile")
        key_without = generator.from_path_and_params(
            path, params_without_excluded, "tile"
        )

        # Keys should be identical when excluded params are removed
        assert key_with == key_without

    def test_eopf_cache_patterns(self):
        """Test Redis pattern generation for EOPF collections and items."""
        generator = CacheKeyGenerator("titiler-eopf")

        # Test collection pattern
        collection_pattern = generator.get_pattern_for_collection(
            "sentinel-2-l2a-staging"
        )
        assert (
            collection_pattern == "titiler-eopf:*:collections:sentinel-2-l2a-staging:*"
        )

        # Test item pattern
        item_id = "S2B_MSIL2A_20251115T091139_N0511_R050_T35SLU_20251115T111807"
        item_pattern = generator.get_pattern_for_item("sentinel-2-l2a-staging", item_id)
        expected = (
            f"titiler-eopf:*:collections:sentinel-2-l2a-staging:items:{item_id}:*"
        )
        assert item_pattern == expected

        # Test cache type pattern
        tile_pattern = generator.get_pattern_for_cache_type("tile")
        assert tile_pattern == "titiler-eopf:tile:*"

    def test_eopf_key_consistency_across_requests(self):
        """Test that identical requests generate identical cache keys."""
        generator = CacheKeyGenerator("titiler-eopf")

        # Same path and parameters in different order
        path = "/raster/collections/sentinel-2-l2a-staging/items/test-item/tiles/WebMercatorQuad/10/512/384"

        params1 = {
            "rescale": "0,1",
            "bidx": "1",
            "variables": "/measurements/reflectance:b04",
            "nodata": "0",
        }

        params2 = {
            "nodata": "0",
            "variables": "/measurements/reflectance:b04",
            "rescale": "0,1",
            "bidx": "1",
        }

        key1 = generator.from_path_and_params(path, params1, "tile")
        key2 = generator.from_path_and_params(path, params2, "tile")

        # Order of parameters should not affect cache key
        assert key1 == key2

    def test_eopf_different_zoom_levels_different_keys(self):
        """Test that different zoom levels generate different cache keys."""
        generator = CacheKeyGenerator("titiler-eopf")

        base_path = "/raster/collections/sentinel-2-l2a-staging/items/test-item/tiles/WebMercatorQuad"
        params = {"rescale": "0,1", "bidx": "1"}

        # Different zoom levels
        path_z10 = f"{base_path}/10/512/384"
        path_z14 = f"{base_path}/14/9330/6490"

        key_z10 = generator.from_path_and_params(path_z10, params, "tile")
        key_z14 = generator.from_path_and_params(path_z14, params, "tile")

        # Different zoom levels should have different cache keys
        assert key_z10 != key_z14
        assert "10" in key_z10
        assert "14" in key_z14

    def test_exact_eopf_explorer_url(self):
        """Test the exact EOPF Explorer URL provided by the user."""
        generator = CacheKeyGenerator("titiler-eopf")

        # Exact URL from user request
        path = "/raster/collections/sentinel-2-l2a-staging/items/S2B_MSIL2A_20251115T091139_N0511_R050_T35SLU_20251115T111807/tiles/WebMercatorQuad/14/9330/6490@1x"

        # URL decoded parameters from the original request
        params = {
            "rescale": "0,1",  # Was 0%2C1
            "color_formula": "gamma rgb 1.3, sigmoidal rgb 6 0.1, saturation 1.2",
            "variables": "/measurements/reflectance:b04",  # Multiple vars, taking first
            "bidx": "1",
            "nodata": "0",
        }

        # Generate the cache key
        cache_key = generator.from_path_and_params(path, params, "tile")

        # Print for debugging/verification
        print(f"Cache key for EOPF URL: {cache_key}")

        # Verify structure
        assert cache_key.startswith("titiler-eopf:tile:")

        # Verify it contains key path components
        key_parts = cache_key.split(":")
        assert "sentinel-2-l2a-staging" in key_parts
        assert (
            "S2B_MSIL2A_20251115T091139_N0511_R050_T35SLU_20251115T111807" in key_parts
        )
        assert "WebMercatorQuad" in key_parts
        assert "14" in key_parts
        assert "9330" in key_parts
        assert "6490@1x" in key_parts

        # Verify key is deterministic
        cache_key_2 = generator.from_path_and_params(path, params, "tile")
        assert cache_key == cache_key_2

        # Verify key length is reasonable
        assert len(cache_key) <= generator.max_key_length
        print(f"Cache key length: {len(cache_key)}")
