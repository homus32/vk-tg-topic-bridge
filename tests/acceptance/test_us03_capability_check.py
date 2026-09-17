"""US-03: which bot rights are missing, checked before the first forward.

AC-03.1 — the reply explicitly lists every missing required right.
AC-03.2 — with rights missing, setup is NOT reported as fully successful.
AC-03.3 — text, photo, video, document and publication capability are all checked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import cast

import pytest
from aiogram.types import Message

from tests.acceptance._fakes import (
    FULL_CAPABILITIES,
    SAMPLE_TOPICS,
    capabilities_missing,
    make_registration_harness,
)
from vk_topic_bridge.application.admin.register_chat import MissingCapabilitiesError
from vk_topic_bridge.presentation.telegram.routers.register import (
    MISSING_CAPABILITY_LABELS,
    handle_register,
)

CHAT_ID = -1001234567890
CHAT_TITLE = "Тестовый чат"


@dataclass
class FakeMessage:
    """Minimal aiogram Message stand-in for the target chat, recording replies."""

    answers: list[str] = field(default_factory=list)
    chat: object = field(default_factory=lambda: SimpleNamespace(id=CHAT_ID, title=CHAT_TITLE))

    async def answer(self, text: str, **kwargs: object) -> None:
        self.answers.append(text)


async def test_us03_ac031_missing_rights_are_listed_by_name() -> None:
    harness = make_registration_harness(
        capabilities=capabilities_missing("can_send_video", "can_send_document")
    )
    message = FakeMessage()

    await handle_register(cast(Message, message), harness.use_case)

    assert len(message.answers) == 1
    reply = message.answers[0]
    for capability in ("can_send_video", "can_send_document"):
        assert capability in reply
        assert MISSING_CAPABILITY_LABELS[capability] in reply
    assert "can_send_text" not in reply
    assert "can_send_photo" not in reply
    assert reply.count("— ") == 2


async def test_us03_ac032_setup_is_not_complete_when_rights_are_missing() -> None:
    harness = make_registration_harness(capabilities=capabilities_missing("can_send_photo"))
    message = FakeMessage()

    await handle_register(cast(Message, message), harness.use_case)

    reply = message.answers[0]
    assert "Настройка не завершена" in reply
    assert "зарегистрирован" not in reply
    persisted = await harness.settings.get()
    assert persisted is not None
    assert persisted.telegram_chat_id is None
    assert harness.topics.by_chat == {}


async def test_us03_ac033_every_publication_capability_is_checked() -> None:
    required = ("can_send_text", "can_send_photo", "can_send_video", "can_send_document")
    missing_combinations = [(), *[(name,) for name in required], required]
    for missing in missing_combinations:
        harness = make_registration_harness(
            capabilities=capabilities_missing(*missing),
            topics=list(SAMPLE_TOPICS),
        )
        message = FakeMessage()

        await handle_register(cast(Message, message), harness.use_case)

        assert harness.admin.capability_calls == [CHAT_ID]
        persisted = await harness.settings.get()
        assert persisted is not None
        if missing:
            assert persisted.telegram_chat_id is None, missing
            assert all(name in message.answers[0] for name in missing), missing
        else:
            assert persisted.telegram_chat_id == CHAT_ID, missing
            assert "зарегистрирован" in message.answers[0], missing
            assert len(harness.topics.by_chat[CHAT_ID]) == len(SAMPLE_TOPICS)


def test_us03_ac033_full_capabilities_require_no_extra_rights() -> None:
    assert FULL_CAPABILITIES.missing == ()
    assert FULL_CAPABILITIES.can_send_text is True
    assert FULL_CAPABILITIES.can_send_photo is True
    assert FULL_CAPABILITIES.can_send_video is True
    assert FULL_CAPABILITIES.can_send_document is True


async def test_us03_capability_gate_persists_nothing_and_raises() -> None:
    harness = make_registration_harness(capabilities=capabilities_missing("can_send_text"))

    with pytest.raises(MissingCapabilitiesError) as excinfo:
        await harness.use_case.execute(CHAT_ID, CHAT_TITLE)

    assert excinfo.value.missing == ("can_send_text",)
    persisted = await harness.settings.get()
    assert persisted is not None
    assert persisted.telegram_chat_id is None
    assert harness.topics.by_chat == {}
