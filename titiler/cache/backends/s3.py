"""S3 storage backend implementation."""

import fnmatch
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Pattern, Union

import obstore
from obstore.store import S3Store

from ..backends.base import CacheBackend, CacheBackendUnavailable, CacheError
from ..settings import CacheS3Settings

logger = logging.getLogger(__name__)


def _brief(e: Exception) -> str:
    """First line only: obstore errors carry a debug dump and the full S3 XML body."""
    first_line = str(e).split("\n", 1)[0]
    return f"{type(e).__name__}: {first_line}"


class S3StorageBackend(CacheBackend):
    """S3-based storage backend for tile cache data.

    Uses S3 object metadata to store TTL information and cache metadata.
    Completely isolated from EOPF data source S3 configuration.
    """

    def __init__(
        self,
        bucket: str,
        region: str = "us-east-1",
        endpoint_url: Optional[str] = None,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        session_token: Optional[str] = None,
    ):
        """Initialize S3 storage backend. No network I/O happens here.

        Args:
            bucket: S3 bucket name for cache storage
            region: AWS region
            endpoint_url: Custom S3 endpoint (for S3-compatible services)
            access_key_id: AWS access key (optional, uses credential chain if None)
            secret_access_key: AWS secret key
            session_token: AWS session token (for temporary credentials)
        """
        self.bucket = bucket
        self.region = region
        self.endpoint_url = endpoint_url
        # S3Store rejects None; left out, these fall back to AWS defaults.
        optional = {
            "endpoint": endpoint_url,
            "access_key_id": access_key_id,
            "secret_access_key": secret_access_key,
            "session_token": session_token,
        }
        self._store = S3Store(
            bucket,
            region=region,
            client_options={
                "allow_http": bool(endpoint_url and endpoint_url.startswith("http://")),
                "connect_timeout": "3s",
                "timeout": "15s",
            },
            # The default, 10 retries over 3 minutes, would stall the tile waiting on it.
            retry_config={"max_retries": 2, "retry_timeout": timedelta(seconds=3)},
            **{k: v for k, v in optional.items() if v is not None},
        )
        self._bucket_checked = False

        # Statistics tracking
        self._stats = {
            "hits": 0,
            "misses": 0,
            "errors": 0,
            "total_operations": 0,
            "bytes_stored": 0,
            "bytes_retrieved": 0,
        }

    async def _ensure_bucket(self) -> None:
        """Check the bucket once: a GET in a missing one is a 404, i.e. a silent miss."""
        if self._bucket_checked:
            return
        try:
            await obstore.list_with_delimiter_async(self._store)
        except Exception as e:
            raise CacheBackendUnavailable(f"S3 unavailable: {_brief(e)}") from e
        self._bucket_checked = True

    def _get_object_key(self, key: str) -> str:
        """Convert cache key to S3 object key.

        Args:
            key: Cache key (e.g., "titiler:tile:collection:item:z:x:y:hash")

        Returns:
            S3 object key with proper structure for organization
        """
        # Convert cache key to S3 path structure for better organization
        # e.g., "titiler:tile:collection:item:10:512:384:abc123"
        # -> "tiles/collection/item/10/512/384/abc123"
        parts = key.split(":")
        if len(parts) >= 2 and parts[1] == "tile":
            # Tile cache key structure
            return "/".join(["tiles"] + parts[2:])
        else:
            # Generic cache key - use as-is but replace colons
            return key.replace(":", "/")

    async def get(self, key: str) -> Optional[bytes]:
        """Retrieve data from S3."""
        self._stats["total_operations"] += 1
        object_key = self._get_object_key(key)
        try:
            await self._ensure_bucket()
            result = await obstore.get_async(self._store, object_key)
            expires_at = result.attributes.get("ttl-expires-at")
            if expires_at and datetime.now(timezone.utc) > datetime.fromisoformat(
                expires_at
            ):
                logger.debug(f"S3 object expired for key: {key}")
                await obstore.delete_async(self._store, object_key)
                self._stats["misses"] += 1
                return None
            data = bytes(await result.bytes_async())
        except FileNotFoundError:  # obstore raises the builtin, not its NotFoundError
            self._stats["misses"] += 1
            logger.debug(f"S3 Cache MISS for key: {key}")
            return None
        except CacheBackendUnavailable:
            self._stats["errors"] += 1
            raise
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"S3 get error for key {key}: {_brief(e)}")
            raise CacheError(f"Failed to get key {key}: {_brief(e)}") from e

        self._stats["hits"] += 1
        self._stats["bytes_retrieved"] += len(data)
        logger.debug(f"S3 Cache HIT for key: {key} ({len(data)} bytes)")
        return data

    async def set(self, key: str, value: bytes, ttl: Optional[int] = None) -> bool:
        """Store data in S3 with TTL metadata."""
        self._stats["total_operations"] += 1
        now = datetime.now(timezone.utc)
        # Unknown attributes become x-amz-meta-* user metadata, as boto3 wrote them.
        attributes = {
            "Content-Type": "application/octet-stream",
            "cache-key": key,
            "stored-at": now.isoformat(),
        }
        if ttl is not None:
            attributes["ttl-expires-at"] = (now + timedelta(seconds=ttl)).isoformat()
            attributes["ttl-seconds"] = str(ttl)

        try:
            await self._ensure_bucket()
            await obstore.put_async(
                self._store, self._get_object_key(key), value, attributes=attributes
            )
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"S3 set error for key {key}: {_brief(e)}")
            return False

        self._stats["bytes_stored"] += len(value)
        logger.debug(f"S3 Cache SET for key: {key} ({len(value)} bytes, TTL: {ttl})")
        return True

    async def delete(self, key: str) -> bool:
        """Delete data from S3."""
        self._stats["total_operations"] += 1
        object_key = self._get_object_key(key)
        try:
            await self._ensure_bucket()
            # DELETE succeeds on a missing key too; HEAD says whether it existed.
            await obstore.head_async(self._store, object_key)
            await obstore.delete_async(self._store, object_key)
        except FileNotFoundError:
            return False
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"S3 delete error for key {key}: {_brief(e)}")
            return False

        logger.debug(f"S3 Cache DELETE for key: {key}")
        return True

    async def exists(self, key: str) -> bool:
        """Check whether a key exists in S3."""
        self._stats["total_operations"] += 1
        try:
            await self._ensure_bucket()
            await obstore.head_async(self._store, self._get_object_key(key))
        except FileNotFoundError:
            return False
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"S3 exists error for key {key}: {_brief(e)}")
            return False

        return True

    async def clear_pattern(self, pattern: Union[str, Pattern]) -> int:
        """Delete S3 objects matching pattern using list operations."""
        self._stats["total_operations"] += 1
        if isinstance(pattern, str):
            # obstore lists whole path segments, so list from the last complete one.
            literal = re.split(r"[*?]", pattern, maxsplit=1)[0]
            prefix = self._get_object_key(literal).rpartition("/")[0]
            regex = re.compile(fnmatch.translate(pattern))
        else:
            regex = pattern
            source = pattern.pattern
            prefix = (
                source[1:].split("[.*+?^${}()|\\]")[0] if source.startswith("^") else ""
            )

        deleted = 0
        try:
            await self._ensure_bucket()
            # 1000 keys is the most one DeleteObjects request takes.
            stream = obstore.list(self._store, prefix=prefix or None, chunk_size=1000)
            async for chunk in stream:
                doomed = [
                    obj["path"]
                    for obj in chunk
                    if regex.match(obj["path"].replace("/", ":"))
                ]
                if doomed:
                    await obstore.delete_async(self._store, doomed)
                    deleted += len(doomed)
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"S3 clear pattern error for {pattern}: {_brief(e)}")

        return deleted

    async def health_check(self) -> dict[str, Any]:
        """Check S3 health and return metrics."""
        try:
            await obstore.list_with_delimiter_async(self._store)
        except Exception as e:
            logger.error(f"S3 health check error: {_brief(e)}")
            return {
                "status": "error",
                "bucket": self.bucket,
                "region": self.region,
                "error": _brief(e),
            }

        return {
            "status": "connected",
            "bucket": self.bucket,
            "region": self.region,
            "endpoint_url": self.endpoint_url or "aws",
            "total_bytes_stored": self._stats["bytes_stored"],
            "total_bytes_retrieved": self._stats["bytes_retrieved"],
        }

    async def get_stats(self) -> dict[str, Any]:
        """Get S3 storage statistics."""
        total_ops = self._stats["total_operations"]
        if total_ops > 0:
            hit_rate = (self._stats["hits"] / total_ops) * 100
        else:
            hit_rate = 0.0

        return {
            "backend": "s3",
            "hit_rate": round(hit_rate, 2),
            "total_hits": self._stats["hits"],
            "total_misses": self._stats["misses"],
            "total_errors": self._stats["errors"],
            "total_operations": total_ops,
            "bytes_stored": self._stats["bytes_stored"],
            "bytes_retrieved": self._stats["bytes_retrieved"],
        }

    @classmethod
    def from_settings(cls, settings: CacheS3Settings) -> "S3StorageBackend":
        """Create S3 backend from settings."""
        if not settings.bucket:
            raise ValueError("S3 bucket must be configured")

        return cls(
            bucket=settings.bucket,
            region=settings.region,
            endpoint_url=settings.endpoint_url,
            access_key_id=settings.access_key_id,
            secret_access_key=settings.secret_access_key.get_secret_value()
            if settings.secret_access_key
            else None,
            session_token=settings.session_token,
        )
