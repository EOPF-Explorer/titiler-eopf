"""S3+Redis composite cache backend."""

import logging
from typing import Any, Optional, Pattern, Union

from ..backends.base import CacheBackend, CacheBackendUnavailable, CacheError
from ..backends.redis import RedisCacheBackend
from ..backends.s3 import S3StorageBackend
from ..settings import CacheRedisSettings, CacheS3Settings

logger = logging.getLogger(__name__)


class S3RedisCacheBackend(CacheBackend):
    """Composite cache backend using Redis for metadata and S3 for tile data.

    Redis stores cache keys and metadata for fast access and pattern matching.
    S3 stores the actual tile data with TTL information.
    This provides fast access patterns with scalable storage.
    """

    def __init__(
        self,
        redis_backend: RedisCacheBackend,
        s3_backend: S3StorageBackend,
        metadata_prefix: str = "meta:",
    ):
        """Initialize composite S3+Redis cache backend.

        Args:
            redis_backend: Redis backend for metadata
            s3_backend: S3 backend for tile data storage
            metadata_prefix: Prefix for Redis metadata keys
        """
        self.redis = redis_backend
        self.s3 = s3_backend
        self.metadata_prefix = metadata_prefix

        # Combined statistics
        self._stats = {
            "hits": 0,
            "misses": 0,
            "errors": 0,
            "total_operations": 0,
            "s3_operations": 0,
            "redis_operations": 0,
        }

    def _get_metadata_key(self, key: str) -> str:
        """Get Redis metadata key for a cache key."""
        return f"{self.metadata_prefix}{key}"

    async def get(self, key: str) -> Optional[bytes]:
        """Retrieve data using Redis metadata + S3 storage."""
        try:
            self._stats["total_operations"] += 1

            # First check Redis metadata for existence and TTL
            metadata_key = self._get_metadata_key(key)
            metadata = await self.redis.get(metadata_key)

            if metadata is None:
                # No metadata in Redis = cache miss
                self._stats["misses"] += 1
                logger.debug(f"Composite Cache MISS (no metadata): {key}")
                return None

            self._stats["redis_operations"] += 1

            # Metadata exists, get data from S3
            data = await self.s3.get(key)
            self._stats["s3_operations"] += 1

            if data is not None:
                self._stats["hits"] += 1
                logger.debug(f"Composite Cache HIT: {key}")
                return data
            else:
                # Data missing from S3 but metadata exists - cleanup metadata
                await self.redis.delete(metadata_key)
                self._stats["misses"] += 1
                logger.debug(f"Composite Cache MISS (data missing): {key}")
                return None

        except CacheBackendUnavailable:
            self._stats["errors"] += 1
            raise
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"Composite get error for key {key}: {e}")
            raise CacheError(f"Failed to get key {key}: {e}") from e

    async def set(self, key: str, value: bytes, ttl: Optional[int] = None) -> bool:
        """Store data in both Redis metadata and S3 storage."""
        try:
            self._stats["total_operations"] += 1

            # Store data in S3 first
            s3_success = await self.s3.set(key, value, ttl)
            self._stats["s3_operations"] += 1

            if not s3_success:
                return False

            # Store metadata in Redis with same TTL
            metadata_key = self._get_metadata_key(key)
            metadata_value = f"s3:{len(value)}".encode(
                "utf-8"
            )  # Simple metadata: backend:size
            redis_success = await self.redis.set(metadata_key, metadata_value, ttl)
            self._stats["redis_operations"] += 1

            if redis_success:
                logger.debug(
                    f"Composite Cache SET: {key} ({len(value)} bytes, TTL: {ttl})"
                )
                return True
            else:
                # Redis failed, cleanup S3 to maintain consistency
                await self.s3.delete(key)
                return False

        except CacheBackendUnavailable:
            self._stats["errors"] += 1
            return False
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"Composite set error for key {key}: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """Delete from both Redis and S3."""
        try:
            self._stats["total_operations"] += 1

            # Delete from both backends
            metadata_key = self._get_metadata_key(key)
            redis_deleted = await self.redis.delete(metadata_key)
            s3_deleted = await self.s3.delete(key)

            self._stats["redis_operations"] += 1
            self._stats["s3_operations"] += 1

            # Return True if either backend had the key
            success = redis_deleted or s3_deleted
            logger.debug(
                f"Composite Cache DELETE: {key} (redis: {redis_deleted}, s3: {s3_deleted})"
            )
            return success

        except CacheBackendUnavailable:
            self._stats["errors"] += 1
            return False
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"Composite delete error for key {key}: {e}")
            return False

    async def exists(self, key: str) -> bool:
        """Check existence using Redis metadata (faster than S3)."""
        try:
            self._stats["total_operations"] += 1

            metadata_key = self._get_metadata_key(key)
            exists = await self.redis.exists(metadata_key)
            self._stats["redis_operations"] += 1
            return exists

        except CacheBackendUnavailable:
            self._stats["errors"] += 1
            return False
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"Composite exists error for key {key}: {e}")
            return False

    async def clear_pattern(self, pattern: Union[str, Pattern]) -> int:
        """Clear pattern from both Redis and S3."""
        try:
            self._stats["total_operations"] += 1

            # Clear metadata from Redis first (faster pattern matching)
            metadata_pattern = f"{self.metadata_prefix}{pattern}"
            redis_deleted = await self.redis.clear_pattern(metadata_pattern)
            self._stats["redis_operations"] += 1

            # Clear data from S3
            s3_deleted = await self.s3.clear_pattern(pattern)
            self._stats["s3_operations"] += 1

            total_deleted = max(
                redis_deleted, s3_deleted
            )  # Use max as they should be similar
            logger.debug(
                f"Composite Cache CLEAR pattern: {pattern} (redis: {redis_deleted}, s3: {s3_deleted})"
            )
            return total_deleted

        except CacheBackendUnavailable:
            self._stats["errors"] += 1
            return 0
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"Composite clear pattern error for {pattern}: {e}")
            return 0

    async def health_check(self) -> dict[str, Any]:
        """Check health of both Redis and S3 backends."""
        try:
            # Check both backends
            redis_health = await self.redis.health_check()
            s3_health = await self.s3.health_check()

            # Determine overall status
            if (
                redis_health["status"] == "connected"
                and s3_health["status"] == "connected"
            ):
                overall_status = "connected"
            elif redis_health["status"] == "error" or s3_health["status"] == "error":
                overall_status = "error"
            else:
                overall_status = "partially_connected"

            return {
                "status": overall_status,
                "redis": redis_health,
                "s3": s3_health,
                "metadata_prefix": self.metadata_prefix,
            }

        except Exception as e:
            logger.error(f"Composite health check error: {e}")
            return {
                "status": "error",
                "error": str(e),
                "redis": {"status": "unknown"},
                "s3": {"status": "unknown"},
            }

    async def get_stats(self) -> dict[str, Any]:
        """Get combined statistics from both backends."""
        total_ops = self._stats["total_operations"]
        if total_ops > 0:
            hit_rate = (self._stats["hits"] / total_ops) * 100
        else:
            hit_rate = 0.0

        # Get individual backend stats
        redis_stats = await self.redis.get_stats()
        s3_stats = await self.s3.get_stats()

        return {
            "backend": "s3+redis",
            "hit_rate": round(hit_rate, 2),
            "total_hits": self._stats["hits"],
            "total_misses": self._stats["misses"],
            "total_errors": self._stats["errors"],
            "total_operations": total_ops,
            "s3_operations": self._stats["s3_operations"],
            "redis_operations": self._stats["redis_operations"],
            "redis_stats": redis_stats,
            "s3_stats": s3_stats,
        }

    @classmethod
    def from_settings(
        cls,
        redis_settings: CacheRedisSettings,
        s3_settings: CacheS3Settings,
        metadata_prefix: str = "meta:",
    ) -> "S3RedisCacheBackend":
        """Create composite backend from settings."""
        redis_backend = RedisCacheBackend.from_settings(redis_settings)
        s3_backend = S3StorageBackend.from_settings(s3_settings)

        return cls(
            redis_backend=redis_backend,
            s3_backend=s3_backend,
            metadata_prefix=metadata_prefix,
        )

    async def close(self):
        """Close connections to both backends."""
        await self.redis.close()
        # S3 backend doesn't need explicit closing
        logger.debug("Composite backend connections closed")
