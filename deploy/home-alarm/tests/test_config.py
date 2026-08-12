from pathlib import Path

import pytest
from pydantic import ValidationError

from ruview_alarm.config import Settings


def test_settings_require_all_three_credentials() -> None:
    """Removing a required credential must make settings invalid."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(telegram_bot_token="bot-token", telegram_chat_id=123456)

    assert "ruview_api_token" in str(exc_info.value)


def test_settings_apply_documented_defaults() -> None:
    """Omitting optional settings must preserve the documented deployment defaults."""
    settings = Settings(
        telegram_bot_token="bot-token",
        telegram_chat_id=123456,
        ruview_api_token="ruview-token",
    )

    assert str(settings.ruview_base_url) == "http://sensing-server:3000/"
    assert str(settings.telegram_base_url) == "https://api.telegram.org/"
    assert settings.state_path == Path("/data/state.json")
    assert settings.health_path == Path("/tmp/ruview-alarm-health.json")
    assert settings.poll_seconds == 5.0
    assert settings.all_clear_seconds == 60.0
    assert settings.offline_seconds == 30.0
    assert settings.telegram_poll_seconds == 20


def test_settings_accept_constructor_overrides_without_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit constructor values must work independently of environment-file configuration."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("RUVIEW_API_TOKEN", raising=False)

    settings = Settings(
        telegram_bot_token="bot-token",
        telegram_chat_id=987654,
        ruview_api_token="ruview-token",
        poll_seconds=1.5,
    )

    assert settings.telegram_chat_id == 987654
    assert settings.poll_seconds == 1.5


def test_validation_error_does_not_include_secret_values() -> None:
    """The model-level credential validation error must not render its secret input."""
    sentinel = "DO_NOT_RENDER_ME"

    with pytest.raises(ValidationError) as exc_info:
        Settings(
            telegram_bot_token=sentinel,
            telegram_chat_id=123456,
            ruview_api_token=sentinel,
        )

    rendered_error = str(exc_info.value)
    assert sentinel not in rendered_error
    assert "Telegram and RuView API tokens must differ" in rendered_error
