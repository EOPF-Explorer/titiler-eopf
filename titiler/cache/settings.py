"""Cache configuration settings."""

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self


class CacheSettings(BaseSettings):
    """Base cache configuration."""

    enable: bool = False
    default_ttl: int = 3600  # 1 hour default
    max_tile_size: int = 1024 * 1024  # 1MB max tile size
    monitoring_enabled: bool = True

    # Exclude these parameters from cache keys
    exclude_params: list[str] = [
        # Debug/Development
        "debug",
        "profile",
        "timing",
        "stats",
        # User-specific
        "user_id",
        "session",
        "token",
        "auth",
        # Timestamps
        "timestamp",
        "cache_buster",
        "t",
        "_t",
        # Response format (handled separately)
        "f",
        "format_response",
        "output_format",
        # Request metadata
        "callback",
        "jsonp",
        "pretty",
    ]

    model_config = SettingsConfigDict(
        env_prefix="TITILER_CACHE_", env_file=".env", extra="ignore"
    )


class CacheRedisSettings(BaseSettings):
    """Redis cache backend configuration."""

    host: str | None = None
    port: int = 6379
    password: SecretStr | None = None
    db: int = 0

    model_config = SettingsConfigDict(
        env_prefix="TITILER_CACHE_REDIS_", env_file=".env", extra="ignore"
    )


class CacheS3Settings(BaseSettings):
    """S3 cache storage configuration.

    Separate from EOPF data source S3 settings to allow different
    buckets, regions, and credentials for cache storage.
    """

    bucket: str | None = None
    region: str = "us-east-1"
    endpoint_url: str | None = None
    access_key_id: str | None = None
    secret_access_key: SecretStr | None = None
    session_token: str | None = None

    model_config = SettingsConfigDict(
        env_prefix="TITILER_CACHE_S3_", env_file=".env", extra="ignore"
    )

    @model_validator(mode="after")
    def validate_s3_config(self) -> Self:
        """Validate S3 configuration."""
        if self.bucket and not self.access_key_id:
            # Allow using default AWS credentials chain if no explicit key provided
            pass
        return self
