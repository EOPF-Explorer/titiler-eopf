"""API settings."""

from pydantic import AnyUrl, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self

from titiler.cache import CacheRedisSettings, CacheS3Settings
from titiler.cache import CacheSettings as BaseCacheSettings


class ApiSettings(BaseSettings):
    """API settings"""

    name: str = "TiTiler application for EOPF datasets"
    cors_origins: str = "*"
    cors_allow_methods: str = "GET"
    cachecontrol: str = "public, max-age=3600"
    root_path: str = ""
    debug: bool = False

    model_config = SettingsConfigDict(
        env_prefix="TITILER_EOPF_API_", env_file=".env", extra="ignore"
    )

    @field_validator("cors_origins")
    def parse_cors_origin(cls, v):
        """Parse CORS origins."""
        return [origin.strip() for origin in v.split(",")]

    @field_validator("cors_allow_methods")
    def parse_cors_allow_methods(cls, v):
        """Parse CORS allowed methods."""
        return [method.strip().upper() for method in v.split(",")]


class DataStoreSettings(BaseSettings):
    """Data store settings"""

    scheme: str | None = None
    host: str | None = None
    path: str | None = None

    url: AnyUrl | None = None

    model_config = SettingsConfigDict(
        env_prefix="TITILER_EOPF_STORE_", env_file=".env", extra="ignore"
    )

    @field_validator("url", mode="before")
    def assemble_url(cls, v: str | None, info: ValidationInfo) -> str | AnyUrl:
        """Validate database config."""
        if isinstance(v, str):
            return v

        # Only build URL from components if url is not provided and scheme/host are available
        if v is None and (info.data.get("scheme") and info.data.get("host")):
            return AnyUrl.build(
                scheme=info.data["scheme"],
                host=info.data["host"],
                path=info.data.get("path", ""),
            )

        raise ValueError(
            "Either 'url' must be provided or both 'scheme' and 'host' must be provided"
        )


class CacheSettings(BaseSettings):
    """Legacy Redis Cache Settings - replaced by TiTiler Cache Extension.

    This class maintains backward compatibility with existing EOPF cache settings
    while providing access to the new comprehensive cache system.
    """

    host: str | None = None
    port: int = 6379
    password: SecretStr | None = None
    enable: bool = False

    model_config = SettingsConfigDict(
        env_prefix="TITILER_EOPF_CACHE_", env_file=".env", extra="ignore"
    )

    @model_validator(mode="after")
    def check_cache_settings(self) -> Self:
        """Check if cache is disabled."""
        if self.enable and not self.host:
            raise ValueError("Redis CACHE_HOST must be set when cache is enabled")

        return self


class EOPFCacheSettings(BaseCacheSettings):
    """Enhanced EOPF Cache Settings.

    Extends the base cache settings to provide EOPF-specific configuration
    with support for Redis metadata, S3 tile storage, and cache management.
    """

    # Backend configuration
    backend: str = "redis"  # redis, s3, or s3-redis

    # EOPF-specific cache settings
    namespace: str = "titiler-eopf"
    default_ttl: int = 3600  # 1 hour default TTL
    tile_ttl: int = 86400  # 24 hours for tiles
    metadata_ttl: int = 300  # 5 minutes for metadata

    # Parameter exclusion for cache keys
    exclude_params: list[str] = ["format", "callback", "buffer"]

    # Cache path patterns to cache
    cache_paths: list[str] = [
        "/tiles/",
        "/tilejson.json",
        "/preview",
        "/crop/",
        "/statistics",
        "/info.json",
    ]

    # Nested settings for backends
    redis: CacheRedisSettings | None = None
    s3: CacheS3Settings | None = None

    model_config = SettingsConfigDict(
        env_prefix="TITILER_EOPF_CACHE_", env_file=".env", extra="ignore"
    )

    @model_validator(mode="after")
    def validate_backend_settings(self) -> Self:
        """Validate backend-specific settings."""
        if not self.enable:
            return self

        if self.backend == "redis":
            if not self.redis:
                self.redis = CacheRedisSettings(_env_prefix="TITILER_EOPF_CACHE_REDIS_")
        elif self.backend == "s3":
            if not self.s3:
                self.s3 = CacheS3Settings(_env_prefix="TITILER_EOPF_CACHE_S3_")
        elif self.backend == "s3-redis":
            if not self.redis:
                self.redis = CacheRedisSettings(_env_prefix="TITILER_EOPF_CACHE_REDIS_")
            if not self.s3:
                self.s3 = CacheS3Settings(_env_prefix="TITILER_EOPF_CACHE_S3_")
        else:
            raise ValueError(f"Unsupported cache backend: {self.backend}")

        return self
