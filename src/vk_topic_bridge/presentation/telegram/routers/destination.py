# ruff: noqa: E501 (the frozen stage-7 marker below must stay on one exact line)
"""Temporary pre-Stage-7 destination commands: list forum topics, confirm the choice.

TODO(stage-7): remove temporary destination-topic provisioning when Telegram Admin UI provides destination selection.

``/topics`` prints ``index. title (id: N)``; ``/set_topic N`` resolves the ordinal and
delegates to ``SelectDestination``, which performs the real Bot API send proof before
persisting. Both commands run only in the target group/supergroup chat and leave the
persisted state untouched on any failure.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from vk_topic_bridge.application.errors import ProvisioningError
from vk_topic_bridge.domain.value_objects import TopicInfo

TOPICS_COMMAND = "topics"
SET_TOPIC_COMMAND = "set_topic"

TARGET_CHAT_TYPES: frozenset[str] = frozenset({"group", "supergroup"})

TARGET_CHAT_REQUIRED_TEXT = (
    "Команда работает только в целевом чате: добавьте бота в группу или супергруппу "
    "и отправьте команду там."
)
NOT_REGISTERED_TEXT = "Сначала зарегистрируйте чат командой /register."
EMPTY_TOPICS_TEXT = "Темы не найдены. Выполните /register в этом чате, чтобы загрузить список тем."

type TopicsReader = Callable[[int], Awaitable[list[TopicInfo]]]
type RunIdFactory = Callable[[], str]


class DestinationSelector(Protocol):
    """Structural type for the destination use case consumed by the handlers."""

    async def execute(self, chat_id: int, topic: TopicInfo, run_id: str) -> int: ...


def default_run_id() -> str:
    """Unique per-invocation id used to correlate the confirmation message with evidence."""
    return f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid4().hex[:8]}"


def _is_target_chat(message: Message) -> bool:
    chat_type: str | None = getattr(message.chat, "type", None)
    return chat_type is None or chat_type in TARGET_CHAT_TYPES


def _format_topics(topics: list[TopicInfo]) -> str:
    lines: list[str] = []
    for index, topic in enumerate(topics, start=1):
        if topic.topic_id is None:
            lines.append(f"{index}. {topic.title} (служебная тема, не выбирается)")
        else:
            lines.append(f"{index}. {topic.title} (id: {topic.topic_id})")
    return "\n".join(lines)


def _parse_ordinal(text: str | None) -> int | None:
    if not text:
        return None
    parts = text.split(maxsplit=1)
    if len(parts) != 2:
        return None
    try:
        return int(parts[1].strip())
    except ValueError:
        return None


async def handle_topics(message: Message, topics_reader: TopicsReader) -> None:
    """Print the numbered topic list for the current chat."""
    if not _is_target_chat(message):
        await message.answer(TARGET_CHAT_REQUIRED_TEXT)
        return

    topics = await topics_reader(message.chat.id)
    if not topics:
        await message.answer(EMPTY_TOPICS_TEXT)
        return

    await message.answer(
        f"Темы чата:\n{_format_topics(topics)}\n\n"
        f"Выберите тему назначения командой /{SET_TOPIC_COMMAND} <номер>."
    )


async def handle_set_topic(
    message: Message,
    select_destination: DestinationSelector,
    topics_reader: TopicsReader,
    *,
    run_id_factory: RunIdFactory = default_run_id,
) -> None:
    """Resolve the ordinal, prove the topic by a real send, and only then persist it."""
    if not _is_target_chat(message):
        await message.answer(TARGET_CHAT_REQUIRED_TEXT)
        return

    ordinal = _parse_ordinal(message.text)
    if ordinal is None:
        await message.answer(
            f"Укажите номер темы: /{SET_TOPIC_COMMAND} <номер>. Список тем — /{TOPICS_COMMAND}."
        )
        return

    topics = await topics_reader(message.chat.id)
    if not topics:
        await message.answer(EMPTY_TOPICS_TEXT)
        return

    if ordinal < 1 or ordinal > len(topics):
        await message.answer(
            f"Темы с номером {ordinal} нет: доступны номера с 1 по {len(topics)}. "  # noqa: RUF001
            f"Список тем — /{TOPICS_COMMAND}."
        )
        return

    topic = topics[ordinal - 1]
    if topic.topic_id is None:
        await message.answer(
            f"Тема «{topic.title}» служебная и не может быть темой назначения. "
            f"Выберите именованную тему: список — /{TOPICS_COMMAND}."
        )
        return
    try:
        message_id = await select_destination.execute(message.chat.id, topic, run_id_factory())
    except ProvisioningError as error:
        await message.answer(
            f"Не удалось подтвердить тему «{topic.title}»: {error}\n"  # noqa: RUF001
            "Ничего не сохранено. Проверьте права бота и повторите попытку."
        )
        return
    except Exception as error:
        await message.answer(
            f"Не удалось подтвердить тему «{topic.title}» ({type(error).__name__}).\n"  # noqa: RUF001
            "Ничего не сохранено. Повторите попытку позже."
        )
        return

    await message.answer(
        f"Тема «{topic.title}» подтверждена тестовым сообщением "
        f"(message_id: {message_id}) и сохранена как тема сообщений VK-чата."
    )


def build_destination_router(
    select_destination: DestinationSelector,
    topics_reader: TopicsReader,
    *,
    run_id_factory: RunIdFactory = default_run_id,
) -> Router:
    """Build the router for the temporary destination commands."""
    router = Router(name="destination")

    async def topics(message: Message) -> None:
        await handle_topics(message, topics_reader)

    async def set_topic(message: Message) -> None:
        await handle_set_topic(
            message,
            select_destination,
            topics_reader,
            run_id_factory=run_id_factory,
        )

    router.message.register(topics, Command(TOPICS_COMMAND))
    router.message.register(set_topic, Command(SET_TOPIC_COMMAND))
    return router
