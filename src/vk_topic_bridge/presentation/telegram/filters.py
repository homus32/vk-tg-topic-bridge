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
TOGGLE_ALL_ENABLE = "▶️ Включить @all"
TOGGLE_ALL_DISABLE = "⏸️ Выключить @all"
TOGGLE_HASHTAGS_ENABLE = "#️⃣ Включить хештеги"
TOGGLE_HASHTAGS_DISABLE = "⏸️ Выключить хештеги"
TOGGLE_WALL_ENABLE = "🧱 Включить стену"
TOGGLE_WALL_DISABLE = "⏸️ Выключить стену"
MENU_MESSAGES_DESTINATION = "📨 Топик сообщений"
MENU_WALL_DESTINATION = "🧱 Топик стены"
MENU_TOPICS_SETTINGS = "⚙️ Топики"
MENU_CHANGE_CHAT = "🔄 Сменить чат"
MENU_DELIVERY_DIAGNOSTICS = "⚠️ Проблемы доставки"
BTN_CANCEL = "✖ Отмена"
BTN_BACK = "⬅️ Назад"
BTN_YES = "✅ Да"
BTN_REFRESH = "🔄 Обновить"
BTN_MARK_REVIEWED = "✅ Отметить просмотренной"
