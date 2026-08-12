"""Hermetic network integration tests for the complete alarm service."""

from pathlib import Path

import httpx

from fakes import FakeRuView, integration_harness, wait_until
from ruview_alarm.state import load_state, save_state


async def test_fake_ruview_rejects_missing_and_wrong_bearer_tokens() -> None:
    """RuView test traffic must exercise the same bearer boundary as production."""
    async with FakeRuView("expected-ruview-token") as fake:
        async with httpx.AsyncClient() as client:
            missing = await client.get(f"{fake.base_url}/api/v1/sensing/latest")
            wrong = await client.get(
                f"{fake.base_url}/api/v1/sensing/latest",
                headers={"Authorization": "Bearer wrong-ruview-token"},
            )
            authorized = await client.get(
                f"{fake.base_url}/api/v1/sensing/latest",
                headers={"Authorization": "Bearer expected-ruview-token"},
            )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert authorized.status_code == 200


async def test_authorized_arm_presence_and_all_clear_persist_offset(tmp_path: Path) -> None:
    """A real adapter path must persist arm and report one complete incident lifecycle."""
    async with integration_harness(tmp_path, monotonic_step=30.5) as harness:
        harness.ruview.set_healthy_sample(presence=False, tick=1)
        harness.telegram.queue_message(update_id=11, chat_id=123, text="/arm")

        await wait_until(
            lambda: harness.telegram.message_texts[:2]
            == ["Alarm restored: disarmed", "Alarm is armed."],
        )
        harness.ruview.set_healthy_sample(presence=True, tick=2)
        await wait_until(
            lambda: "Intrusion detected while armed." in harness.telegram.message_texts
        )

        harness.ruview.set_healthy_sample(presence=False, tick=3)
        await wait_until(
            lambda: "All clear after continuous absence." in harness.telegram.message_texts
        )

        saved = load_state(harness.settings.state_path)
        assert saved.armed is True
        assert saved.telegram_offset == 12
        assert harness.telegram.message_texts == [
            "Alarm restored: disarmed",
            "Alarm is armed.",
            "Intrusion detected while armed.",
            "All clear after continuous absence.",
        ]


async def test_callback_acknowledged_and_unauthorized_chat_suppressed(tmp_path: Path) -> None:
    """Only the configured chat may arm or receive a callback acknowledgement."""
    async with integration_harness(tmp_path) as harness:
        harness.ruview.set_healthy_sample(presence=False, tick=1)
        harness.telegram.queue_message(update_id=20, chat_id=999, text="/disarm")
        harness.telegram.queue_callback(
            update_id=21,
            chat_id=123,
            callback_id="callback-21",
            action="arm",
        )

        await wait_until(lambda: harness.telegram.acknowledgements == ["callback-21"])
        await wait_until(lambda: len(harness.telegram.message_texts) == 2)

        saved = load_state(harness.settings.state_path)
        assert saved.armed is True
        assert saved.telegram_offset == 22
        assert harness.telegram.message_texts == [
            "Alarm restored: disarmed",
            "Alarm is armed.",
        ]


async def test_delivery_failure_and_sensor_loss_recover_independently(tmp_path: Path) -> None:
    """A failed Telegram send must retry while sensing reports one loss and recovery."""
    async with integration_harness(tmp_path, monotonic_step=31.0) as harness:
        harness.telegram.fail_next_messages(1)
        harness.ruview.set_unhealthy()

        await wait_until(lambda: "Sensor is offline." in harness.telegram.message_texts)
        harness.ruview.set_healthy_sample(presence=False, tick=1)
        await wait_until(lambda: "Sensor recovered." in harness.telegram.message_texts)

        assert harness.telegram.message_attempts[:2] == [
            "Alarm restored: disarmed",
            "Alarm restored: disarmed",
        ]
        assert harness.telegram.message_texts == [
            "Alarm restored: disarmed",
            "Sensor is offline.",
            "Sensor recovered.",
        ]


async def test_armed_recreation_detects_immediate_presence_and_closes_clients(
    tmp_path: Path,
) -> None:
    """Restored arm state must detect current presence and close both HTTP pools cleanly."""
    state_path = tmp_path / "state.json"
    save_state(
        state_path, load_state(state_path).model_copy(update={"armed": True, "telegram_offset": 7})
    )

    async with integration_harness(tmp_path) as harness:
        harness.ruview.set_healthy_sample(presence=True, tick=1)
        await wait_until(lambda: len(harness.telegram.message_texts) >= 2)

        assert harness.telegram.message_texts[:2] == [
            "Alarm restored: armed",
            "Intrusion detected while armed.",
        ]

    assert harness.ruview_http.is_closed
    assert harness.telegram_http.is_closed
