from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from vk_topic_bridge.application.dto.infrastructure import LongPollInfo
from vk_topic_bridge.bootstrap import startup
from vk_topic_bridge.bootstrap.container import AppContainer
from vk_topic_bridge.domain.errors import FatalStartupError, FatalStartupReason


class _FakeVkGateway:
    def __init__(self, long_poll: object) -> None:
        self.long_poll = long_poll

    async def get_community_id(self) -> int:
        return 42

    async def check_long_poll(self) -> LongPollInfo:
        return cast(LongPollInfo, self.long_poll)


def _container(long_poll: object) -> AppContainer:
    return cast(
        AppContainer,
        SimpleNamespace(vk_gateway=_FakeVkGateway(long_poll)),
    )


def _long_poll(*, wall_post_new_enabled: bool) -> object:
    return SimpleNamespace(
        server="https://lp.vk.com/wh42",
        key="key",
        ts="1",
        enabled=True,
        wall_post_new_enabled=wall_post_new_enabled,
    )


async def test_vk_startup_rejects_disabled_wall_event() -> None:
    with pytest.raises(FatalStartupError) as error:
        await startup._verify_vk(_container(_long_poll(wall_post_new_enabled=False)))

    assert error.value.reason is FatalStartupReason.VK_LONGPOLL_DISABLED
    assert "wall_post_new" in str(error.value)


async def test_vk_startup_accepts_enabled_wall_event() -> None:
    await startup._verify_vk(_container(_long_poll(wall_post_new_enabled=True)))
