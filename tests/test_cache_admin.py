"""Cache admin API: kill switch, bearer auth, input bounds, namespace scoping."""

import asyncio
import importlib
import logging

import boto3
import fakeredis
import obstore
import pytest
import redis
from fastapi import FastAPI
from pydantic import SecretStr, ValidationError
from starlette.testclient import TestClient

from titiler.cache import TileCacheMiddleware
from titiler.cache.admin import create_cache_admin_router
from titiler.cache.backends.base import CacheBackendUnavailable
from titiler.cache.backends.redis import RedisCacheBackend
from titiler.cache.backends.s3 import S3StorageBackend
from titiler.cache.backends.s3_redis import S3RedisCacheBackend
from titiler.cache.utils import CacheKeyGenerator

TOKEN = "s3cret-token-0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
ADMIN_ENV = ("ENABLE", "TOKEN", "PREFIX")


class MockCacheBackend:
    """Mirrors the real backends: invalidation goes through clear_pattern."""

    def __init__(self, healthy=True, fail_on=None):
        """Init."""
        self.cleared = []
        self.healthy = healthy
        self.fail_on = fail_on

    async def clear_pattern(self, pattern: str) -> int:
        """Record the pattern, or raise for `fail_on`."""
        if pattern == self.fail_on:
            raise RuntimeError("boom")
        self.cleared.append(pattern)
        return 1

    async def health_check(self):
        """Report backend health."""
        return {"status": "connected" if self.healthy else "disconnected"}

    async def get_stats(self):
        """Stats."""
        return {"hit_rate": 1.0}


def _admin_client(backend, **kwargs):
    app = FastAPI()
    app.include_router(
        create_cache_admin_router(
            backend,
            CacheKeyGenerator(namespace="test"),
            token=SecretStr(TOKEN),
            **kwargs,
        )
    )
    return TestClient(app)


@pytest.fixture
def backend():
    """Mock backend."""
    return MockCacheBackend()


@pytest.fixture
def admin_client(backend):
    """App with only the admin router mounted."""
    return _admin_client(backend)


def _reload_main():
    import titiler.eopf.main

    return importlib.reload(titiler.eopf.main).app


@pytest.fixture
def main_app_with_env(monkeypatch):
    """Reload titiler.eopf.main under extra env vars, restore it afterwards."""

    def _make(**env):
        for k in ADMIN_ENV:
            monkeypatch.delenv(f"TITILER_EOPF_CACHE_ADMIN_{k}", raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        return TestClient(_reload_main())

    yield _make
    for k in ADMIN_ENV:
        monkeypatch.delenv(f"TITILER_EOPF_CACHE_ADMIN_{k}", raising=False)
    monkeypatch.setenv("TITILER_EOPF_CACHE_ENABLE", "TRUE")
    _reload_main()


# --- mounting decisions in titiler.eopf.main -------------------------------


def test_admin_disabled_by_default(app):
    """Default config: admin routes are not mounted nor documented."""
    assert app.get("/admin/cache/status").status_code == 404
    resp = app.post("/admin/cache/invalidate", json={"patterns": ["*"]})
    assert resp.status_code == 404
    paths = app.get("/api").json()["paths"]
    assert not any(p.startswith("/admin") for p in paths)


def test_token_without_enable_is_not_mounted(main_app_with_env):
    """A token alone does not turn the API on."""
    client = main_app_with_env(TITILER_EOPF_CACHE_ADMIN_TOKEN=TOKEN)
    assert client.get("/admin/cache/status", headers=AUTH).status_code == 404


@pytest.mark.parametrize("token", [None, "", "   \n", "too-short"])
def test_enabled_with_bad_token_is_not_mounted(main_app_with_env, token):
    """Enabled with a missing/blank/short token: fail closed, tiles still up."""
    env = {"TITILER_EOPF_CACHE_ADMIN_ENABLE": "true"}
    if token is not None:
        env["TITILER_EOPF_CACHE_ADMIN_TOKEN"] = token
    client = main_app_with_env(**env)
    assert client.get("/admin/cache/status").status_code == 404
    assert client.get("/_mgmt/ping").status_code == 200


@pytest.mark.parametrize("prefix", ["", "/", "admin", "/admin/"])
def test_enabled_with_bad_prefix_is_not_mounted(main_app_with_env, prefix, caplog):
    """A bad prefix is logged and skipped, never an import-time crash."""
    with caplog.at_level(logging.ERROR, logger="titiler.eopf.main"):
        client = main_app_with_env(
            TITILER_EOPF_CACHE_ADMIN_ENABLE="true",
            TITILER_EOPF_CACHE_ADMIN_TOKEN=TOKEN,
            TITILER_EOPF_CACHE_ADMIN_PREFIX=prefix,
        )
    assert "Cache admin API NOT mounted" in caplog.text
    assert client.get("/_mgmt/ping").status_code == 200
    assert client.get("/admin/cache/status", headers=AUTH).status_code == 404


def test_enabled_with_cache_off_warns(main_app_with_env, caplog):
    """ENABLE + token with the cache off: nothing mounted, and it says why."""
    with caplog.at_level(logging.WARNING, logger="titiler.eopf.main"):
        client = main_app_with_env(
            TITILER_EOPF_CACHE_ENABLE="false",
            TITILER_EOPF_CACHE_ADMIN_ENABLE="true",
            TITILER_EOPF_CACHE_ADMIN_TOKEN=TOKEN,
        )
    assert "the cache is disabled" in caplog.text
    assert client.get("/admin/cache/status", headers=AUTH).status_code == 404


def test_admin_enabled_with_token(main_app_with_env):
    """Enabled with token: mounted at the configured prefix, auth enforced."""
    client = main_app_with_env(
        TITILER_EOPF_CACHE_ADMIN_ENABLE="true",
        # trailing newline as produced by `kubectl create secret --from-file`
        TITILER_EOPF_CACHE_ADMIN_TOKEN=f"{TOKEN}\n",
        TITILER_EOPF_CACHE_ADMIN_PREFIX="/cache-admin",
    )
    assert client.get("/admin/cache/status").status_code == 404
    assert client.get("/cache-admin/status").status_code == 401
    resp = client.get("/cache-admin/status", headers=AUTH)
    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "no-store"
    paths = client.get("/api").json()["paths"]
    assert not any(p.startswith("/cache-admin") for p in paths)


@pytest.mark.parametrize(
    "tile_env,tile_ttl", [({"TITILER_EOPF_CACHE_TILE_TTL": "600"}, 600), ({}, 60)]
)
def test_tile_ttl_env_reaches_the_middleware(
    main_app_with_env, monkeypatch, tile_env, tile_ttl
):
    """The deployed app stores tiles for TILE_TTL, or for DEFAULT_TTL if unset."""
    monkeypatch.delenv("TITILER_EOPF_CACHE_TILE_TTL", raising=False)
    client = main_app_with_env(TITILER_EOPF_CACHE_DEFAULT_TTL="60", **tile_env)
    # the app is built: drop the vars so the fixture's teardown reload doesn't keep them
    for k in ("DEFAULT_TTL", "TILE_TTL"):
        monkeypatch.delenv(f"TITILER_EOPF_CACHE_{k}", raising=False)

    (mw,) = [m for m in client.app.user_middleware if m.cls is TileCacheMiddleware]
    middleware = mw.cls(app=None, **mw.kwargs)
    assert (middleware.default_ttl, middleware.tile_ttl) == (60, tile_ttl)


def test_mgmt_cache_is_minimal(app):
    """Public /_mgmt/cache exposes no connection details or raw errors."""
    body = app.get("/_mgmt/cache").json()["cache"]
    assert set(body) <= {"status", "healthy"}


def test_tile_ttl_must_be_positive(monkeypatch):
    """TILE_TTL=0 would silently stop tile caching: refused at startup."""
    from titiler.eopf.settings import EOPFCacheSettings

    monkeypatch.setenv("TITILER_EOPF_CACHE_TILE_TTL", "0")
    with pytest.raises(ValidationError):
        EOPFCacheSettings()


def test_settings_errors_hide_input(monkeypatch):
    """A settings ValidationError must not echo the admin token."""
    from titiler.eopf.settings import EOPFCacheSettings

    # short token: pydantic truncates long input reprs, which would hide a leak
    monkeypatch.setenv("TITILER_EOPF_CACHE_ADMIN_TOKEN", "tok-abc")
    monkeypatch.setenv("TITILER_EOPF_CACHE_BACKEND", "nope")
    with pytest.raises(ValidationError) as exc:
        EOPFCacheSettings()
    assert "Unsupported cache backend" in str(exc.value)
    assert "tok-abc" not in str(exc.value)


# --- the router itself ------------------------------------------------------


@pytest.mark.parametrize("token", ["", "   ", "x" * 15, "é" * 20, "\udcff" * 20])
def test_router_refuses_bad_token(backend, token):
    """The router can never be built with an unusable token."""
    with pytest.raises(ValueError):
        create_cache_admin_router(
            backend, CacheKeyGenerator(namespace="test"), token=SecretStr(token)
        )


@pytest.mark.parametrize("prefix", ["", "/", "admin", "/admin/"])
def test_router_refuses_bad_prefix(backend, prefix):
    """Bad prefixes raise ValueError (not FastAPI's AssertionError)."""
    with pytest.raises(ValueError):
        _admin_client(backend, prefix=prefix)


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong"},
        {"Authorization": f"Basic {TOKEN}"},
        {"Authorization": TOKEN},
    ],
)
def test_bad_or_missing_token_rejected(admin_client, backend, headers):
    """Missing/wrong credentials get 401 and nothing is invalidated."""
    resp = admin_client.get("/admin/cache/status", headers=headers)
    assert resp.status_code == 401
    assert resp.headers["Cache-Control"] == "no-store"
    resp = admin_client.post(
        "/admin/cache/invalidate", json={"patterns": ["*"]}, headers=headers
    )
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"] == "Bearer"
    assert backend.cleared == []


def test_correct_token(admin_client, backend):
    """Correct bearer token reaches the endpoints; patterns get namespaced."""
    resp = admin_client.get("/admin/cache/status", headers=AUTH)
    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.json()["namespace"] == "test"

    resp = admin_client.post(
        "/admin/cache/invalidate",
        json={"patterns": ["tile:*", "test:info:*"]},
        headers=AUTH,
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["invalidated_count"] == 2
    assert backend.cleared == ["test:tile:*", "test:info:*"]


@pytest.mark.parametrize(
    "patterns",
    [
        [],
        ["x"] * 101,
        ["x" * 257],
        [""],
        ["tile[js]on:*"],
        ["x]"],
        ["a\\*"],
        ["caf\u00e9:*"],
        ["x\ny"],
    ],
)
def test_invalidate_input_bounds(admin_client, backend, patterns):
    """Oversize, empty, [ ] \\, non-ASCII or control characters: rejected."""
    resp = admin_client.post(
        "/admin/cache/invalidate", json={"patterns": patterns}, headers=AUTH
    )
    assert resp.status_code == 422
    assert backend.cleared == []


def test_invalidate_reports_failed_pattern():
    """A backend exception marks that pattern failed and success false."""
    backend = MockCacheBackend(fail_on="test:bad:*")
    resp = _admin_client(backend).post(
        "/admin/cache/invalidate", json={"patterns": ["bad:*", "ok:*"]}, headers=AUTH
    )
    body = resp.json()
    assert body["success"] is False
    assert body["failed_patterns"] == ["bad:*"]
    assert body["invalidated_count"] == 1


def test_invalidate_reports_unhealthy_backend():
    """An unreachable backend is a failure, not a silent 0-key success."""
    backend = MockCacheBackend(healthy=False)
    resp = _admin_client(backend).post(
        "/admin/cache/invalidate", json={"patterns": ["*"]}, headers=AUTH
    )
    body = resp.json()
    assert body["success"] is False
    assert body["failed_patterns"] == ["*"]
    assert backend.cleared == []


@pytest.fixture
def s3_redis(s3_endpoint):
    """s3-redis composite on fakeredis and a fresh moto bucket."""
    bucket = "s3-redis-cache"
    s3 = boto3.client(
        "s3",
        region_name="us-east-1",
        endpoint_url=s3_endpoint,
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    s3.create_bucket(Bucket=bucket)
    redis_backend = RedisCacheBackend(host="unused")
    redis_backend._client = fakeredis.FakeAsyncRedis()
    s3_backend = S3StorageBackend(
        bucket=bucket,
        endpoint_url=s3_endpoint,
        access_key_id="testing",
        secret_access_key="testing",
    )
    yield S3RedisCacheBackend(redis_backend, s3_backend)
    for obj in s3.list_objects_v2(Bucket=bucket).get("Contents", []):
        s3.delete_object(Bucket=bucket, Key=obj["Key"])
    s3.delete_bucket(Bucket=bucket)


@pytest.mark.parametrize("failing", ["s3", "redis"])
def test_invalidate_reports_failed_delete_on_s3_redis(s3_redis, monkeypatch, failing):
    """s3-redis: a delete that fails on either side fails the pattern."""
    assert asyncio.run(s3_redis.set("test:tilejson:coll:x", b"x")) is True

    async def connected():
        return {"status": "connected"}

    async def failing_delete(*args, **kwargs):
        raise OSError(f"{failing} refused the delete")

    # fakeredis has no INFO, which health_check uses.
    s3_redis.health_check = connected
    if failing == "s3":
        monkeypatch.setattr(obstore, "delete_async", failing_delete)
    else:
        monkeypatch.setattr(s3_redis.redis._client, "delete", failing_delete)
    resp = _admin_client(s3_redis).post(
        "/admin/cache/invalidate", json={"patterns": ["tilejson:*"]}, headers=AUTH
    )
    body = resp.json()
    assert body["success"] is False
    assert body["failed_patterns"] == ["tilejson:*"]
    if failing == "s3":  # S3 goes first: a failed pattern is still being served
        assert asyncio.run(s3_redis.exists("test:tilejson:coll:x"))


def test_redis_clear_pattern_raises_when_unavailable(monkeypatch):
    """An unreachable Redis fails the clear instead of reporting 0 deleted."""
    backend = RedisCacheBackend(host="unused")

    async def unavailable():
        raise CacheBackendUnavailable("Redis unavailable")

    monkeypatch.setattr(backend, "_get_client", unavailable)
    with pytest.raises(CacheBackendUnavailable):
        asyncio.run(backend.clear_pattern("test:*"))


def test_s3_redis_counts_only_entries_still_served(s3_redis):
    """An S3 object whose Redis metadata already expired is not counted."""

    async def run():
        await s3_redis.set("test:tilejson:coll:live", b"x")
        await s3_redis.set("test:tilejson:coll:expired", b"x")
        await s3_redis.redis._client.delete("meta:test:tilejson:coll:expired")
        return await s3_redis.clear_pattern("test:tilejson:*")

    assert asyncio.run(run()) == 1


def test_invalidate_star_stays_in_namespace_on_redis(redis_host):
    """`*` on the real Redis backend leaves keys of other namespaces alone."""
    sync = redis.Redis(host=redis_host, port=6379)
    sync.set("test:tile:a", b"1")
    sync.set("test:info:b", b"1")
    sync.set("other-app:tile:a", b"1")
    sync.set("unrelated", b"1")
    try:
        redis_backend = RedisCacheBackend(host=redis_host, port=6379)

        # fakeredis' TCP server has no INFO command, which health_check uses;
        # clear_pattern (the code under test) still runs against fakeredis.
        async def connected():
            return {"status": "connected"}

        redis_backend.health_check = connected
        client = _admin_client(redis_backend)
        resp = client.post(
            "/admin/cache/invalidate", json={"patterns": ["*"]}, headers=AUTH
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["invalidated_count"] == 2
        assert not sync.exists("test:tile:a", "test:info:b")
        assert sync.exists("other-app:tile:a", "unrelated") == 2
    finally:
        sync.delete("test:tile:a", "test:info:b", "other-app:tile:a", "unrelated")


BUCKET = "shared-cache"
UNRELATED = ["source/product.zarr/zarr.json", "other-data/x.bin", "cache/y.bin"]


@pytest.mark.parametrize("composite", [False, True], ids=["s3", "s3-redis"])
@pytest.mark.parametrize(
    "pattern",
    [
        "*",
        "?*",
        "**",
        "tiles*",
        "tile*",
        "titiler-eopf*",
        "titiler-eopf-staging:*",
        "titiler-eopf:tile:*",
        "../*",
        ":*",
        "/*",
        " ",
    ],
)
def test_invalidate_stays_in_namespace_on_s3(s3_endpoint, composite, pattern):
    """No pattern deletes S3 objects outside `<namespace>/`, even in a shared bucket.

    `titiler-eopf` is a string prefix of `titiler-eopf-staging`; the staging
    objects must survive too.
    """
    s3 = boto3.client(
        "s3",
        region_name="us-east-1",
        endpoint_url=s3_endpoint,
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    s3.create_bucket(Bucket=BUCKET)
    try:
        for key in UNRELATED:
            s3.put_object(Bucket=BUCKET, Key=key, Body=b"keep")

        server = fakeredis.FakeServer()

        def make_backend(db):
            backend = S3StorageBackend(
                bucket=BUCKET,
                endpoint_url=s3_endpoint,
                access_key_id="testing",
                secret_access_key="testing",
            )
            if not composite:
                return backend
            redis_backend = RedisCacheBackend(host="unused")
            redis_backend._client = fakeredis.FakeAsyncRedis(server=server, db=db)
            return S3RedisCacheBackend(redis_backend, backend)

        prod, staging = make_backend(0), make_backend(1)
        prod_keys = CacheKeyGenerator(namespace="titiler-eopf")
        staging_keys = CacheKeyGenerator(namespace="titiler-eopf-staging")
        tile = "/collections/C/items/I/tiles/WebMercatorQuad/10/1/2.png"
        info = "/collections/C/items/I/info"

        async def seed():
            await prod.set(prod_keys.from_path_and_params(info, {}, "info"), b"p")
            await prod.set(prod_keys.from_path_and_params(tile, {}, "tile"), b"p")
            for path, cache_type in ((info, "info"), (tile, "tile")):
                key = staging_keys.from_path_and_params(path, {"s": "1"}, cache_type)
                await staging.set(key, b"s")

        asyncio.run(seed())

        def listing():
            return {o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET)["Contents"]}

        outside = {k for k in listing() if not k.startswith("titiler-eopf/")}
        assert any(k.startswith("titiler-eopf-staging/") for k in outside)

        async def connected():
            return {"status": "connected"}

        # fakeredis has no INFO, which health_check uses (see above).
        prod.health_check = connected
        app = FastAPI()
        app.include_router(
            create_cache_admin_router(prod, prod_keys, token=SecretStr(TOKEN))
        )
        resp = TestClient(app).post(
            "/admin/cache/invalidate", json={"patterns": [pattern]}, headers=AUTH
        )
        assert resp.status_code == 200
        assert outside <= listing()
    finally:
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET):
            for obj in page.get("Contents", []):
                s3.delete_object(Bucket=BUCKET, Key=obj["Key"])
        s3.delete_bucket(Bucket=BUCKET)
