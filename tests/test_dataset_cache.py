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
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.sorted_sets: dict[str, dict[str, float]] = {}

    def set(self, key: str, value: bytes, **_: object) -> None:
        self.store[key] = value

    def get(self, key: str) -> bytes | None:
        return self.store.get(key)

    def delete(self, *keys: object) -> int:
        removed = 0
        for key in keys:
            normalized = self._as_str(key)
            removed += 1 if self.store.pop(normalized, None) is not None else 0
        return removed

    def scan_iter(self, match: str | None = None):
        pattern = match or "*"
        for key in list(self.store):
            if fnmatch.fnmatch(key, pattern):
                yield key

    def zadd(self, key: str, mapping: dict[str, float]) -> None:
        zset = self.sorted_sets.setdefault(key, {})
        for member, score in mapping.items():
            zset[self._as_str(member)] = score

    def zcard(self, key: str) -> int:
        return len(self.sorted_sets.get(key, {}))

    def zpopmin(self, key: str, count: int):  # noqa: D401 - match redis signature
        zset = self.sorted_sets.get(key, {})
        items = sorted(zset.items(), key=lambda item: item[1])[:count]
        for member, _ in items:
            zset.pop(member, None)
        return items

    def zrem(self, key: str, *members: object) -> int:
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
        if isinstance(value, bytes):
            return value.decode("utf-8")
        if isinstance(value, str):
            return value
        raise TypeError(f"Unsupported key type: {type(value)}")


def _make_tree() -> xarray.DataTree:
    ds = xarray.Dataset({"foo": ("x", numpy.arange(3))})
    return xarray.DataTree.from_dict({"/": ds})


def _cache(**overrides: object) -> DatasetCache:
    cache = DatasetCache(
        ttl_seconds=60,
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
    normalized, _ = normalize_src_path("tests/fixtures/data.zarr")
    cache_key = build_dataset_cache_key(normalized, {})
    assert "/" not in cache_key


def test_cache_key_stable_for_callable_kwargs() -> None:
    normalized, _ = normalize_src_path("tests/fixtures/data.zarr")

    def build_key() -> str:
        return build_dataset_cache_key(normalized, {"fn": lambda value: value})

    assert build_key() == build_key()


def test_cache_payload_limit_prevents_large_writes() -> None:
    cache = _cache(redis_max_payload_bytes=32)
    normalized, _ = normalize_src_path("tests/fixtures/data.zarr")
    cache_key = build_dataset_cache_key(normalized, {})

    cache.set(cache_key, normalized, _make_tree())

    dummy: DummyRedis = cache._redis_client  # type: ignore[assignment]
    assert dummy.store == {}


def test_cache_max_items_triggers_eviction() -> None:
    cache = _cache(max_items=1, redis_max_payload_bytes=1024 * 1024)
    normalized, _ = normalize_src_path("tests/fixtures/data.zarr")

    first_key = build_dataset_cache_key(normalized, {})
    second_key = build_dataset_cache_key(normalized, {"variant": 1})

    tree = _make_tree()
    cache.set(first_key, normalized, tree)
    cache.set(second_key, normalized, tree)

    dummy: DummyRedis = cache._redis_client  # type: ignore[assignment]
    assert len(dummy.store) == 1
    assert list(dummy.store.keys())[0].endswith(second_key)


def test_ttl_jitter_applied(monkeypatch) -> None:
    cache = _cache()
    delta = max(1, int(cache._ttl * dataset_cache_module.TTL_JITTER_RATIO))

    def fake_randint(_: int, __: int) -> int:  # always return positive spread
        return delta

    monkeypatch.setattr(dataset_cache_module.random, "randint", fake_randint)

    assert cache._redis_ttl() == cache._ttl + delta
