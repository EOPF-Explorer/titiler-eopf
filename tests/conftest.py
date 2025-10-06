"""titiler.eopf tests configuration."""

import os
from typing import Any

import pytest
from rasterio.io import MemoryFile
from starlette.testclient import TestClient


@pytest.fixture
def set_env(monkeypatch):
    """Set Env variables."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "jqt")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "rde")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", "/tmp/noconfigheere")

    # Fake data store
    monkeypatch.setenv("TITILER_EOPF_STORE_SCHEME", "file")
    monkeypatch.setenv("TITILER_EOPF_STORE_HOST", os.path.dirname(__file__))
    monkeypatch.setenv("TITILER_EOPF_STORE_PATH", "fixtures")


@pytest.fixture(autouse=True)
def app(set_env) -> TestClient:
    """Create App."""
    from titiler.eopf.main import app

    return TestClient(app)


def parse_img(content: bytes) -> dict[Any, Any]:
    """Read tile image and return metadata."""
    with MemoryFile(content) as mem:
        with mem.open() as dst:
            return dst.profile
