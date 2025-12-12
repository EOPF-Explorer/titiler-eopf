"""titiler.eopf cache helpers."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

try:
    import redis
except ImportError:  # pragma: nocover
    redis = None  # type: ignore


@lru_cache(maxsize=None)
def get_redis_pool(
    *,
    host: str,
    port: int,
    db: int,
    username: str | None,
    password: str | None,
    ssl: bool,
    max_connections: int | None = None,
) -> "redis.ConnectionPool":
    """Return a cached Redis connection pool for the given parameters."""

    assert redis, "Redis package needs to be installed to use Redis Cache"

    kwargs: dict[str, Any] = {
        "host": host,
        "port": port,
        "db": db,
    }
    if username:
        kwargs["username"] = username
    if password:
        kwargs["password"] = password
    if ssl:
        kwargs["ssl"] = True
    if max_connections is not None:
        kwargs["max_connections"] = max_connections

    return redis.ConnectionPool(**kwargs)
