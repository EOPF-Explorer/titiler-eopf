"""Unit tests for the dataset cache helper."""

from __future__ import annotations

import fnmatch

import numpy
import xarray

from titiler.eopf import dataset_cache as dataset_cache_module
from titiler.eopf.dataset_cache import (
    DatasetCache,
    build_dataset_cache_key,
    normalize_src_path,
)


class DummyRedis:
    """Small in-memory stub matching the subset of Redis APIs used by the cache."""

    def __init__(self) -> None:
        """Create a new empty stub."""
        self.store: dict[str, bytes] = {}
        self.sorted_sets: dict[str, dict[str, float]] = {}

    def set(self, key: str, value: bytes, **_: object) -> None:
        """Store a key/value pair."""
        self.store[key] = value

    def get(self, key: str) -> bytes | None:
        """Return the stored payload for a key, if any."""
        return self.store.get(key)

    def delete(self, *keys: object) -> int:
        """Delete one or more keys, returning the count of removed entries."""
        removed = 0
        for key in keys:
            normalized = self._as_str(key)
            removed += 1 if self.store.pop(normalized, None) is not None else 0
        return removed

    def scan_iter(self, match: str | None = None):
        """Yield keys matching a glob-style pattern."""
        pattern = match or "*"
        for key in list(self.store):
            if fnmatch.fnmatch(key, pattern):
                yield key

    def zadd(self, key: str, mapping: dict[str, float]) -> None:
        """Add/update sorted set members."""
        zset = self.sorted_sets.setdefault(key, {})
        for member, score in mapping.items():
            zset[self._as_str(member)] = score

    def zcard(self, key: str) -> int:
        """Return the cardinality of a sorted set."""
        return len(self.sorted_sets.get(key, {}))

    def zpopmin(self, key: str, count: int):  # noqa: D401 - match redis signature
        """Pop and return the lowest-score members."""
        zset = self.sorted_sets.get(key, {})
        items = sorted(zset.items(), key=lambda item: item[1])[:count]
        for member, _ in items:
            zset.pop(member, None)
        return items

    def zrem(self, key: str, *members: object) -> int:
        """Remove members from a sorted set."""
        zset = self.sorted_sets.get(key, {})
        removed = 0
        for member in members:
            normalized = self._as_str(member)
            if normalized in zset:
                zset.pop(normalized, None)
                removed += 1
        return removed

    @staticmethod
    def _as_str(value: bytes | str | object) -> str:
        """Normalize Redis key representations to strings."""
        if isinstance(value, bytes):
            return value.decode("utf-8")
        if isinstance(value, str):
            return value
        raise TypeError(f"Unsupported key type: {type(value)}")


def _make_tree() -> xarray.DataTree:
    """Create a small datatree payload."""
    ds = xarray.Dataset({"foo": ("x", numpy.arange(3))})
    return xarray.DataTree.from_dict({"/": ds})


def _cache(**overrides: object) -> DatasetCache:
    """Create a DatasetCache wired with an in-memory Redis stub."""
    cache = DatasetCache(
        ttl_seconds=60,
        ttl_jitter_ratio=0.1,
        max_items=overrides.get("max_items", 2),
        enable_redis=True,
        redis_host="localhost",
        redis_port=6379,
        redis_username=None,
        redis_password=None,
        redis_db=0,
        redis_ssl=False,
        redis_hmac_secret="secret",
        redis_max_payload_bytes=overrides.get("redis_max_payload_bytes"),
    )
    cache._redis_client = DummyRedis()  # type: ignore[attr-defined]
    cache._redis_config = None  # type: ignore[attr-defined]
    return cache


def test_cache_key_masks_internal_paths() -> None:
    """Cache keys must not embed raw filesystem paths."""
    normalized, _ = normalize_src_path("tests/fixtures/data.zarr")
    cache_key = build_dataset_cache_key(normalized, {})
    assert "/" not in cache_key


def test_cache_key_stable_for_callable_kwargs() -> None:
    """Callable kwargs should produce stable digests."""
    normalized, _ = normalize_src_path("tests/fixtures/data.zarr")

    def build_key() -> str:
        return build_dataset_cache_key(normalized, {"fn": lambda value: value})

    assert build_key() == build_key()


def test_cache_payload_limit_prevents_large_writes() -> None:
    """Oversized payloads should be skipped before writing to Redis."""
    cache = _cache(redis_max_payload_bytes=32)
    normalized, _ = normalize_src_path("tests/fixtures/data.zarr")
    cache_key = build_dataset_cache_key(normalized, {})

    cache.set(cache_key, _make_tree())

    dummy: DummyRedis = cache._redis_client  # type: ignore[assignment]
    assert dummy.store == {}


def test_cache_max_items_triggers_eviction() -> None:
    """Redis index bookkeeping should enforce the max_items budget."""
    cache = _cache(max_items=1, redis_max_payload_bytes=1024 * 1024)
    normalized, _ = normalize_src_path("tests/fixtures/data.zarr")

    first_key = build_dataset_cache_key(normalized, {})
    second_key = build_dataset_cache_key(normalized, {"variant": 1})

    tree = _make_tree()
    cache.set(first_key, tree)
    cache.set(second_key, tree)

    dummy: DummyRedis = cache._redis_client  # type: ignore[assignment]
    assert len(dummy.store) == 1
    assert list(dummy.store.keys())[0].endswith(second_key)


def test_ttl_jitter_applied(monkeypatch) -> None:
    """TTL jitter should spread expirations to avoid synchronized refreshes."""
    cache = _cache()
    delta = max(1, int(cache._ttl * cache._ttl_jitter_ratio))

    def fake_randint(_: int, __: int) -> int:  # always return positive spread
        return delta

    monkeypatch.setattr(dataset_cache_module.random, "randint", fake_randint)

    assert cache._redis_ttl() == cache._ttl + delta
