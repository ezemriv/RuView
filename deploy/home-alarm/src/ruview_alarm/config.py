"""Validated configuration for the RuView home alarm service."""

from pathlib import Path
from typing import Self

from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration loaded from environment variables or explicit constructor values."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_file=None,
        extra="ignore",
        hide_input_in_errors=True,
        validate_default=True,
    )

    telegram_bot_token: SecretStr
    telegram_chat_id: int
    ruview_api_token: SecretStr
    ruview_base_url: AnyHttpUrl = "http://sensing-server:3000"
    telegram_base_url: AnyHttpUrl = "https://api.telegram.org"
    state_path: Path = Path("/data/state.json")
    health_path: Path = Path("/tmp/ruview-alarm-health.json")
    poll_seconds: float = Field(default=5.0, gt=0)
    all_clear_seconds: float = Field(default=60.0, gt=0)
    offline_seconds: float = Field(default=30.0, gt=0)
    telegram_poll_seconds: int = Field(default=20, gt=0)

    @model_validator(mode="after")
    def require_distinct_api_tokens(self) -> Self:
        """Keep Telegram and RuView credentials separated."""
        if self.telegram_bot_token.get_secret_value() == self.ruview_api_token.get_secret_value():
            raise ValueError("Telegram and RuView API tokens must differ")
        return self
