"""test for settings"""

import pytest
from pydantic import ValidationError
from pydantic_settings import SettingsConfigDict

from titiler.cache import CacheRedisSettings
from titiler.eopf.settings import CacheSettings, DataStoreSettings


class IsolatedDataStoreSettings(DataStoreSettings):
    """Isolated version of DataStoreSettings that doesn't load from .env files."""

    model_config = SettingsConfigDict(
        env_prefix="TITILER_EOPF_STORE_",
        env_file=None,  # Disable .env file loading for tests
        extra="ignore",
    )


@pytest.mark.parametrize(
    "params,url",
    [
        ({"scheme": "s3", "host": "yeah/ye", "path": "yo"}, "s3://yeah/ye/yo"),
        ({"scheme": "s3", "host": "yeah/ye", "path": None}, "s3://yeah/ye"),
        ({"url": "s3://yeah/yo"}, "s3://yeah/yo"),
    ],
)
def test_datastore_settings(params, url, monkeypatch):
    """Test DataStoreSettings."""
    # Clear environment variables that might interfere with test
    monkeypatch.delenv("TITILER_EOPF_STORE_URL", raising=False)
    monkeypatch.delenv("TITILER_EOPF_STORE_SCHEME", raising=False)
    monkeypatch.delenv("TITILER_EOPF_STORE_HOST", raising=False)
    monkeypatch.delenv("TITILER_EOPF_STORE_PATH", raising=False)
    settings = IsolatedDataStoreSettings(**params)
    assert str(settings.url) == url


@pytest.mark.parametrize(
    "params",
    [
        {"scheme": "s3", "host": None, "path": "yo"},
        {"scheme": None, "host": "yeah/ye", "path": None},
        {"url": "thisisnotavalidurl", "scheme": None, "host": None, "path": None},
        {"url": None, "scheme": None, "host": None, "path": None},
    ],
)
def test_datastore_settings_error(params, monkeypatch):
    """Missing URL or scheme/host."""
    # Clear environment variables that might interfere with test
    monkeypatch.delenv("TITILER_EOPF_STORE_URL", raising=False)
    monkeypatch.delenv("TITILER_EOPF_STORE_SCHEME", raising=False)
    monkeypatch.delenv("TITILER_EOPF_STORE_HOST", raising=False)
    monkeypatch.delenv("TITILER_EOPF_STORE_PATH", raising=False)
    with pytest.raises(ValidationError):
        IsolatedDataStoreSettings(**params)


class IsolatedCacheSettings(CacheSettings):
    """Reader cache settings without .env loading."""

    model_config = SettingsConfigDict(
        env_prefix="TITILER_EOPF_CACHE_REDIS_", env_file=None, extra="ignore"
    )


class IsolatedCacheRedisSettings(CacheRedisSettings):
    """Tile-cache Redis settings without .env loading."""

    model_config = SettingsConfigDict(
        env_prefix="TITILER_EOPF_CACHE_REDIS_", env_file=None, extra="ignore"
    )


def test_reader_and_tile_cache_redis_settings_aligned(monkeypatch):
    """Reader cache and tile cache resolve the same Redis connection config.

    Both read the ``TITILER_EOPF_CACHE_REDIS_`` prefix, so host/port/db must
    resolve identically — otherwise the two caches could target different
    Redis servers or databases.
    """
    monkeypatch.setenv("TITILER_EOPF_CACHE_REDIS_HOST", "redis.example")
    monkeypatch.setenv("TITILER_EOPF_CACHE_REDIS_PORT", "6380")
    monkeypatch.setenv("TITILER_EOPF_CACHE_REDIS_DB", "3")

    reader_cache = IsolatedCacheSettings()
    tile_cache = IsolatedCacheRedisSettings()

    assert reader_cache.host == tile_cache.host == "redis.example"
    assert reader_cache.port == tile_cache.port == 6380
    assert reader_cache.db == tile_cache.db == 3
