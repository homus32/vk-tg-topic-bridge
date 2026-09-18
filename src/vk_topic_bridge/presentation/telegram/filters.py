"""Presentation-level filters: context predicates (never authorization by themselves)."""

from __future__ import annotations

from aiogram import Bot
from aiogram.filters import BaseFilter
from aiogram.types import Message

PRIVATE_CHAT = "private"
GROUP_CHAT_TYPES = frozenset({"group", "supergroup"})


class PrivateChatFilter(BaseFilter):
    """Accept a message only from a private chat."""

    async def __call__(self, message: Message) -> bool:
        return getattr(message.chat, "type", None) == PRIVATE_CHAT


class GroupChatFilter(BaseFilter):
    """Accept only group/supergroup chat context."""

    async def __call__(self, message: Message) -> bool:
        return getattr(message.chat, "type", None) in GROUP_CHAT_TYPES


class DirectedAtThisBotFilter(BaseFilter):
    """Accept commands and text addressed to this bot, bare or ``@username``-directed.

    The username comes from the injected ``Bot`` (cached ``bot.me()``), never a hardcoded
    literal. A message whose tokens mention another bot's username is rejected so the
    bridge never answers commands directed at a different bot in a shared group.
    """

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def __call__(self, message: Message) -> bool:
        text = getattr(message, "text", None)
        if not isinstance(text, str):
            return True
        me = await self._bot.me()
        username = (me.username or "").lstrip("@").lower()
        if not username:
            return True
        for token in text.lower().split():
            if "@" not in token:
                continue
            mention = token.split("@", 1)[1]
            if mention and mention != username:
                return False
        return True


# Text-button payloads (ReplyKeyboard buttons arrive as ordinary text messages).
TOGGLE_ALL_ENABLE = "Включить автопересылку по @all"
TOGGLE_ALL_DISABLE = "Отключить автопересылку по @all"
TOGGLE_HASHTAGS_ENABLE = "Включить автопересылку по хештегам"
TOGGLE_HASHTAGS_DISABLE = "Отключить автопересылку по хештегам"
TOGGLE_WALL_ENABLE = "Включить автопересылку постов сообщества"
TOGGLE_WALL_DISABLE = "Отключить автопересылку постов сообщества"
MENU_MESSAGES_DESTINATION = "Настроить топик назначения автопересылки сообщений чата"
MENU_WALL_DESTINATION = "Настроить топик назначения автопересылки постов стены"
MENU_TOPICS_SETTINGS = "Список настроек топиков"
MENU_CHANGE_CHAT = "Сменить Telegram-чат"
MENU_DELIVERY_DIAGNOSTICS = "Диагностика доставки"
BTN_CANCEL = "Отмена"
BTN_BACK = "← Назад"
BTN_YES = "Да"
BTN_REFRESH = "Обновить список"
BTN_MARK_REVIEWED = "Пометить просмотренной"
