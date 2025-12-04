"""GeoZarr dataset caching helpers."""

from __future__ import annotations

import hashlib
import logging
import pickle
import random
import sys
import time
from collections.abc import Callable, Iterable
from importlib import import_module
from pathlib import Path
from typing import Any, Hashable
from urllib.parse import ParseResult, urlparse

import xarray
from cachetools import TTLCache  # type: ignore[import-untyped]

from .cache import get_redis_pool
from .settings import CacheSettings

logger = logging.getLogger(__name__)

redis_module: Any | None
RedisErrorType: type[Exception]

try:  # pragma: nocover - optional redis dependency
    import redis as redis_module  # type: ignore[import-untyped]
    from redis.exceptions import RedisError as _RedisError  # type: ignore[import-untyped]
except ImportError:  # pragma: nocover
    redis_module = None
    RedisErrorType = Exception
else:
    RedisErrorType = _RedisError

redis = redis_module


CacheKey = str


def _now() -> float:
    return time.monotonic()


def _resolve_timer(path: str | None) -> Callable[[], float]:
    if not path:
        return _now

    module_path, _, attr = path.replace(":", ".").rpartition(".")
    if not module_path or not attr:
        raise ValueError(
            "Timer path must include a module and attribute (e.g. package.module:callable)."
        )

    timer = getattr(import_module(module_path), attr)
    if not callable(timer):
        raise TypeError(f"Timer '{path}' is not callable")
    return timer


def _make_hashable(value: Any) -> Hashable:
    if isinstance(value, Hashable):
        return value
    if isinstance(value, dict):
        return tuple((key, _make_hashable(value[key])) for key in sorted(value))
    if isinstance(value, (list, tuple)):
        return tuple(_make_hashable(v) for v in value)
    if isinstance(value, set):
        return tuple(sorted((_make_hashable(v) for v in value), key=repr))
    return repr(value)


def build_dataset_cache_key(src_path: str, kwargs: dict[str, Any]) -> CacheKey:
    """Build a deterministic cache key for a dataset path and opener kwargs."""

    if not kwargs:
        return src_path

    normalized_kwargs = tuple((key, _make_hashable(kwargs[key])) for key in sorted(kwargs))
    digest = hashlib.sha1(repr(normalized_kwargs).encode("utf-8")).hexdigest()
    return f"{src_path}#{digest}"


def normalize_src_path(src_path: str) -> tuple[str, ParseResult]:
    """Return an absolute path (file:// when needed) plus parsed result."""

    parsed = urlparse(src_path)
    if parsed.scheme:
        return src_path, parsed

    resolved = Path(src_path).resolve()
    normalized = f"file://{resolved}"
    return normalized, urlparse(normalized)


class DatasetCache:
    """Cache GeoZarr datatrees locally and optionally in Redis."""

    def __init__(
        self,
        *,
        ttl_seconds: int,
        max_items: int | None,
        enable_redis: bool,
        redis_host: str | None,
        redis_port: int,
        redis_username: str | None,
        redis_password: str | None,
        redis_db: int,
        redis_ssl: bool,
        ttl_jitter_seconds: int,
        timer: Callable[[], float] = _now,
    ) -> None:
        """Configure cache TTL, capacity, and Redis connectivity."""
        self._ttl = max(0, ttl_seconds)
        self._timer = timer
        self._ttl_jitter = max(0, ttl_jitter_seconds)
        self._redis_config = (
            {
                "host": redis_host,
                "port": redis_port,
                "db": redis_db,
                "username": redis_username,
                "password": redis_password,
                "ssl": redis_ssl,
            }
            if self._ttl and enable_redis and redis_host
            else None
        )
        self._redis_client: Any | None = None
        local_max = max_items or sys.maxsize
        self._local: TTLCache | None = (
            TTLCache(maxsize=local_max, ttl=self._ttl, timer=self._timer) if self._ttl else None
        )

    @classmethod
    def from_settings(cls, settings: CacheSettings) -> "DatasetCache":
        """Create a cache based on application settings."""
        timer = _resolve_timer(settings.dataset_timer_path)
        return cls(
            ttl_seconds=settings.dataset_ttl_seconds,
            max_items=settings.dataset_max_items,
            enable_redis=settings.enable,
            redis_host=settings.host,
            redis_port=settings.port,
            redis_username=settings.username,
            redis_password=settings.password,
            redis_db=settings.db,
            redis_ssl=settings.ssl,
            ttl_jitter_seconds=settings.dataset_ttl_jitter_seconds,
            timer=timer,
        )

    @property
    def ttl(self) -> int:
        """Return the configured cache TTL in seconds."""
        return self._ttl

    @property
    def local_cache(self) -> TTLCache | None:
        """Expose the in-process TTL cache instance for tests or debugging."""
        return self._local

    @property
    def timer(self) -> Callable[[], float]:
        """Return the callable used to track elapsed time for the local cache."""
        return self._timer

    def clear_local(self) -> None:
        """Remove every entry from the local TTL cache."""
        if self._local is not None:
            self._local.clear()

    def set_timer(self, timer: Callable[[], float]) -> None:
        """Update the timer used by the local TTL cache."""
        self._timer = timer
        if self._local is not None:
            snapshot = dict(self._local.items())
            self._local = TTLCache(maxsize=self._local.maxsize, ttl=self._ttl, timer=timer)
            self._local.update(snapshot)

    def reset_redis(self) -> None:
        """Drop the cached Redis client (used by tests)."""
        client = self._redis_client
        if client is None:
            return
        close = getattr(client, "close", None)
        if callable(close):  # pragma: nocover - best effort cleanup
            try:
                close()
            except Exception:  # noqa: BLE001 - no need to raise during shutdown
                pass
        self._redis_client = None

    def _redis(self) -> Any | None:
        if self._redis_client is not None:
            return self._redis_client
        if not (self._redis_config and redis):
            return None
        pool = get_redis_pool(**self._redis_config)
        self._redis_client = redis.Redis(connection_pool=pool)
        return self._redis_client

    def _redis_ttl(self) -> int:
        if not self._ttl:
            return 0
        if not self._ttl_jitter:
            return self._ttl
        delta = random.randint(-self._ttl_jitter, self._ttl_jitter)
        ttl = self._ttl + delta
        return ttl if ttl > 0 else 1

    def get(self, cache_key: CacheKey) -> xarray.DataTree | None:
        """Fetch a datatree from local or Redis cache."""
        if self._local is None:
            return None

        cached = self._local.get(cache_key)
        if cached is not None:
            logger.info("Cache - local hit %s", cache_key)
            return cached

        cache_client = self._redis()
        if not cache_client:
            return None

        try:
            payload = cache_client.get(cache_key)
        except RedisErrorType as exc:  # pragma: nocover - network failures
            logger.warning("Cache - Redis get failed for %s: %s", cache_key, exc)
            return None

        if not payload:
            return None

        try:
            dataset = pickle.loads(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cache - could not deserialize %s, purging entry: %s", cache_key, exc)
            self._delete_redis_keys(cache_client, [cache_key])
            return None

        logger.info("Cache - Redis hit %s", cache_key)
        self._local[cache_key] = dataset
        return dataset

    def set(self, cache_key: CacheKey, data: xarray.DataTree) -> None:
        """Write a datatree into the caches."""
        if self._local is None:
            return

        self._local[cache_key] = data

        cache_client = self._redis()
        if not cache_client:
            return

        try:
            payload = pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
            ttl = self._redis_ttl()
            kwargs: dict[str, Any] = {"ex": ttl} if ttl else {}
            cache_client.set(cache_key, payload, **kwargs)
        except (RedisErrorType, pickle.PickleError, TypeError) as exc:
            logger.warning("Cache - Redis set failed for %s: %s", cache_key, exc)

    def invalidate(self, normalized_path: str, cache_key: CacheKey | None = None) -> None:
        """Purge cached entries matching the path or specific key."""
        if self._local is not None:
            targets = (cache_key,) if cache_key else self._matching_local_keys(normalized_path)
            for key in filter(None, targets):
                self._local.pop(key, None)

        cache_client = self._redis()
        if not cache_client:
            return

        if cache_key:
            self._delete_redis_keys(cache_client, [cache_key])
        else:
            self._delete_dataset_keys(cache_client, normalized_path)

    def _matching_local_keys(self, normalized_path: str) -> tuple[CacheKey, ...]:
        if self._local is None:
            return ()
        return tuple(key for key in self._local.keys() if isinstance(key, str) and key.startswith(normalized_path))

    def _delete_dataset_keys(self, cache_client: Any, normalized_path: str) -> None:
        scan_iter = getattr(cache_client, "scan_iter", None)
        if not callable(scan_iter):
            fallback = self._matching_local_keys(normalized_path) or (normalized_path,)
            self._delete_redis_keys(cache_client, fallback)
            return

        pattern = f"{normalized_path}*"
        try:
            keys = list(scan_iter(match=pattern))
        except RedisErrorType as exc:  # pragma: nocover - best effort cleanup
            logger.warning("Cache - Redis scan failed for %s: %s", normalized_path, exc)
            return

        if keys:
            self._delete_redis_keys(cache_client, keys)

    @staticmethod
    def _delete_redis_keys(cache_client: Any, keys: Iterable[bytes | str]) -> None:
        targets = tuple(keys)
        if not targets:
            return
        try:
            cache_client.delete(*targets)
        except RedisErrorType as exc:  # pragma: nocover - best effort cleanup
            logger.warning("Cache - Redis delete failed for %s: %s", targets, exc)


_cache_settings = CacheSettings()
DATASET_CACHE = DatasetCache.from_settings(_cache_settings)


def invalidate_open_dataset_cache(src_path: str, **kwargs: Any) -> None:
    """Helper to drop cache entries tied to an open_dataset call."""
    normalized_path, _ = normalize_src_path(src_path)
    cache_key = build_dataset_cache_key(normalized_path, kwargs) if kwargs else None
    DATASET_CACHE.invalidate(normalized_path, cache_key)
