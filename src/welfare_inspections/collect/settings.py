"""Settings for local source discovery defaults."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from welfare_inspections.collect.portal_discovery import CANONICAL_SOURCE_URL


class DiscoverySettings(BaseSettings):
    """Environment-configurable defaults for manual discovery runs."""

    model_config = SettingsConfigDict(
        env_prefix="WELFARE_INSPECTIONS_DISCOVERY_",
        extra="ignore",
    )

    start_url: str = CANONICAL_SOURCE_URL
    max_pages: int = Field(default=5, ge=1)
    page_size: int = Field(default=10, ge=1)
    request_delay_seconds: float = Field(default=1.0, ge=0)
