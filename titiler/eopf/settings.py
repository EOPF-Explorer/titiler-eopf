"""API settings."""

from pydantic import (
    AnyUrl,
    Field,
    SecretStr,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self


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
    """Redis Cache Settings"""

    host: str | None = None
    port: int = Field(default=6379, ge=1, le=65535)
    username: str | None = None
    password: SecretStr | None = None
    db: int = Field(default=0, ge=0)
    ssl: bool = False
    enable: bool = False
    dataset_ttl_seconds: int = Field(default=300, ge=0)
    dataset_ttl_jitter_ratio: float = Field(default=0.1, ge=0.0, le=1.0)
    dataset_max_items: int | None = Field(default=128, gt=0)
    dataset_hmac_secret: SecretStr | None = None
    dataset_max_redis_payload_bytes: int = Field(default=64 * 1024 * 1024, ge=1)

    model_config = SettingsConfigDict(
        env_prefix="TITILER_EOPF_CACHE_", env_file=".env", extra="ignore"
    )

    @model_validator(mode="after")
    def check_cache_settings(self) -> Self:
        """Check if cache is disabled."""
        if self.enable and not self.host:
            raise ValueError("Redis CACHE_HOST must be set when cache is enabled")

        if self.enable and not self.dataset_hmac_secret:
            raise ValueError(
                "Redis CACHE_DATASET_HMAC_SECRET must be set when cache is enabled"
            )

        return self
