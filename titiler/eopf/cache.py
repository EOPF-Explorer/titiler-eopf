""" "titiler.eopf cache."""

from __future__ import annotations

from pydantic import SecretStr

try:
    import redis

except ImportError:  # pragma: nocover
    redis = None  # type: ignore


class RedisCache:
    """Redis connection pool singleton class."""

    _instance = None

    @classmethod
    def get_instance(
        cls, host: str, port: int, password: SecretStr | None
    ) -> redis.ConnectionPool:
        """Get the redis connection pool."""
        assert redis, "Redis package needs to be installed to use Redis Cache"
        if cls._instance is None:
            cls._instance = redis.ConnectionPool(
                host=host,
                port=port,
                password=password.get_secret_value() if password else None,
                db=0,
            )
        return cls._instance
