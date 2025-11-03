""" "titiler.eopf cache."""

from __future__ import annotations

try:
    import redis

except ImportError:  # pragma: nocover
    redis = None  # type: ignore


class RedisCache:
    """Redis connection pool singleton class."""

    _instance = None

    @classmethod
    def get_instance(cls, host: str) -> redis.ConnectionPool:
        """Get the redis connection pool."""
        assert redis, "Redis package needs to be installed to use Redis Cache"
        if cls._instance is None:
            cls._instance = redis.ConnectionPool(host=host, port=6379, db=0)
        return cls._instance
