"""A slow object store must not stall the event loop (EOPF-Explorer/data-pipeline#416).

Latency is injected at the socket, so this holds whatever S3 client the backend uses.
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
# Well under LATENCY, so a backend that blocks for one round-trip cannot slip under it.
MAX_TICK_GAP = 0.05


class _SlowHandler(socketserver.BaseRequestHandler):
    def handle(self):
        """Relay to `server.target`, delaying each chunk on its way back by LATENCY."""
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
                        time.sleep(LATENCY)
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
    proxy = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _SlowHandler)
    proxy.daemon_threads = True
    proxy.target = (target.hostname, target.port)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
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
    await backend.exists(seeded_key)  # connect and check the bucket before timing

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

    # Otherwise a relay that failed to delay would pass the test vacuously.
    assert (
        elapsed > LATENCY
    ), f"latency injection did not take: read took {elapsed:.3f}s"
    assert gaps, "ticker never ran"
    assert (
        max(gaps) < MAX_TICK_GAP
    ), f"event loop stalled for {max(gaps):.3f}s during a {elapsed:.3f}s cache read"
