"""The S3 cache backend's contract, pinned over real HTTP.

`moto`'s in-process `mock_aws` patches botocore, so it can only see an S3 client that
*is* boto3. Driving a real HTTP endpoint instead keeps these tests valid for any
implementation of the same contract.

The `xfail(strict=True)` cases are pre-existing bugs, each noted at its test.
"""

from datetime import datetime, timezone

import boto3
import pytest

from titiler.cache.backends.s3 import S3StorageBackend

BUCKET = "tilecache"
CREDENTIALS = {"access_key_id": "testing", "secret_access_key": "testing"}


@pytest.fixture
def s3_client(s3_endpoint, monkeypatch):
    """A raw boto3 client on an empty bucket, for asserting on what was stored."""
    # Both branches of _build_client work with explicit credentials; pin the branch
    # so a developer's exported value cannot change what is under test.
    monkeypatch.delenv("AWS_EC2_METADATA_DISABLED", raising=False)

    client = boto3.client(
        "s3",
        region_name="us-east-1",
        endpoint_url=s3_endpoint,
        aws_access_key_id=CREDENTIALS["access_key_id"],
        aws_secret_access_key=CREDENTIALS["secret_access_key"],
    )
    client.create_bucket(Bucket=BUCKET)
    yield client

    objects = client.list_objects_v2(Bucket=BUCKET).get("Contents", [])
    if objects:
        client.delete_objects(
            Bucket=BUCKET, Delete={"Objects": [{"Key": o["Key"]} for o in objects]}
        )
    client.delete_bucket(Bucket=BUCKET)


@pytest.fixture
def backend(s3_endpoint, s3_client):
    """The backend under test, pointed at the bucket s3_client just created."""
    return S3StorageBackend(
        bucket=BUCKET, region="us-east-1", endpoint_url=s3_endpoint, **CREDENTIALS
    )


def test_missing_bucket_is_unavailable_not_a_crash(s3_endpoint, s3_client):
    """A bucket that does not exist surfaces as CacheBackendUnavailable."""
    from titiler.cache.backends.base import CacheBackendUnavailable

    backend = S3StorageBackend(
        bucket="no-such-bucket",
        region="us-east-1",
        endpoint_url=s3_endpoint,
        **CREDENTIALS,
    )
    with pytest.raises(CacheBackendUnavailable):
        backend._get_client()


def test_object_key_is_a_tile_path(backend):
    """Tile keys become a directory layout; anything else just loses its colons."""
    assert (
        backend._get_object_key("titiler:tile:coll:item:10:512:384:abc123")
        == "tiles/coll/item/10/512/384/abc123"
    )
    assert backend._get_object_key("titiler:meta:coll") == "titiler/meta/coll"


@pytest.mark.asyncio
async def test_set_then_get_round_trips(backend):
    """The bytes come back unchanged."""
    key = "titiler:tile:coll:item:10:512:384:abc123"

    assert await backend.set(key, b"\x89PNG-payload", ttl=3600) is True
    assert await backend.get(key) == b"\x89PNG-payload"

    stats = await backend.get_stats()
    assert stats["total_hits"] == 1
    assert stats["total_errors"] == 0
    assert stats["bytes_stored"] == len(b"\x89PNG-payload")
    assert stats["bytes_retrieved"] == len(b"\x89PNG-payload")


@pytest.mark.asyncio
async def test_ttl_is_stored_as_user_metadata(backend, s3_client):
    """TTL travels as user metadata on the object, not in the payload.

    boto3 strips the `x-amz-meta-` prefix and lowercases the names; these are the keys
    any replacement backend has to keep writing for old objects to stay readable.
    """
    key = "titiler:tile:coll:item:1:2:3:hash"
    await backend.set(key, b"payload", ttl=1800)

    head = s3_client.head_object(Bucket=BUCKET, Key="tiles/coll/item/1/2/3/hash")
    metadata = head["Metadata"]

    assert metadata["cache-key"] == key
    assert metadata["ttl-seconds"] == "1800"
    expires_at = datetime.fromisoformat(metadata["ttl-expires-at"])
    assert expires_at > datetime.now(timezone.utc)
    datetime.fromisoformat(metadata["stored-at"])


@pytest.mark.asyncio
async def test_set_without_ttl_writes_no_expiry(backend, s3_client):
    """No TTL means no expiry metadata, and the entry never expires."""
    key = "titiler:tile:coll:item:0:0:0:forever"
    await backend.set(key, b"payload")

    head = s3_client.head_object(Bucket=BUCKET, Key="tiles/coll/item/0/0/0/forever")
    assert "ttl-expires-at" not in head["Metadata"]
    assert await backend.get(key) == b"payload"


@pytest.mark.asyncio
async def test_expired_entry_is_a_miss_and_is_evicted(backend, s3_client):
    """An expired object reads as a miss and is deleted on the way out."""
    key = "titiler:tile:coll:item:5:5:5:stale"
    object_key = "tiles/coll/item/5/5/5/stale"

    await backend.set(key, b"stale-payload", ttl=-1)
    assert "Contents" in s3_client.list_objects_v2(Bucket=BUCKET, Prefix=object_key)

    assert await backend.get(key) is None

    assert "Contents" not in s3_client.list_objects_v2(Bucket=BUCKET, Prefix=object_key)
    stats = await backend.get_stats()
    assert stats["total_misses"] == 1
    assert stats["total_errors"] == 0


@pytest.mark.asyncio
async def test_missing_key_is_a_miss_not_an_error(backend):
    """A cache miss is an ordinary outcome and must not count as an error."""
    assert await backend.get("titiler:tile:coll:item:9:9:9:absent") is None

    stats = await backend.get_stats()
    assert stats["total_misses"] == 1
    assert stats["total_errors"] == 0


@pytest.mark.asyncio
async def test_exists_reports_presence(backend):
    """exists() is True once set() has run."""
    key = "titiler:tile:coll:item:2:2:2:here"
    await backend.set(key, b"payload")
    assert await backend.exists(key) is True


@pytest.mark.asyncio
async def test_exists_on_missing_key_is_false(backend):
    """A missing key is absent, not an exception."""
    assert await backend.exists("titiler:tile:coll:item:9:9:9:absent") is False


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason="bug: head_object raises ClientError('404'), not NoSuchKey, so the "
    "absent-key branch is never taken and a plain miss is counted as an error",
)
async def test_exists_on_missing_key_is_not_an_error(backend):
    """Asking about a key that is not there is not a backend error."""
    await backend.exists("titiler:tile:coll:item:9:9:9:absent")

    stats = await backend.get_stats()
    assert stats["total_errors"] == 0


@pytest.mark.asyncio
async def test_delete_removes_the_object(backend, s3_client):
    """delete() reports True and the object is gone."""
    key = "titiler:tile:coll:item:3:3:3:doomed"
    await backend.set(key, b"payload")

    assert await backend.delete(key) is True
    assert "Contents" not in s3_client.list_objects_v2(
        Bucket=BUCKET, Prefix="tiles/coll/item/3/3/3/doomed"
    )


@pytest.mark.asyncio
async def test_delete_on_missing_key_is_false(backend):
    """Deleting what is not there reports False."""
    assert await backend.delete("titiler:tile:coll:item:9:9:9:absent") is False


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason="bug: same ClientError('404') vs NoSuchKey mismatch as exists(), so the "
    "head_object miss escapes to the generic handler and counts as an error",
)
async def test_delete_on_missing_key_is_not_an_error(backend):
    """Deleting an absent key is a no-op, not a backend error."""
    await backend.delete("titiler:tile:coll:item:9:9:9:absent")

    stats = await backend.get_stats()
    assert stats["total_errors"] == 0


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason="bug: object keys are mapped back with '/'->':' , yielding "
    "'tiles:coll:...' which can never match a 'titiler:tile:coll:*' glob, so "
    "clear_pattern deletes nothing and cache invalidation silently no-ops",
)
async def test_clear_pattern_deletes_matching_tiles(backend):
    """A glob over one collection clears that collection's tiles."""
    await backend.set("titiler:tile:coll:item:1:1:1:a", b"a")
    await backend.set("titiler:tile:coll:item:2:2:2:b", b"b")
    await backend.set("titiler:tile:other:item:3:3:3:c", b"c")

    assert await backend.clear_pattern("titiler:tile:coll:*") == 2
    assert await backend.get("titiler:tile:coll:item:1:1:1:a") is None
    assert await backend.get("titiler:tile:other:item:3:3:3:c") == b"c"


@pytest.mark.asyncio
async def test_health_check_shape(backend):
    """/_mgmt/cache consumers read these keys."""
    health = await backend.health_check()

    assert health["status"] == "connected"
    assert health["bucket"] == BUCKET
    assert health["region"] == "us-east-1"
    assert "endpoint_url" in health
    assert "total_bytes_stored" in health
    assert "total_bytes_retrieved" in health


@pytest.mark.asyncio
async def test_health_check_reports_a_missing_bucket(s3_endpoint, s3_client):
    """A bucket that vanished is reported, not raised."""
    backend = S3StorageBackend(
        bucket="no-such-bucket",
        region="us-east-1",
        endpoint_url=s3_endpoint,
        **CREDENTIALS,
    )
    health = await backend.health_check()

    assert health["status"] in {"disconnected", "error"}
    assert health["bucket"] == "no-such-bucket"
