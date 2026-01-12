"""Abstract cache backend interface."""

import abc
from typing import Any, Optional, Pattern, Union


class CacheBackend(abc.ABC):
    """Abstract cache backend interface.

    Defines the contract for all cache backend implementations including
    Redis, S3, composite backends, and in-memory implementations.
    """

    @abc.abstractmethod
    async def get(self, key: str) -> Optional[bytes]:
        """Retrieve data from cache.

        Args:
            key: Cache key to retrieve

        Returns:
            Cached data as bytes, or None if not found

        Raises:
            CacheError: On backend-specific errors (should be handled gracefully)
        """
        ...

    @abc.abstractmethod
    async def set(self, key: str, value: bytes, ttl: Optional[int] = None) -> bool:
        """Store data in cache.

        Args:
            key: Cache key to store under
            value: Data to cache as bytes
            ttl: Time to live in seconds, None for backend default

        Returns:
            True if successfully stored, False on error
        """
        ...

    @abc.abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete single cache entry.

        Args:
            key: Cache key to delete

        Returns:
            True if key existed and was deleted, False otherwise
        """
        ...

    @abc.abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if cache key exists.

        Args:
            key: Cache key to check

        Returns:
            True if key exists, False otherwise
        """
        ...

    @abc.abstractmethod
    async def clear_pattern(self, pattern: Union[str, Pattern]) -> int:
        """Delete cache entries matching pattern.

        Args:
            pattern: Pattern to match keys (Redis glob or regex pattern)

        Returns:
            Number of keys deleted
        """
        ...

    @abc.abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Check backend health and return metrics.

        Returns:
            Dictionary with health status and backend-specific metrics
        """
        ...

    async def get_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache hit/miss rates and other metrics.
            Base implementation returns empty dict.
        """
        return {}


class CacheError(Exception):
    """Base exception for cache-related errors."""

    pass


class CacheBackendUnavailable(CacheError):
    """Raised when cache backend is unavailable."""

    pass
