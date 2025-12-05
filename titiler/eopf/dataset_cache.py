"""GeoZarr dataset caching helpers.

Keeps cached GeoZarr payloads private and trustworthy by hashing normalized
paths + kwargs into opaque Redis keys, by pickling/compressing/HMAC-signing
each DataTree, and by adding TTL jitter plus a sorted-set index so expirations
stagger and the cache stays within budget.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import pickle
import random
import time
import zlib
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Final
from urllib.parse import ParseResult, urlparse

import xarray

from .cache import get_redis_pool
from .settings import CacheSettings

logger = logging.getLogger(__name__)

redis_module: Any | None
RedisErrorType: type[Exception]

try:  # pragma: nocover - optional redis dependency
    import redis as redis_module  # type: ignore[import-untyped]
    from redis.exceptions import (
        RedisError as _RedisError,  # type: ignore[import-untyped]
    )
except ImportError:  # pragma: nocover
    redis_module = None
    RedisErrorType = Exception
else:
    RedisErrorType = _RedisError

redis = redis_module


CacheKey = str
REDIS_PREFIX: Final = "titiler:dataset-cache"
DIGEST_SIZE: Final = hashlib.sha256().digest_size
CACHE_INDEX_KEY: Final = f"{REDIS_PREFIX}:index"
NO_KWARGS_DIGEST: Final = "base"
DEFAULT_MAX_PAYLOAD_BYTES: Final = 64 * 1024 * 1024
DEFAULT_REDIS_MAX_CONNECTIONS: Final = 128
TTL_JITTER_RATIO: Final = 0.1
SCAN_BATCH_SIZE: Final = 512


def _path_digest(normalized_path: str) -> str:
    return hashlib.sha1(normalized_path.encode("utf-8")).hexdigest()


def _canonicalize(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return tuple((key, _canonicalize(value[key])) for key in sorted(value))
    if isinstance(value, (list, tuple)):
        return tuple(_canonicalize(v) for v in value)
    if isinstance(value, set):
        canonical = (_canonicalize(v) for v in value)
        return tuple(sorted(canonical, key=repr))
    if callable(value):
        module = getattr(value, "__module__", "unknown")
        qualname = getattr(
            value, "__qualname__", getattr(type(value), "__qualname__", "callable")
        )
        return f"{module}.{qualname}"
    return f"{type(value).__module__}.{type(value).__qualname__}"


def _kwargs_digest(kwargs: dict[str, Any]) -> str:
    if not kwargs:
        return NO_KWARGS_DIGEST
    canonical = tuple((key, _canonicalize(kwargs[key])) for key in sorted(kwargs))
    payload = repr(canonical)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def build_dataset_cache_key(src_path: str, kwargs: dict[str, Any]) -> CacheKey:
    """Build a deterministic cache key for a dataset path and opener kwargs."""

    path_token = _path_digest(src_path)
    kwargs_token = _kwargs_digest(kwargs)
    return f"{path_token}:{kwargs_token}"


def normalize_src_path(src_path: str) -> tuple[str, ParseResult]:
    """Return an absolute path (file:// when needed) plus parsed result."""

    parsed = urlparse(src_path)
    if parsed.scheme:
        return src_path, parsed

    resolved = Path(src_path).resolve()
    normalized = f"file://{resolved}"
    return normalized, urlparse(normalized)


def _clone_datatree(tree: xarray.DataTree) -> xarray.DataTree:
    """Return a deep copy to keep cached entries immutable."""

    return tree.copy(deep=True)


def _redis_key(cache_key: CacheKey) -> str:
    return f"{REDIS_PREFIX}:{cache_key}"


def _dataset_pattern(normalized_path: str) -> str:
    return f"{REDIS_PREFIX}:{_path_digest(normalized_path)}:*"


class DatasetCache:
    """Cache GeoZarr datatrees in Redis when configured."""

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
        redis_hmac_secret: str | None,
        redis_max_payload_bytes: int | None,
    ) -> None:
        """Configure cache TTL and Redis connectivity."""

        self._ttl = max(0, ttl_seconds)
        self._max_items = max_items if max_items and max_items > 0 else None
        self._redis_secret = (
            redis_hmac_secret.encode("utf-8") if redis_hmac_secret else None
        )
        max_connections = DEFAULT_REDIS_MAX_CONNECTIONS
        self._redis_config = (
            {
                "host": redis_host,
                "port": redis_port,
                "db": redis_db,
                "username": redis_username,
                "password": redis_password,
                "ssl": redis_ssl,
                "max_connections": max_connections,
            }
            if self._ttl and enable_redis and redis_host and self._redis_secret
            else None
        )
        self._redis_client: Any | None = None
        self._redis_max_payload = (
            redis_max_payload_bytes
            if redis_max_payload_bytes is not None
            else DEFAULT_MAX_PAYLOAD_BYTES
        )
        self._redis_index_key = CACHE_INDEX_KEY

    @classmethod
    def from_settings(cls, settings: CacheSettings) -> "DatasetCache":
        """Create a cache based on application settings."""

        redis_password = (
            settings.password.get_secret_value() if settings.password else None
        )
        redis_secret = (
            settings.dataset_hmac_secret.get_secret_value()
            if settings.dataset_hmac_secret
            else None
        )
        return cls(
            ttl_seconds=settings.dataset_ttl_seconds,
            max_items=settings.dataset_max_items,
            enable_redis=settings.enable,
            redis_host=settings.host,
            redis_port=settings.port,
            redis_username=settings.username,
            redis_password=redis_password,
            redis_db=settings.db,
            redis_ssl=settings.ssl,
            redis_hmac_secret=redis_secret,
            redis_max_payload_bytes=settings.dataset_max_redis_payload_bytes,
        )

    @property
    def ttl(self) -> int:
        """Return the configured cache TTL in seconds."""

        return self._ttl

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
        base = self._ttl
        if base <= 0:
            return 0
        jitter_ratio = TTL_JITTER_RATIO
        if jitter_ratio <= 0:
            return base
        spread = max(1, int(base * jitter_ratio))
        offset = random.randint(-spread, spread)
        return max(1, base + offset)

    def get(self, cache_key: CacheKey, normalized_path: str) -> xarray.DataTree | None:
        """Fetch a datatree from Redis cache."""

        cache_client = self._redis()
        if not cache_client:
            return None

        redis_key = _redis_key(cache_key)
        try:
            payload = cache_client.get(redis_key)
        except RedisErrorType as exc:  # pragma: nocover - network failures
            logger.warning("Cache - Redis get failed for %s: %s", cache_key, exc)
            return None

        if not payload:
            return None

        try:
            dataset = self._deserialize(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Cache - invalid payload for %s, purging entry: %s", cache_key, exc
            )
            self._delete_redis_keys(cache_client, [redis_key])
            return None

        if dataset is None:
            self._delete_redis_keys(cache_client, [redis_key])
            return None

        logger.info("Cache - Redis hit %s", cache_key)
        return _clone_datatree(dataset)

    def set(
        self, cache_key: CacheKey, normalized_path: str, data: xarray.DataTree
    ) -> None:
        """Write a datatree into Redis."""

        cached_copy = _clone_datatree(data)
        cache_client = self._redis()
        if not cache_client:
            return

        try:
            payload = self._serialize(cached_copy)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cache - serialization failed for %s: %s", cache_key, exc)
            return

        if payload is None:
            return

        if (
            self._redis_max_payload is not None
            and len(payload) > self._redis_max_payload
        ):
            logger.info(
                "Cache - payload for %s skipped (size %s > limit %s)",
                cache_key,
                len(payload),
                self._redis_max_payload,
            )
            return

        ttl = self._redis_ttl()
        kwargs: dict[str, Any] = {"ex": ttl} if ttl else {}
        redis_key = _redis_key(cache_key)
        try:
            cache_client.set(redis_key, payload, **kwargs)
            self._record_cache_key(cache_client, redis_key)
        except RedisErrorType as exc:  # pragma: nocover - network failures
            logger.warning("Cache - Redis set failed for %s: %s", cache_key, exc)

    def invalidate(
        self, normalized_path: str, cache_key: CacheKey | None = None
    ) -> None:
        """Purge cached entries matching the path or specific key."""

        cache_client = self._redis()
        if not cache_client:
            return

        if cache_key:
            redis_key = _redis_key(cache_key)
            self._delete_redis_keys(cache_client, [redis_key])
        else:
            self._delete_dataset_keys(cache_client, normalized_path)

    def _delete_dataset_keys(self, cache_client: Any, normalized_path: str) -> None:
        pattern = _dataset_pattern(normalized_path)
        delete_batch: list[str] = []
        try:
            for key in self._scan_keys(cache_client, pattern):
                delete_batch.append(key)
                if len(delete_batch) >= SCAN_BATCH_SIZE:
                    self._delete_redis_keys(cache_client, delete_batch)
                    delete_batch.clear()
        except RedisErrorType as exc:  # pragma: nocover - best effort cleanup
            logger.warning("Cache - Redis scan failed for %s: %s", normalized_path, exc)
            return

        if delete_batch:
            self._delete_redis_keys(cache_client, delete_batch)

    def _scan_keys(self, cache_client: Any, pattern: str):
        scan = getattr(cache_client, "scan", None)
        if callable(scan):
            cursor: int | str = 0
            while True:
                cursor, keys = scan(cursor=cursor, match=pattern, count=SCAN_BATCH_SIZE)
                for key in keys:
                    yield self._coerce_redis_key(key)
                if cursor in (0, "0"):
                    break
            return

        scan_iter = getattr(cache_client, "scan_iter", None)
        if not callable(scan_iter):
            raise RedisErrorType("Redis client missing SCAN support")
        for key in scan_iter(match=pattern):
            yield self._coerce_redis_key(key)

    @staticmethod
    def _coerce_redis_key(key: bytes | str) -> str:
        return key.decode("utf-8") if isinstance(key, bytes) else key

    def _delete_redis_keys(
        self, cache_client: Any, keys: Iterable[bytes | str]
    ) -> None:
        targets = tuple(self._coerce_redis_key(key) for key in keys if key)
        if not targets:
            return
        try:
            cache_client.delete(*targets)
        except RedisErrorType as exc:  # pragma: nocover - best effort cleanup
            logger.warning("Cache - Redis delete failed for %s: %s", targets, exc)
            return
        if not self._max_items:
            return
        try:
            cache_client.zrem(self._redis_index_key, *targets)
        except RedisErrorType as exc:  # pragma: nocover - best effort cleanup
            logger.warning(
                "Cache - Redis index cleanup failed for %s: %s", targets, exc
            )

    def _record_cache_key(self, cache_client: Any, redis_key: str) -> None:
        if not self._max_items:
            return
        try:
            cache_client.zadd(self._redis_index_key, {redis_key: time.time()})
            overflow = cache_client.zcard(self._redis_index_key) - self._max_items
            if overflow > 0:
                evicted = cache_client.zpopmin(self._redis_index_key, overflow)
                if evicted:
                    self._delete_redis_keys(cache_client, (key for key, _ in evicted))
        except RedisErrorType as exc:  # pragma: nocover - best effort cleanup
            logger.warning("Cache - Redis eviction bookkeeping failed: %s", exc)

    def _serialize(self, tree: xarray.DataTree) -> bytes | None:
        if self._redis_secret is None:
            return None
        payload = pickle.dumps(tree, protocol=pickle.HIGHEST_PROTOCOL)
        compressed = zlib.compress(payload)
        digest = hmac.new(self._redis_secret, compressed, hashlib.sha256).digest()
        return digest + compressed

    def _deserialize(self, payload: bytes) -> xarray.DataTree | None:
        if self._redis_secret is None:
            return None
        if len(payload) <= DIGEST_SIZE:
            raise ValueError("Cache payload shorter than digest")
        digest = payload[:DIGEST_SIZE]
        compressed = payload[DIGEST_SIZE:]
        expected = hmac.new(self._redis_secret, compressed, hashlib.sha256).digest()
        if not hmac.compare_digest(digest, expected):
            raise ValueError("Cache payload failed HMAC validation")
        raw = zlib.decompress(compressed)
        return pickle.loads(raw)


_cache_settings = CacheSettings()
DATASET_CACHE = DatasetCache.from_settings(_cache_settings)


def invalidate_open_dataset_cache(src_path: str, **kwargs: Any) -> None:
    """Helper to drop cache entries tied to an open_dataset call."""

    normalized_path, _ = normalize_src_path(src_path)
    cache_key = build_dataset_cache_key(normalized_path, kwargs) if kwargs else None
    DATASET_CACHE.invalidate(normalized_path, cache_key)
