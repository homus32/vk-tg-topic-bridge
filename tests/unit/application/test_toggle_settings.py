"""Unit tests for ``ToggleSettings``: toggle mapping and factory reset."""

from dataclasses import dataclass, replace

import pytest

from tests.unit.application.test_port_fakes import (
    FakeBridgeSettingsRepository,
    FakeUnitOfWork,
)
from vk_topic_bridge.application.admin.toggle_settings import ToggleSettings
from vk_topic_bridge.application.dto.settings import BridgeSettingsState, ToggleKind


@dataclass(frozen=True, slots=True)
class _Harness:
    use_case: ToggleSettings
    uow: FakeUnitOfWork
    settings: FakeBridgeSettingsRepository


def _build() -> _Harness:
    uow = FakeUnitOfWork()
    settings = FakeBridgeSettingsRepository()
    uow.bridge_settings = settings
    return _Harness(use_case=ToggleSettings(lambda: uow), uow=uow, settings=settings)


@pytest.mark.parametrize(
    ("kind", "field"),
    [
        (ToggleKind.ALL, "auto_forward_all"),
        (ToggleKind.HASHTAGS, "auto_forward_hashtags"),
        (ToggleKind.WALL, "auto_forward_wall"),
    ],
)
async def test_toggle_updates_only_the_selected_field(kind: ToggleKind, field: str) -> None:
    harness = _build()

    state = await harness.use_case.execute(kind, False)

    expected = replace(BridgeSettingsState.defaults(), **{field: False})
    assert state == expected
    assert harness.settings.state == expected
    assert harness.uow.committed is True


async def test_toggle_setting_true_wins_over_a_preexisting_false() -> None:
    harness = _build()
    harness.settings.state = replace(harness.settings.state, auto_forward_all=False)

    state = await harness.use_case.execute(ToggleKind.ALL, True)

    assert state == BridgeSettingsState.defaults()


async def test_reset_restores_factory_state() -> None:
    harness = _build()
    harness.settings.state = replace(
        harness.settings.state,
        telegram_chat_id=-100999,
        telegram_messages_topic_id=7,
        auto_forward_all=False,
    )

    state = await harness.use_case.reset()

    assert state == BridgeSettingsState.defaults()
    assert harness.settings.state == BridgeSettingsState.defaults()
    assert harness.uow.committed is True
