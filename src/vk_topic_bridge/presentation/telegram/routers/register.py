"""Registration command: run INSIDE the target chat, reply with the exact outcome.

Capability failures list every missing right verbatim so the owner can grant them all
at once (US-03, D21); a persisted chat with a failed topic refresh is reported as a
retryable partial success, never as success (D18).
"""

from __future__ import annotations

from typing import Protocol

from aiogram.types import Message

from vk_topic_bridge.application.admin.register_chat import (
    MissingCapabilitiesError,
    RegisterChatResult,
)
from vk_topic_bridge.application.errors import ProvisioningError

REGISTER_COMMAND = "register"

REGISTERABLE_CHAT_TYPES: frozenset[str] = frozenset({"group", "supergroup"})

MISSING_CAPABILITY_LABELS: dict[str, str] = {
    "can_send_text": "отправка текста (can_send_text)",
    "can_send_photo": "отправка фото (can_send_photo)",
    "can_send_video": "отправка видео (can_send_video)",
    "can_send_document": "отправка документов (can_send_document)",
}


class RegisterChatUseCase(Protocol):
    """Structural type for the registration use case consumed by the handler."""

    async def execute(self, chat_id: int, title: str | None) -> RegisterChatResult: ...


def _capability_label(name: str) -> str:
    return MISSING_CAPABILITY_LABELS.get(name, name)


def _is_registerable_chat(chat_type: str) -> bool:
    """Only group/supergroup chats are valid registration targets (D16)."""
    return chat_type in REGISTERABLE_CHAT_TYPES


async def handle_register(message: Message, register_chat: RegisterChatUseCase) -> None:
    """Execute registration for the current chat and report the precise outcome."""
    # aiogram always sets chat.type; absent only in minimal message doubles.
    chat_type: str | None = getattr(message.chat, "type", None)
    if chat_type is not None and not _is_registerable_chat(chat_type):
        await message.answer(
            "Команда /register работает только в целевом чате: добавьте бота "
            "в группу или супергруппу и отправьте команду там."
        )
        return

    chat_id = message.chat.id
    title = message.chat.title

    try:
        result = await register_chat.execute(chat_id, title)
    except MissingCapabilitiesError as error:
        missing = "\n".join(f"— {_capability_label(name)}" for name in error.missing)
        await message.answer(
            "Бот не может публиковать в этом чате: не хватает прав.\n"
            f"{missing}\n"
            "Настройка не завершена: выдайте все права и повторите /register."
        )
        return
    except ProvisioningError as error:
        await message.answer(
            f"Не удалось подготовить чат: {error}\n"  # noqa: RUF001
            "Чат не зарегистрирован. Исправьте причину и повторите /register."
        )
        return

    if not result.ready:
        await message.answer(
            "Чат сохранён, но список тем получить не удалось: подготовка не завершена.\n"
            "Повторите /register, чтобы завершить настройку."
        )
        return

    await message.answer(
        f"Чат зарегистрирован. Найдено тем: {len(result.topics)}. Список тем обновлён."
    )
