"""A slow object store must not stall the event loop.

`TileCacheMiddleware` awaits this backend on every tile, so a blocking body inside a
coroutine parks the worker for a whole object-store round-trip. That is what starved the
liveness probe until kubelet killed both replicas in
EOPF-Explorer/data-pipeline#416.

The guard is stated as the property itself -- the loop keeps running while a cache read
is in flight -- rather than as "the call happens on a thread", so it survives any change
of S3 client. Latency is injected at the socket, below whatever library is in use.
"""

import asyncio
import selectors
import socket
import socketserver
import threading
import time
from urllib.parse import urlparse

import boto3
import pytest

from titiler.cache.backends.s3 import S3StorageBackend

BUCKET = "loopcache"
CREDENTIALS = {"access_key_id": "testing", "secret_access_key": "testing"}
LATENCY = 0.1
# A tick this slow means the loop is not being serviced; it is well under the injected
# latency, so a backend that blocks for one round-trip cannot slip under it.
MAX_TICK_GAP = 0.05


class _SlowProxy(socketserver.ThreadingTCPServer):
    """A TCP relay that adds `delay` to everything the upstream sends back."""

    daemon_threads = True
    allow_reuse_address = True


class _SlowHandler(socketserver.BaseRequestHandler):
    def handle(self):
        """Pipe both directions, delaying each chunk on its way back to the client."""
        upstream = socket.create_connection(self.server.target)
        sel = selectors.DefaultSelector()
        sel.register(self.request, selectors.EVENT_READ, "client")
        sel.register(upstream, selectors.EVENT_READ, "upstream")
        try:
            while True:
                for key, _ in sel.select(timeout=30):
                    if key.data == "client":
                        data = self.request.recv(65536)
                        if not data:
                            return
                        upstream.sendall(data)
                    else:
                        data = upstream.recv(65536)
                        if not data:
                            return
                        time.sleep(self.server.delay)
                        self.request.sendall(data)
        except OSError:
            return
        finally:
            sel.close()
            upstream.close()


@pytest.fixture
def slow_endpoint(s3_endpoint):
    """`s3_endpoint`, reachable only through a relay that adds LATENCY per response."""
    target = urlparse(s3_endpoint)
    proxy = _SlowProxy(("127.0.0.1", 0), _SlowHandler)
    proxy.target = (target.hostname, target.port)
    proxy.delay = LATENCY

    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{proxy.server_address[1]}"
    proxy.shutdown()
    proxy.server_close()


@pytest.fixture
def seeded_key(s3_endpoint):
    """One cached tile, written at full speed so only the read is slow."""
    client = boto3.client(
        "s3",
        region_name="us-east-1",
        endpoint_url=s3_endpoint,
        aws_access_key_id=CREDENTIALS["access_key_id"],
        aws_secret_access_key=CREDENTIALS["secret_access_key"],
    )
    client.create_bucket(Bucket=BUCKET)
    client.put_object(
        Bucket=BUCKET, Key="tiles/coll/item/8/8/8/payload", Body=b"tile-bytes"
    )
    yield "titiler:tile:coll:item:8:8:8:payload"
    client.delete_object(Bucket=BUCKET, Key="tiles/coll/item/8/8/8/payload")
    client.delete_bucket(Bucket=BUCKET)


@pytest.mark.asyncio
async def test_a_slow_store_does_not_stall_the_event_loop(slow_endpoint, seeded_key):
    """While a cache read is in flight, a 5 ms ticker keeps being serviced."""
    backend = S3StorageBackend(
        bucket=BUCKET, region="us-east-1", endpoint_url=slow_endpoint, **CREDENTIALS
    )
    # Connect and validate the bucket before timing, so head_bucket's latency is not
    # attributed to the read.
    await asyncio.to_thread(backend._get_client)

    gaps: list[float] = []
    ticking = True

    async def ticker():
        last = time.perf_counter()
        while ticking:
            await asyncio.sleep(0.005)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    task = asyncio.create_task(ticker())
    await asyncio.sleep(0.02)
    gaps.clear()

    started = time.perf_counter()
    assert await backend.get(seeded_key) == b"tile-bytes"
    elapsed = time.perf_counter() - started

    ticking = False
    await task

    # Guards against the relay silently not delaying, which would make the assertion
    # below pass for the wrong reason.
    assert (
        elapsed > LATENCY
    ), f"latency injection did not take: read took {elapsed:.3f}s"
    assert gaps, "ticker never ran"
    assert (
        max(gaps) < MAX_TICK_GAP
    ), f"event loop stalled for {max(gaps):.3f}s during a {elapsed:.3f}s cache read"
