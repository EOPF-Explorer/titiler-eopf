"""Tests for store-version-aware datatree caching in `open_dataset`.

Covers the correctness behaviour added for issue #118: an append (changed
store-version token) must produce a new cache key and trigger a fresh read,
defeating both the Redis key and the in-process memo; a failed version probe
must fall back to the bare `src_path` key.

(The deterministic performance invariants for this caching live in
`tests/test_open_dataset_cache_perf.py`.)
"""

import fakeredis
import pytest

import titiler.eopf.reader as reader_mod
from titiler.eopf.reader import cache_settings, open_dataset


def _reset_all() -> None:
    open_dataset.cache_clear()
    cache_settings.cache_clear()


def _redis_keys(client) -> set[str]:
    return {k.decode() for k in client.keys()}


@pytest.fixture(autouse=True)
def reset_caches():
    """Reset every memo around each test (redis disabled by default env)."""
    _reset_all()
    yield
    _reset_all()


@pytest.fixture
def redis_client(monkeypatch):
    """Enable the redis cache path and inject an in-process fake client.

    Uses `fakeredis.FakeStrictRedis` (not the TCP fake server) to avoid a
    RESP2/RESP3 protocol mismatch, and patches the point where the reader builds
    its client so the version-keyed get/set runs against the fake.
    """
    monkeypatch.setenv("TITILER_EOPF_CACHE_ENABLE", "TRUE")
    monkeypatch.setenv("TITILER_EOPF_CACHE_REDIS_HOST", "localhost")
    cache_settings.cache_clear()

    fake = fakeredis.FakeStrictRedis()
    monkeypatch.setattr(reader_mod.redis, "Redis", lambda **kwargs: fake)
    yield fake


def _count_opens(monkeypatch) -> list[int]:
    """Patch `_open_from_store` to count real opens; returns a 1-element counter."""
    counter = [0]
    real_open = reader_mod._open_from_store

    def counting(src_path: str):
        counter[0] += 1
        return real_open(src_path)

    monkeypatch.setattr(reader_mod, "_open_from_store", counting)
    return counter


# --- Correctness -----------------------------------------------------------


def test_append_changes_cache_key_and_rereads(
    geozarr_dataset, redis_client, monkeypatch
):
    """A changed version token writes a new Redis key and re-reads the store."""
    versions = iter(["v1", "v2"])
    monkeypatch.setattr(reader_mod, "_store_version_cached", lambda src: next(versions))
    opens = _count_opens(monkeypatch)

    open_dataset(geozarr_dataset)  # v1 -> read + cache <path>#v1
    open_dataset(geozarr_dataset)  # v2 -> miss -> read + cache <path>#v2

    assert opens[0] == 2
    norm = reader_mod._normalize_path(geozarr_dataset)
    keys = _redis_keys(redis_client)
    assert f"{norm}#v1" in keys
    assert f"{norm}#v2" in keys


def test_version_probe_failure_falls_back_to_src_path_key(
    geozarr_dataset, redis_client, monkeypatch
):
    """When the version probe returns None, the bare src_path key is used and no error escapes."""
    monkeypatch.setattr(reader_mod, "_store_version_cached", lambda src: None)

    dt = open_dataset(geozarr_dataset)

    assert dt is not None
    norm = reader_mod._normalize_path(geozarr_dataset)
    keys = _redis_keys(redis_client)
    assert norm in keys
    assert not any("#" in k for k in keys)


def test_store_version_returns_none_on_head_failure(monkeypatch):
    """A failed HEAD never raises; it degrades to None (so the cache falls back)."""

    def boom(store, path):
        raise FileNotFoundError("no such object")

    monkeypatch.setattr(reader_mod.obstore, "head", boom)
    reader_mod._get_store.cache_clear()

    assert reader_mod._store_version("file:///tmp/does-not-exist.zarr") is None
