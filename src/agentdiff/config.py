"""Process-wide settings, sourced from environment variables.

`ANTHROPIC_API_KEY` is read without a prefix to match the Anthropic
SDK's own convention. Everything else uses `AGENTDIFF_*` so we don't
collide with whatever else the user has in their shell.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    log_level: str = Field(default="WARNING", validation_alias="AGENTDIFF_LOG_LEVEL")
    concurrency: int = Field(default=5, validation_alias="AGENTDIFF_CONCURRENCY")
