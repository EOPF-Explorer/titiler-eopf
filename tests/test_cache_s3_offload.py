"""The S3 cache backend must not run boto3 on the event loop.

boto3 is synchronous and this backend is awaited from TileCacheMiddleware on every
tile, so a body left in the coroutine blocks the worker for a full object-store
round-trip — which is what starved the liveness probe in
EOPF-Explorer/data-pipeline#416. Each public method must hand its blocking half to
a worker thread; these tests fail if one is ever inlined back.
"""

import threading

import pytest

from titiler.cache.backends.s3 import S3StorageBackend


@pytest.fixture
def backend():
    """A backend that never talks to S3 (no client is ever created)."""
    return S3StorageBackend(bucket="test-bucket", region="us-east-1")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,blocking,args",
    [
        ("get", "_get", ("key",)),
        ("set", "_set", ("key", b"value", 60)),
        ("delete", "_delete", ("key",)),
        ("exists", "_exists", ("key",)),
        ("clear_pattern", "_clear_pattern", ("pattern*",)),
        ("health_check", "_health_check", ()),
    ],
)
async def test_blocking_call_runs_off_the_event_loop(backend, method, blocking, args):
    """Every blocking S3 method runs in a worker thread, not on the loop."""
    ran_in = {}
    setattr(
        backend, blocking, lambda *_: ran_in.setdefault("thread", threading.get_ident())
    )

    await getattr(backend, method)(*args)

    assert (
        ran_in["thread"] != threading.get_ident()
    ), f"{method} ran its blocking body on the event loop thread"
