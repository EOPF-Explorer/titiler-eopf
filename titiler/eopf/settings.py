"""API settings."""

from pydantic import AnyUrl, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    scheme: str
    host: str
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

        return AnyUrl.build(
            scheme=info.data["scheme"],
            host=info.data["host"],
            path=info.data.get("path", ""),
        )
