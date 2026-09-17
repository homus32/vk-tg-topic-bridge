"""Registration command: run INSIDE the target chat, reply with the exact outcome.

Capability failures list every missing right verbatim so the owner can grant them all
at once (US-03, D21); a persisted chat with a failed topic refresh is reported as a
retryable partial success, never as success (D18).
"""

from __future__ import annotations

from typing import Protocol

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from vk_topic_bridge.application.admin.register_chat import (
    MissingCapabilitiesError,
    RegisterChat,
    RegisterChatResult,
)
from vk_topic_bridge.application.errors import ProvisioningError

REGISTER_COMMAND = "register"

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


async def handle_register(message: Message, register_chat: RegisterChatUseCase) -> None:
    """Execute registration for the current chat and report the precise outcome."""
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


def build_register_router(register_chat: RegisterChat) -> Router:
    """Build the router for the registration command bound to a use case instance."""
    router = Router(name="register")

    async def register(message: Message) -> None:
        await handle_register(message, register_chat)

    router.message.register(register, Command(REGISTER_COMMAND))
    return router
