"""VkPollingRuntime cursor tests: runtime dir selection, gap callback forwarding.

The polling transport class is intercepted through monkeypatch, so no network is
involved; the assertion targets are the transport constructed inside ``run()`` and the
gap notification path.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import cast

import pytest

from vk_topic_bridge.application.forwarding.forward_message import ForwardOutcome, ForwardVkMessage
from vk_topic_bridge.bootstrap import vk_consumer as consumer_module
from vk_topic_bridge.bootstrap.vk_consumer import VkPollingRuntime
from vk_topic_bridge.domain.value_objects import Author, SourceMessage
from vk_topic_bridge.infrastructure.vk.api import VkApiGateway
from vk_topic_bridge.infrastructure.vk.cursor import RuntimePathBotPolling

GROUP_ID = 555


class _Gateway:
    async def get_community_id(self) -> int:
        return GROUP_ID

    async def get_author(self, user_id: int) -> Author:
        return Author(user_id=user_id, first_name="A", last_name="B", screen_name=None)

    async def normalize_event(self, raw: Mapping[str, object], author: Author) -> SourceMessage:
        raise AssertionError("no events expected")


class _Forward:
    async def execute(self, source: SourceMessage) -> ForwardOutcome:
        raise AssertionError("no events expected")


class _GapRecorder:
    def __init__(self) -> None:
        self.kinds: list[str] = []

    async def __call__(self, kind: str) -> None:
        self.kinds.append(kind)


def _runtime(
    *,
    cursor_dir: Path | None = None,
    on_history_gap: _GapRecorder | None = None,
) -> VkPollingRuntime:
    return VkPollingRuntime(
        cast("object", object()),  # type: ignore[arg-type]
        cast(VkApiGateway, _Gateway()),
        cast(ForwardVkMessage, _Forward()),
        cursor_dir=cursor_dir,
        on_history_gap=on_history_gap,
    )


async def test_runtime_with_cursor_dir_uses_runtime_path_polling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: list[RuntimePathBotPolling] = []

    class _Stub(RuntimePathBotPolling):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)  # type: ignore[arg-type]
            created.append(self)

        async def listen(self) -> AsyncIterator[dict[str, object]]:  # type: ignore[override]
            if False:  # pragma: no cover - empty async generator
                yield {}
            return

    cursor_dir = tmp_path / "vk_cursor"
    monkeypatch.setattr(consumer_module, "RuntimePathBotPolling", _Stub)

    await _runtime(cursor_dir=cursor_dir).run()

    assert cursor_dir.exists()
    assert created, "runtime must construct the persistent cursor transport"
    polling = created[0]
    assert polling.ts_state_path == cursor_dir / "bot-polling" / f"{GROUP_ID}.json"
    assert polling.skip_old_events is False


async def test_runtime_without_cursor_dir_uses_plain_bot_polling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[object] = []
    plain = consumer_module.BotPolling

    class _Stub(plain):  # type: ignore[misc, valid-type]
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)  # type: ignore[arg-type]
            created.append(self)

        async def listen(self) -> AsyncIterator[dict[str, object]]:  # type: ignore[override]
            if False:  # pragma: no cover - empty async generator
                yield {}
            return

    monkeypatch.setattr(consumer_module, "BotPolling", _Stub)

    await _runtime().run()

    assert created, "plain mode must construct BotPolling"
    assert not isinstance(created[0], RuntimePathBotPolling)


async def test_gap_callback_reaches_notifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gaps = _GapRecorder()

    class _Stub(RuntimePathBotPolling):
        async def listen(self) -> AsyncIterator[dict[str, object]]:  # type: ignore[override]
            server = {"ts": "1", "server": "s", "key": "k"}
            await self.handle_failed_event(server, {"failed": 1, "ts": "9"})
            if False:  # pragma: no cover - empty async generator
                yield {}
            return

    monkeypatch.setattr(consumer_module, "RuntimePathBotPolling", _Stub)

    await _runtime(cursor_dir=tmp_path / "vk_cursor", on_history_gap=gaps).run()

    assert gaps.kinds == ["history_outdated"]
