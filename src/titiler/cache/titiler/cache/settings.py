"""Cache configuration settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


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
