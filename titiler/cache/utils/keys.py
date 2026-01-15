"""Cache key generation utilities."""

import hashlib
import logging
from typing import Optional
from urllib.parse import urlencode, urlparse

from starlette.requests import Request

logger = logging.getLogger(__name__)


class CacheKeyGenerator:
    """Generate deterministic cache keys from HTTP requests.

    Handles URL path parsing, query parameter filtering, and namespace organization
    to create consistent cache keys across different titiler applications.
    """

    def __init__(
        self,
        namespace: str,
        exclude_params: Optional[list[str]] = None,
        max_key_length: int = 2048,
    ):
        """Initialize cache key generator.

        Args:
            namespace: Application namespace (e.g., "titiler-eopf", "my-app")
            exclude_params: Query parameters to exclude from cache keys
            max_key_length: Maximum cache key length (for Redis compatibility, default 2048)
        """
        self.namespace = namespace
        self.exclude_params = set(exclude_params or [])
        self.max_key_length = max_key_length

    def from_request(
        self,
        request: Request,
        cache_type: str = "tile",
        extra_params: Optional[dict[str, str]] = None,
    ) -> str:
        """Generate cache key from HTTP request.

        Args:
            request: Starlette/FastAPI request object
            cache_type: Type of cache (e.g., "tile", "tilejson", "preview")
            extra_params: Additional parameters to include in key

        Returns:
            Deterministic cache key string
        """
        # Parse URL components
        parsed_url = urlparse(str(request.url))
        path_parts = self._parse_path(parsed_url.path)

        # Filter and normalize query parameters
        cache_params = self._filter_query_params(dict(request.query_params))

        # Add extra parameters if provided
        if extra_params:
            cache_params.update(extra_params)

        # Generate parameter hash for deterministic key
        params_hash = self._generate_params_hash(cache_params)

        # Construct cache key with namespace
        key_parts = [self.namespace, cache_type] + path_parts + [params_hash]
        cache_key = ":".join(str(part) for part in key_parts if part)

        # Ensure key length is within limits
        if len(cache_key) > self.max_key_length:
            # Hash the entire key if too long
            key_hash = hashlib.md5(cache_key.encode("utf-8")).hexdigest()
            cache_key = f"{self.namespace}:{cache_type}:hash:{key_hash}"

        logger.debug(f"Generated cache key: {cache_key}")
        return cache_key

    def _parse_path(self, path: str) -> list[str]:
        """Parse URL path into cache key components.

        Args:
            path: URL path (e.g., "/collections/test/items/item1/tiles/WebMercatorQuad/10/512/384.png")

        Returns:
            List of path components relevant for caching
        """
        # Remove leading/trailing slashes and split
        path_parts = path.strip("/").split("/")

        # Remove empty parts
        path_parts = [part for part in path_parts if part]

        # Remove file extensions from the last part
        if path_parts and "." in path_parts[-1]:
            last_part = path_parts[-1]
            path_parts[-1] = last_part.split(".")[0]

        return path_parts

    def _filter_query_params(self, query_params: dict[str, str]) -> dict[str, str]:
        """Filter and normalize query parameters for caching.

        Args:
            query_params: Raw query parameters from request

        Returns:
            Filtered parameters dict suitable for cache key generation
        """
        filtered_params = {}

        for key, value in query_params.items():
            # Skip excluded parameters
            if key.lower() in {p.lower() for p in self.exclude_params}:
                logger.debug(f"Excluding parameter from cache key: {key}")
                continue

            # Handle multiple values (take first for consistency)
            if isinstance(value, list):
                value = value[0] if value else ""

            # Normalize parameter value
            normalized_value = str(value).strip()
            if normalized_value:
                filtered_params[key] = normalized_value

        return filtered_params

    def _generate_params_hash(self, params: dict[str, str]) -> str:
        """Generate deterministic hash from parameters.

        Args:
            params: Filtered query parameters

        Returns:
            8-character hash representing the parameters
        """
        if not params:
            return "noparams"

        # Sort parameters alphabetically for deterministic output
        sorted_params = sorted(params.items())

        # Create URL-encoded string
        params_string = urlencode(sorted_params)

        # Generate hash
        params_hash = hashlib.md5(params_string.encode("utf-8")).hexdigest()

        # Return first 8 characters for shorter keys
        return params_hash[:8]

    def from_path_and_params(
        self,
        path: str,
        query_params: Optional[dict[str, str]] = None,
        cache_type: str = "tile",
        extra_params: Optional[dict[str, str]] = None,
    ) -> str:
        """Generate cache key from path and parameters directly.

        Useful for programmatic cache key generation without HTTP request.

        Args:
            path: URL path
            query_params: Query parameters dict
            cache_type: Type of cache
            extra_params: Additional parameters

        Returns:
            Cache key string
        """
        # Parse path components
        path_parts = self._parse_path(path)

        # Filter parameters
        cache_params = self._filter_query_params(query_params or {})

        # Add extra parameters
        if extra_params:
            cache_params.update(extra_params)

        # Generate hash
        params_hash = self._generate_params_hash(cache_params)

        # Construct key
        key_parts = [self.namespace, cache_type] + path_parts + [params_hash]
        cache_key = ":".join(str(part) for part in key_parts if part)

        # Ensure key length
        if len(cache_key) > self.max_key_length:
            key_hash = hashlib.md5(cache_key.encode("utf-8")).hexdigest()
            cache_key = f"{self.namespace}:{cache_type}:hash:{key_hash}"

        return cache_key

    def get_pattern_for_collection(self, collection_id: str) -> str:
        """Generate Redis pattern for all cache entries of a collection.

        Args:
            collection_id: Collection identifier

        Returns:
            Redis glob pattern string
        """
        return f"{self.namespace}:*:collections:{collection_id}:*"

    def get_pattern_for_item(self, collection_id: str, item_id: str) -> str:
        """Generate Redis pattern for all cache entries of a specific item.

        Args:
            collection_id: Collection identifier
            item_id: Item identifier

        Returns:
            Redis glob pattern string
        """
        return f"{self.namespace}:*:collections:{collection_id}:items:{item_id}:*"

    def get_pattern_for_cache_type(self, cache_type: str) -> str:
        """Generate Redis pattern for specific cache type.

        Args:
            cache_type: Cache type (e.g., "tile", "tilejson", "datatree")

        Returns:
            Redis glob pattern string
        """
        return f"{self.namespace}:{cache_type}:*"

    def get_pattern_for_datatree(self, src_path: str) -> str:
        """Generate Redis pattern for datatree cache entries.

        Args:
            src_path: Source path of the dataset (http://, s3://, or file path)

        Returns:
            Redis glob pattern string
        """
        # For URLs with schemes (http://, s3://, etc.)
        if "://" in src_path:
            from urllib.parse import urlparse

            parsed_url = urlparse(src_path)

            if parsed_url.scheme in ("s3", "http", "https"):
                # Extract meaningful components
                if parsed_url.scheme == "s3":
                    # For s3://bucket/path/to/file.zarr
                    bucket = parsed_url.netloc
                    path_parts = [
                        part for part in parsed_url.path.strip("/").split("/") if part
                    ]
                    if path_parts:
                        # Pattern: namespace:datatree:s3:bucket:path:*
                        pattern_parts = (
                            [self.namespace, "datatree", "s3", bucket]
                            + path_parts[:-1]
                            + ["*"]
                        )
                        return ":".join(pattern_parts)
                else:
                    # For http/https URLs
                    host = parsed_url.netloc.replace(
                        ".", "_"
                    )  # Replace dots for Redis key compatibility
                    path_parts = [
                        part for part in parsed_url.path.strip("/").split("/") if part
                    ]
                    if path_parts:
                        # Pattern: namespace:datatree:http:host:path:*
                        pattern_parts = (
                            [self.namespace, "datatree", parsed_url.scheme, host]
                            + path_parts[:-1]
                            + ["*"]
                        )
                        return ":".join(pattern_parts)

        # For simple file paths like /test/file.zarr
        if src_path.startswith("/"):
            path_parts = [part for part in src_path.strip("/").split("/") if part]
            if path_parts:
                # Pattern: namespace:datatree:file:path:*
                pattern_parts = (
                    [self.namespace, "datatree", "file"] + path_parts[:-1] + ["*"]
                )
                return ":".join(pattern_parts)

        # Fallback: use the filename for any unhandled cases
        filename = src_path.split("/")[-1].split("\\")[
            -1
        ]  # Handle both / and \ separators
        return f"{self.namespace}:datatree:*{filename}*"

    def get_pattern_for_item_all_types(self, collection_id: str, item_id: str) -> str:
        """Generate Redis pattern for all cache types of a specific item.

        Args:
            collection_id: Collection identifier
            item_id: Item identifier

        Returns:
            Redis glob pattern string
        """
        return f"{self.namespace}:*:collections:{collection_id}:items:{item_id}:*"
