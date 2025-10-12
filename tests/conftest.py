"""titiler.eopf tests configuration."""

import os
from threading import Thread
from typing import Any, Generator

import pytest
from fakeredis import TcpFakeServer
from rasterio.io import MemoryFile
from starlette.testclient import TestClient


@pytest.fixture(scope="session")
def redis_host() -> Generator[str, Any, Any]:
    """FakeRedis fixture."""
    server_address = ("127.0.0.1", 6379)
    server = TcpFakeServer(server_address, server_type="redis")
    t = Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield server_address[0]
    server.shutdown()
    server.server_close()
    t.join()


@pytest.fixture(autouse=True)
def set_env(redis_host, monkeypatch) -> Generator[TestClient, Any, Any]:
    """Set env variables for tests"""
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

    # Redis Cache
    monkeypatch.setenv("TITILER_EOPF_CACHE_HOST", redis_host)
    monkeypatch.setenv("TITILER_EOPF_CACHE_ENABLE", "TRUE")


@pytest.fixture
def app(set_env) -> Generator[TestClient, Any, Any]:
    """Create App."""
    from titiler.eopf.main import app

    with TestClient(app) as app:
        yield app


def parse_img(content: bytes) -> dict[Any, Any]:
    """Read tile image and return metadata."""
    with MemoryFile(content) as mem:
        with mem.open() as dst:
            return dst.profile
