"""Deterministic performance invariants for the version-aware datatree cache.

These assert exact side-effect *counts* (HEADs, store builds, datatree opens),
not wall-clock timing, so they fail loudly the moment a perf guard regresses —
the probe throttle, the `_get_store` memo, or the bounded in-process memo —
regardless of machine speed. They complement the wall-clock benchmark suite.

Correctness behaviour for the same cache lives in `tests/test_open_dataset_cache.py`.
"""

import pytest

import titiler.eopf.reader as reader_mod
from titiler.eopf.reader import cache_settings, open_dataset


def _reset_all() -> None:
    open_dataset.cache_clear()
    cache_settings.cache_clear()


@pytest.fixture(autouse=True)
def reset_caches():
    """Reset every memo around each test (redis disabled by default env)."""
    _reset_all()
    yield
    _reset_all()


def _count_opens(monkeypatch) -> list[int]:
    """Patch `_open_from_store` to count real opens; returns a 1-element counter."""
    counter = [0]
    real_open = reader_mod._open_from_store

    def counting(src_path: str):
        counter[0] += 1
        return real_open(src_path)

    monkeypatch.setattr(reader_mod, "_open_from_store", counting)
    return counter


def test_version_probe_throttled_within_ttl(geozarr_dataset, monkeypatch):
    """N opens within version_probe_ttl issue a single HEAD; a re-probe occurs after the window."""
    head_calls = [0]
    real_head = reader_mod.obstore.head

    def counting_head(store, path):
        head_calls[0] += 1
        return real_head(store, path)

    monkeypatch.setattr(reader_mod.obstore, "head", counting_head)
    monkeypatch.setenv("TITILER_EOPF_CACHE_VERSION_PROBE_TTL", "5")
    cache_settings.cache_clear()

    clock = [1000.0]
    monkeypatch.setattr(reader_mod.time, "monotonic", lambda: clock[0])
    open_dataset.cache_clear()

    for _ in range(5):
        open_dataset(geozarr_dataset)
    assert head_calls[0] == 1

    clock[0] = 1010.0  # advance beyond the 5s window
    open_dataset(geozarr_dataset)
    assert head_calls[0] == 2


def test_store_built_once_across_opens(geozarr_dataset, monkeypatch):
    """The obstore store is constructed once per path (no per-request rebuild)."""
    build_calls = [0]
    real_from_url = reader_mod.obstore.store.from_url

    def counting_from_url(url, *args, **kwargs):
        build_calls[0] += 1
        return real_from_url(url, *args, **kwargs)

    monkeypatch.setattr(reader_mod.obstore.store, "from_url", counting_from_url)
    open_dataset.cache_clear()

    for _ in range(4):
        open_dataset(geozarr_dataset)

    assert build_calls[0] == 1


def test_no_reopen_on_stable_token_reopen_on_change(geozarr_dataset, monkeypatch):
    """A stable token reuses the in-process tree; a changed token defeats the memo."""
    monkeypatch.setattr(reader_mod, "_store_version_cached", lambda src: "stable")
    opens = _count_opens(monkeypatch)
    open_dataset.cache_clear()

    for _ in range(3):
        open_dataset(geozarr_dataset)
    assert opens[0] == 1

    monkeypatch.setattr(reader_mod, "_store_version_cached", lambda src: "changed")
    open_dataset(geozarr_dataset)
    assert opens[0] == 2


def test_dataset_memo_is_bounded():
    """The in-process datatree memo is bounded (regression guard vs unbounded @cache)."""
    info = reader_mod._open_dataset_cached.cache_info()
    assert info.maxsize is not None and info.maxsize > 0
