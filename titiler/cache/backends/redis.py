"""Redis cache backend implementation."""

import logging
from typing import Any, Optional, Pattern, Union

from ..backends.base import CacheBackend, CacheBackendUnavailable, CacheError
from ..settings import CacheRedisSettings

try:
    import redis.asyncio as redis
except ImportError:  # pragma: nocover
    redis = None  # type: ignore

logger = logging.getLogger(__name__)


class RedisCacheBackend(CacheBackend):
    """Redis-based cache backend with async support."""

    def __init__(
        self,
        host: str,
        port: int = 6379,
        password: Optional[str] = None,
        db: int = 0,
        **kwargs,
    ):
        """Initialize Redis cache backend.

        Args:
            host: Redis host
            port: Redis port
            password: Redis password (optional)
            db: Redis database number
            **kwargs: Additional Redis connection parameters
        """
        if redis is None:
            raise ImportError("redis package is required for RedisCacheBackend")

        self.host = host
        self.port = port
        self.password = password
        self.db = db
        self._pool = None
        self._client: Optional[redis.Redis] = None
        self.connection_kwargs = kwargs

        # Statistics tracking
        self._stats = {"hits": 0, "misses": 0, "errors": 0, "total_operations": 0}

    async def _get_client(self) -> redis.Redis:
        """Get Redis client with connection pooling."""
        if self._client is None:
            try:
                self._client = redis.Redis(
                    host=self.host,
                    port=self.port,
                    password=self.password,
                    db=self.db,
                    decode_responses=False,  # Keep bytes for tile data
                    **self.connection_kwargs,
                )
                # Test connection
                await self._client.ping()
                logger.debug(f"Connected to Redis at {self.host}:{self.port}")
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
                raise CacheBackendUnavailable(f"Redis unavailable: {e}") from e

        return self._client

    async def get(self, key: str) -> Optional[bytes]:
        """Retrieve data from Redis cache."""
        try:
            client = await self._get_client()
            self._stats["total_operations"] += 1

            data = await client.get(key)
            if data is not None:
                self._stats["hits"] += 1
                logger.debug(f"Cache HIT for key: {key}")
                return data
            else:
                self._stats["misses"] += 1
                logger.debug(f"Cache MISS for key: {key}")
                return None

        except CacheBackendUnavailable:
            self._stats["errors"] += 1
            raise
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"Redis get error for key {key}: {e}")
            raise CacheError(f"Failed to get key {key}: {e}") from e

    async def set(self, key: str, value: bytes, ttl: Optional[int] = None) -> bool:
        """Store data in Redis cache."""
        try:
            client = await self._get_client()
            self._stats["total_operations"] += 1

            if ttl is not None:
                await client.setex(key, ttl, value)
            else:
                await client.set(key, value)

            logger.debug(f"Cache SET for key: {key} (TTL: {ttl})")
            return True

        except CacheBackendUnavailable:
            self._stats["errors"] += 1
            return False
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"Redis set error for key {key}: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """Delete single cache entry from Redis."""
        try:
            client = await self._get_client()
            self._stats["total_operations"] += 1

            result = await client.delete(key)
            logger.debug(f"Cache DELETE for key: {key} (existed: {result > 0})")
            return result > 0

        except CacheBackendUnavailable:
            self._stats["errors"] += 1
            return False
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"Redis delete error for key {key}: {e}")
            return False

    async def exists(self, key: str) -> bool:
        """Check if cache key exists in Redis."""
        try:
            client = await self._get_client()
            self._stats["total_operations"] += 1

            result = await client.exists(key)
            return result > 0

        except CacheBackendUnavailable:
            self._stats["errors"] += 1
            return False
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"Redis exists error for key {key}: {e}")
            return False

    async def clear_pattern(self, pattern: Union[str, Pattern]) -> int:
        """Delete cache entries matching pattern using Redis SCAN."""
        try:
            client = await self._get_client()
            self._stats["total_operations"] += 1

            # Convert regex Pattern to Redis glob if needed
            if hasattr(pattern, "pattern"):
                # Simple conversion for common cases
                redis_pattern = str(pattern.pattern).replace(".*", "*")
            else:
                redis_pattern = str(pattern)

            # Use SCAN to find matching keys (more memory efficient than KEYS)
            deleted = 0
            async for key in client.scan_iter(match=redis_pattern):
                if await client.delete(key):
                    deleted += 1

            logger.debug(f"Cache CLEAR pattern: {redis_pattern} (deleted: {deleted})")
            return deleted

        except CacheBackendUnavailable:
            self._stats["errors"] += 1
            return 0
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"Redis clear pattern error for {pattern}: {e}")
            return 0

    async def health_check(self) -> dict[str, Any]:
        """Check Redis health and return metrics."""
        try:
            client = await self._get_client()

            # Ping Redis
            await client.ping()

            # Get Redis info
            info = await client.info()

            return {
                "status": "connected",
                "host": self.host,
                "port": self.port,
                "db": self.db,
                "redis_version": info.get("redis_version", "unknown"),
                "connected_clients": info.get("connected_clients", 0),
                "used_memory": info.get("used_memory", 0),
                "used_memory_human": info.get("used_memory_human", "0B"),
                "total_connections_received": info.get("total_connections_received", 0),
            }

        except CacheBackendUnavailable:
            return {
                "status": "disconnected",
                "host": self.host,
                "port": self.port,
                "error": "Backend unavailable",
            }
        except Exception as e:
            logger.error(f"Redis health check error: {e}")
            return {
                "status": "error",
                "host": self.host,
                "port": self.port,
                "error": str(e),
            }

    async def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        total_ops = self._stats["total_operations"]
        if total_ops > 0:
            hit_rate = (self._stats["hits"] / total_ops) * 100
        else:
            hit_rate = 0.0

        return {
            "backend": "redis",
            "hit_rate": round(hit_rate, 2),
            "total_hits": self._stats["hits"],
            "total_misses": self._stats["misses"],
            "total_errors": self._stats["errors"],
            "total_operations": total_ops,
        }

    @classmethod
    def from_settings(cls, settings: CacheRedisSettings) -> "RedisCacheBackend":
        """Create Redis backend from settings."""
        if not settings.host:
            raise ValueError("Redis host must be configured")

        return cls(
            host=settings.host,
            port=settings.port,
            password=settings.password.get_secret_value()
            if settings.password
            else None,
            db=settings.db,
        )

    async def scan_keys(self, pattern: str, limit: Optional[int] = None) -> list[str]:
        """Scan for keys matching pattern using Redis SCAN."""
        try:
            client = await self._get_client()
            keys = []

            cursor = 0
            while True:
                cursor, batch_keys = await client.scan(
                    cursor=cursor,
                    match=pattern,
                    count=100,  # Redis SCAN batch size
                )

                keys.extend(
                    [
                        key.decode("utf-8") if isinstance(key, bytes) else key
                        for key in batch_keys
                    ]
                )

                if cursor == 0:  # Full scan complete
                    break

                if limit and len(keys) >= limit:
                    keys = keys[:limit]
                    break

            return keys

        except CacheBackendUnavailable:
            raise
        except Exception as e:
            logger.error(f"Redis scan error for pattern {pattern}: {e}")
            raise CacheError(f"Failed to scan keys for pattern {pattern}: {e}") from e

    async def get_key_info(self, key: str) -> Optional[dict[str, Any]]:
        """Get Redis key information."""
        try:
            client = await self._get_client()

            # Check if key exists
            if not await client.exists(key):
                return None

            # Get TTL (-1 = no expiry, -2 = doesn't exist)
            ttl = await client.ttl(key)
            ttl_seconds = ttl if ttl >= 0 else None

            # Get key type and try to get size
            key_type = await client.type(key)
            size_bytes = None

            try:
                # For string values, get memory usage (Redis 4.0+)
                if hasattr(client, "memory_usage"):
                    size_bytes = await client.memory_usage(key)
                else:
                    # Fallback: estimate size for strings
                    if key_type == "string":
                        value = await client.strlen(key)
                        size_bytes = value
            except Exception:
                pass  # Size estimation failed, skip

            return {
                "key": key,
                "type": key_type.decode("utf-8")
                if isinstance(key_type, bytes)
                else key_type,
                "ttl": ttl_seconds,
                "size": size_bytes,
                "exists": True,
            }

        except CacheBackendUnavailable:
            raise
        except Exception as e:
            logger.error(f"Redis key info error for key {key}: {e}")
            return None

    async def close(self):
        """Close Redis connection."""
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.debug("Redis connection closed")
