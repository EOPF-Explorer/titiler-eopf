"""S3 storage backend implementation."""

import logging
from datetime import datetime, timezone
from typing import Any, Optional, Pattern, Union

from ..backends.base import CacheBackend, CacheBackendUnavailable, CacheError
from ..settings import CacheS3Settings

try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError
except ImportError:  # pragma: nocover
    boto3 = None  # type: ignore
    ClientError = Exception  # type: ignore
    NoCredentialsError = Exception  # type: ignore

logger = logging.getLogger(__name__)


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
        **kwargs,
    ):
        """Initialize S3 storage backend.

        Args:
            bucket: S3 bucket name for cache storage
            region: AWS region
            endpoint_url: Custom S3 endpoint (for S3-compatible services)
            access_key_id: AWS access key (optional, uses credential chain if None)
            secret_access_key: AWS secret key
            session_token: AWS session token (for temporary credentials)
            **kwargs: Additional boto3 client parameters
        """
        if boto3 is None:
            raise ImportError("boto3 package is required for S3StorageBackend")

        self.bucket = bucket
        self.region = region
        self.endpoint_url = endpoint_url
        self._client = None
        self.client_kwargs = kwargs

        # Store credentials for client creation
        self._credentials = {
            "aws_access_key_id": access_key_id,
            "aws_secret_access_key": secret_access_key,
            "aws_session_token": session_token,
        }
        # Remove None values
        self._credentials = {
            k: v for k, v in self._credentials.items() if v is not None
        }

        # Statistics tracking
        self._stats = {
            "hits": 0,
            "misses": 0,
            "errors": 0,
            "total_operations": 0,
            "bytes_stored": 0,
            "bytes_retrieved": 0,
        }

    def _get_client(self):
        """Get S3 client with isolated credentials."""
        if self._client is None:
            try:
                # Create session with isolated credentials
                session = boto3.Session(**self._credentials)

                self._client = session.client(
                    "s3",
                    region_name=self.region,
                    endpoint_url=self.endpoint_url,
                    **self.client_kwargs,
                )

                # Test access to bucket
                self._client.head_bucket(Bucket=self.bucket)
                logger.debug(f"Connected to S3 bucket: {self.bucket}")

            except (ClientError, NoCredentialsError) as e:
                logger.error(f"Failed to connect to S3: {e}")
                raise CacheBackendUnavailable(f"S3 unavailable: {e}") from e

        return self._client

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
        try:
            client = self._get_client()
            self._stats["total_operations"] += 1

            object_key = self._get_object_key(key)

            # Get object with metadata
            response = client.get_object(Bucket=self.bucket, Key=object_key)

            # Check TTL if present in metadata
            metadata = response.get("Metadata", {})
            if "ttl-expires-at" in metadata:
                expires_at = datetime.fromisoformat(metadata["ttl-expires-at"])
                if datetime.now(timezone.utc) > expires_at:
                    logger.debug(f"S3 object expired for key: {key}")
                    # Object expired, delete it and return None
                    client.delete_object(Bucket=self.bucket, Key=object_key)
                    self._stats["misses"] += 1
                    return None

            data = response["Body"].read()
            self._stats["hits"] += 1
            self._stats["bytes_retrieved"] += len(data)
            logger.debug(f"S3 Cache HIT for key: {key} ({len(data)} bytes)")
            return data

        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                self._stats["misses"] += 1
                logger.debug(f"S3 Cache MISS for key: {key}")
                return None
            else:
                self._stats["errors"] += 1
                logger.error(f"S3 get error for key {key}: {e}")
                raise CacheError(f"Failed to get key {key}: {e}") from e
        except CacheBackendUnavailable:
            self._stats["errors"] += 1
            raise
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"S3 get error for key {key}: {e}")
            raise CacheError(f"Failed to get key {key}: {e}") from e

    async def set(self, key: str, value: bytes, ttl: Optional[int] = None) -> bool:
        """Store data in S3 with TTL metadata."""
        try:
            client = self._get_client()
            self._stats["total_operations"] += 1

            object_key = self._get_object_key(key)

            # Prepare metadata
            metadata = {
                "cache-key": key,
                "stored-at": datetime.now(timezone.utc).isoformat(),
                "content-type": "application/octet-stream",
            }

            # Add TTL metadata if specified
            if ttl is not None:
                expires_at = datetime.now(timezone.utc).timestamp() + ttl
                metadata["ttl-expires-at"] = datetime.fromtimestamp(
                    expires_at, tz=timezone.utc
                ).isoformat()
                metadata["ttl-seconds"] = str(ttl)

            # Store object with metadata
            client.put_object(
                Bucket=self.bucket,
                Key=object_key,
                Body=value,
                Metadata=metadata,
                ContentType="application/octet-stream",
            )

            self._stats["bytes_stored"] += len(value)
            logger.debug(
                f"S3 Cache SET for key: {key} ({len(value)} bytes, TTL: {ttl})"
            )
            return True

        except CacheBackendUnavailable:
            self._stats["errors"] += 1
            return False
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"S3 set error for key {key}: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """Delete single object from S3."""
        try:
            client = self._get_client()
            self._stats["total_operations"] += 1

            object_key = self._get_object_key(key)

            # Check if object exists first
            try:
                client.head_object(Bucket=self.bucket, Key=object_key)
                client.delete_object(Bucket=self.bucket, Key=object_key)
                logger.debug(f"S3 Cache DELETE for key: {key}")
                return True
            except ClientError as e:
                if e.response["Error"]["Code"] == "NoSuchKey":
                    return False
                raise

        except CacheBackendUnavailable:
            self._stats["errors"] += 1
            return False
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"S3 delete error for key {key}: {e}")
            return False

    async def exists(self, key: str) -> bool:
        """Check if object exists in S3."""
        try:
            client = self._get_client()
            self._stats["total_operations"] += 1

            object_key = self._get_object_key(key)
            client.head_object(Bucket=self.bucket, Key=object_key)
            return True

        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return False
            self._stats["errors"] += 1
            logger.error(f"S3 exists error for key {key}: {e}")
            return False
        except CacheBackendUnavailable:
            self._stats["errors"] += 1
            return False
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"S3 exists error for key {key}: {e}")
            return False

    async def clear_pattern(self, pattern: Union[str, Pattern]) -> int:  # noqa: C901
        """Delete S3 objects matching pattern using list operations."""
        try:
            client = self._get_client()
            self._stats["total_operations"] += 1

            # Convert pattern to S3 prefix if possible
            if hasattr(pattern, "pattern"):
                # Regex pattern - convert to prefix if it starts with literal text
                pattern_str = str(pattern.pattern)
                if pattern_str.startswith("^"):
                    prefix = pattern_str[1:].split("[.*+?^${}()|\\]")[0]
                else:
                    prefix = ""
            else:
                # String pattern - convert Redis glob to S3 prefix
                pattern_str = str(pattern)
                # Extract prefix before first wildcard
                wildcard_pos = min(
                    [
                        pos
                        for pos in [pattern_str.find("*"), pattern_str.find("?")]
                        if pos >= 0
                    ]
                    or [len(pattern_str)]
                )
                prefix = self._get_object_key(pattern_str[:wildcard_pos])

            deleted = 0
            paginator = client.get_paginator("list_objects_v2")

            # List and delete matching objects
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                if "Contents" not in page:
                    continue

                objects_to_delete = []
                for obj in page["Contents"]:
                    # Check if object key matches pattern
                    object_key = obj["Key"]
                    # Convert back to cache key for pattern matching
                    cache_key = object_key.replace("/", ":")

                    if hasattr(pattern, "match"):
                        if pattern.match(cache_key):
                            objects_to_delete.append({"Key": object_key})
                    else:
                        # Simple glob matching
                        if self._glob_match(cache_key, pattern_str):
                            objects_to_delete.append({"Key": object_key})

                # Batch delete matching objects
                if objects_to_delete:
                    response = client.delete_objects(
                        Bucket=self.bucket, Delete={"Objects": objects_to_delete}
                    )
                    deleted += len(response.get("Deleted", []))

            logger.debug(f"S3 Cache CLEAR pattern: {pattern_str} (deleted: {deleted})")
            return deleted

        except CacheBackendUnavailable:
            self._stats["errors"] += 1
            return 0
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"S3 clear pattern error for {pattern}: {e}")
            return 0

    def _glob_match(self, text: str, pattern: str) -> bool:
        """Simple glob pattern matching for S3 object filtering."""
        import fnmatch

        return fnmatch.fnmatch(text, pattern)

    async def health_check(self) -> dict[str, Any]:
        """Check S3 health and return metrics."""
        try:
            client = self._get_client()

            # Check bucket access
            client.head_bucket(Bucket=self.bucket)

            # Get bucket location
            try:
                location = client.get_bucket_location(Bucket=self.bucket)
                bucket_region = location.get("LocationConstraint") or "us-east-1"
            except Exception:
                bucket_region = "unknown"

            return {
                "status": "connected",
                "bucket": self.bucket,
                "region": self.region,
                "bucket_region": bucket_region,
                "endpoint_url": self.endpoint_url or "aws",
                "total_bytes_stored": self._stats["bytes_stored"],
                "total_bytes_retrieved": self._stats["bytes_retrieved"],
            }

        except CacheBackendUnavailable:
            return {
                "status": "disconnected",
                "bucket": self.bucket,
                "region": self.region,
                "error": "Backend unavailable",
            }
        except Exception as e:
            logger.error(f"S3 health check error: {e}")
            return {
                "status": "error",
                "bucket": self.bucket,
                "region": self.region,
                "error": str(e),
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
