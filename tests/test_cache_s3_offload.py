"""The S3 cache backend must not run boto3 on the event loop.

A blocking body left in a coroutine parks the worker for an object-store round-trip,
which starved the liveness probe in EOPF-Explorer/data-pipeline#416.
"""

import threading

import pytest

from titiler.cache.backends.s3 import S3StorageBackend, _s3_threads


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
    """Every blocking S3 method runs in a worker thread, under the S3 limiter."""
    seen = {}

    def record(*_):
        seen["thread"] = threading.get_ident()
        seen["s3_tokens"] = _s3_threads().borrowed_tokens
        return sentinel

    sentinel = object()
    setattr(backend, blocking, record)

    result = await getattr(backend, method)(*args)

    assert (
        seen["thread"] != threading.get_ident()
    ), f"{method} ran its blocking body on the event loop thread"
    # Without limiter=, this lands in anyio's default pool with the tile renders.
    assert seen["s3_tokens"] == 1, f"{method} did not use the S3 limiter"
    assert result is sentinel, f"{method} dropped the return value of {blocking}"
