"""test for settings"""

import pytest
from pydantic import ValidationError
from pydantic_settings import SettingsConfigDict

from titiler.eopf.settings import DataStoreSettings


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
