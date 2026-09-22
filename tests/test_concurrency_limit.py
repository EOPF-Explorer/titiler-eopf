"""Shedding load must never shed the liveness probe."""

import asyncio

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from titiler.eopf.concurrency import ConcurrencyLimitMiddleware


def build_app(limit, gate):
    """An app whose tile route blocks on `gate`, so concurrency is controllable."""

    async def tile(request):
        await gate.wait()
        return PlainTextResponse("tile")

    async def ping(request):
        return PlainTextResponse("pong")

    # Wrapped directly, not via add_middleware: that returns Starlette's own outermost
    # ServerErrorMiddleware, and these tests need a handle on the limiter's counter.
    routes = [Route("/tiles/x", tile), Route("/_mgmt/ping", ping)]
    return ConcurrencyLimitMiddleware(Starlette(routes=routes), limit=limit)


def client_for(app):
    """An httpx client speaking ASGI directly to `app`."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def fill(app, client, n):
    """Hold `n` requests inside the app, blocked on its gate."""
    held = [asyncio.create_task(client.get("/tiles/x")) for _ in range(n)]
    while app.in_flight < n:
        await asyncio.sleep(0)
    return held


@pytest.mark.asyncio
async def test_under_the_limit_everything_passes():
    """Requests up to the limit are served normally."""
    gate = asyncio.Event()
    gate.set()
    async with client_for(build_app(3, gate)) as client:
        done = await asyncio.gather(*(client.get("/tiles/x") for _ in range(3)))
    assert [r.status_code for r in done] == [200, 200, 200]


@pytest.mark.asyncio
async def test_overflow_is_refused_not_queued():
    """Past the limit the answer is an immediate 503, not a wait."""
    gate = asyncio.Event()
    app = build_app(2, gate)
    async with client_for(app) as client:
        held = await fill(app, client, 2)

        refused = await client.get("/tiles/x")
        assert refused.status_code == 503
        assert refused.headers["Retry-After"] == "1"

        gate.set()
        assert [r.status_code for r in await asyncio.gather(*held)] == [200, 200]


@pytest.mark.asyncio
async def test_probe_is_never_refused():
    """At capacity, /_mgmt/ping still answers 200.

    Without this, the limiter is uvicorn's --limit-concurrency and kubelet kills the
    container under exactly the load the limit was added to survive.
    """
    gate = asyncio.Event()
    app = build_app(2, gate)
    async with client_for(app) as client:
        held = await fill(app, client, 2)

        assert (await client.get("/tiles/x")).status_code == 503  # full, for real
        assert (await client.get("/_mgmt/ping")).status_code == 200

        gate.set()
        await asyncio.gather(*held)


@pytest.mark.asyncio
async def test_probe_does_not_consume_a_slot():
    """Probes are not counted, so they cannot push the server to capacity themselves."""
    gate = asyncio.Event()
    gate.set()
    app = build_app(1, gate)
    async with client_for(app) as client:
        for _ in range(5):
            assert (await client.get("/_mgmt/ping")).status_code == 200
        assert app.in_flight == 0
        assert (await client.get("/tiles/x")).status_code == 200


@pytest.mark.asyncio
async def test_slot_is_released_when_the_route_raises():
    """A failing request must not leak its slot, or the worker wedges at capacity."""

    async def boom(request):
        raise RuntimeError("boom")

    app = ConcurrencyLimitMiddleware(
        Starlette(routes=[Route("/tiles/x", boom)]), limit=1
    )
    async with client_for(app) as client:
        for _ in range(3):
            with pytest.raises(RuntimeError):
                await client.get("/tiles/x")
            assert app.in_flight == 0
