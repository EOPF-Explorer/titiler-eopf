"""titiler.eopf tests configuration."""

import os
import shutil
from threading import Thread
from typing import Any, Generator

import jinja2
import pytest
from fakeredis import TcpFakeServer
from rasterio.io import MemoryFile
from starlette.testclient import TestClient

from .create_multiscale_fixture import create_geozarr_fixture

FIXTURES_DIRECTORY = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture(scope="session")
def redis_host() -> Generator[str, Any, Any]:
    """FakeRedis fixture."""
    server_address = ("127.0.0.1", 6379)  # Use non-standard port to avoid conflicts
    server = TcpFakeServer(server_address, server_type="redis")
    t = Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield server_address[0]
    server.shutdown()
    server.server_close()
    t.join()


@pytest.fixture(
    params=[
        # "v0",
        "v1",
    ],
    scope="session",
)
def geozarr(request):
    """Create GeoZarr v1 fixture."""
    version = request.param
    collection_dir = os.path.join(FIXTURES_DIRECTORY, "eopf")
    geozarr = os.path.join(collection_dir, f"geozarr_{version}.zarr")
    create_geozarr_fixture(geozarr, version=version)
    yield ("eopf", f"geozarr_{version}")
    if os.path.exists(collection_dir):
        shutil.rmtree(collection_dir)


@pytest.fixture
def geozarr_dataset(geozarr):
    """GeoZarr dataset path."""
    collection, item = geozarr
    return os.path.join(FIXTURES_DIRECTORY, collection, f"{item}.zarr")


@pytest.fixture
def geozarr_stac(geozarr_dataset):
    """Create GeoZARR STAC Item."""
    env = jinja2.Environment(
        loader=jinja2.ChoiceLoader(
            [
                jinja2.FileSystemLoader(FIXTURES_DIRECTORY),
            ]
        )
    )
    template = env.get_template("item.json")
    return template.render(store_url=f"file://{geozarr_dataset}")


@pytest.fixture
def geozarr_3d():
    """Create GeoZarr v1 with time dimension fixture."""
    collection_dir = os.path.join(FIXTURES_DIRECTORY, "eopf3d")
    geozarr = os.path.join(collection_dir, "geozarr_with_time.zarr")
    create_geozarr_fixture(geozarr, version="v1", with_time=True)
    yield ("eopf3d", "geozarr_with_time")
    if os.path.exists(collection_dir):
        shutil.rmtree(collection_dir)


@pytest.fixture
def geozarr_3d_dataset(geozarr_3d):
    """GeoZarr dataset path."""
    collection, item = geozarr_3d
    return os.path.join(FIXTURES_DIRECTORY, collection, f"{item}.zarr")


@pytest.fixture
def geozarr_3d_stac(geozarr_3d_dataset):
    """Create GeoZARR STAC Item."""
    env = jinja2.Environment(
        loader=jinja2.ChoiceLoader(
            [
                jinja2.FileSystemLoader(FIXTURES_DIRECTORY),
            ]
        )
    )
    template = env.get_template("item.json")
    return template.render(store_url=f"file://{geozarr_3d_dataset}")


@pytest.fixture(autouse=True)
def set_env(redis_host, monkeypatch) -> Generator[TestClient, Any, Any]:
    """Set env variables for tests"""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "jqt")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "rde")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", "/tmp/noconfigheere")

    # Fake data store - override any .env file settings
    monkeypatch.setenv("TITILER_EOPF_STORE_SCHEME", "file")
    monkeypatch.setenv("TITILER_EOPF_STORE_HOST", os.path.dirname(__file__))
    monkeypatch.setenv("TITILER_EOPF_STORE_PATH", "fixtures")
    monkeypatch.setenv(
        "TITILER_EOPF_STORE_URL", f"file://{os.path.dirname(__file__)}/fixtures"
    )

    # Redis Cache
    monkeypatch.setenv("TITILER_EOPF_CACHE_HOST", redis_host)
    monkeypatch.setenv("TITILER_EOPF_CACHE_ENABLE", "TRUE")

    # STAC API
    monkeypatch.setenv("TITILER_EOPF_STAC_API_URL", "https://fake.api.io/stac")


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
