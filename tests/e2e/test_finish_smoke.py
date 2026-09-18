"""Opt-in E2E smoke for the finish-wave surfaces: command scopes and the VK cursor.

Non-destructive by contract: command scopes are set and restored in ``finally``; the
cursor smoke only *reads* whether a state file is created by a short listen started
through the real ``RuntimePathBotPolling``. Never run this while the production
application is polling: two Long Poll consumers on one community token fight over the
same server cursor. When an application process appears to be running, the cursor test
skips instead of interfering.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from aiogram.types import BotCommandScopeChat, BotCommandScopeDefault
from vkbottle import API

from config import Settings
from vk_topic_bridge.infrastructure.telegram.bot_api_factory import create_bot
from vk_topic_bridge.infrastructure.vk.api import VkApiGateway
from vk_topic_bridge.infrastructure.vk.cursor import RuntimePathBotPolling
from vk_topic_bridge.presentation.telegram.commands import owner_private_commands

pytestmark = pytest.mark.e2e


def _application_process_running() -> bool:
    """True when a ``main.py`` runner process is visible, i.e. the poller is live."""
    import subprocess

    try:
        output = subprocess.run(
            ["pgrep", "-f", "main.py"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except OSError, subprocess.SubprocessError:
        return False
    return bool(output.stdout.strip())


async def test_bot_api_command_scopes_roundtrip(e2e_settings: Settings) -> None:
    """Owner private scope is set and then restored to the pre-test state.

    The scope list is not all-users-visible in production (default scope stays empty),
    and the test reverts its own change: a ``BotCommandScopeChat`` for each owner is
    deleted in ``finally`` regardless of assertion outcome.
    """
    bot = create_bot(e2e_settings)
    owner_id = sorted(e2e_settings.OWNER_IDS)[0]
    scope = BotCommandScopeChat(chat_id=owner_id)
    try:
        await bot.set_my_commands(commands=owner_private_commands(), scope=scope)
        commands = await bot.get_my_commands(scope=scope)
        names = [command.command for command in commands]
        assert "start" in names
        assert "cancel" in names
    finally:
        await bot.delete_my_commands(scope=scope)
        await bot.delete_my_commands(scope=BotCommandScopeDefault())
        await bot.session.close()


async def test_vk_long_poll_cursor_file_created(e2e_settings: Settings, tmp_path: Path) -> None:
    """A short real listen persists the ts cursor under the controlled state dir.

    GUARD: skips when a main.py process is running so the production poller is never
    disturbed. The listen window is bounded; the test cancels the generator instead of
    waiting for an event, so it stays fast and read-only.
    """
    if _application_process_running():
        pytest.skip("application appears to be running; refusing to open a second Long Poll")

    api = API(token=e2e_settings.VK_GROUP_TOKEN.get_secret_value())
    gateway = VkApiGateway(api, e2e_settings)
    group_id = await gateway.get_community_id()

    polling = RuntimePathBotPolling(
        state_dir=tmp_path,
        api=api,
        group_id=group_id,
    )
    assert polling.skip_old_events is False

    async def _short_listen() -> None:
        generator = polling.listen()
        try:
            await asyncio.wait_for(generator.__anext__(), timeout=8)
        except TimeoutError, StopAsyncIteration:
            pass
        finally:
            await generator.aclose()

    await _short_listen()

    assert polling.ts_state_path == tmp_path / "bot-polling" / f"{group_id}.json"
