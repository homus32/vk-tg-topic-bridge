from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from vkbottle.tools.keyboard import Keyboard, KeyboardButtonColor
from vkbottle.tools.keyboard.action import Callback, Text

from vk_topic_bridge.domain.policies.keyboard_policy import (
    VK_INLINE_KEYBOARD_LIMITS,
    VK_MAX_BUTTON_LABEL_LENGTH,
    KeyboardLimits,
    fit_keyboard_label,
    fit_keyboard_rows,
)

HELP_TRIGGERS: frozenset[str] = frozenset({"начать", "помощь", "помоги", "help"})
BTN_ALIASES = "🏷 Алиасы"
BTN_HELP = "❓ Помощь"
BTN_CANCEL = "✖ Отмена"
BTN_BACK = "⬅️ Назад"
BTN_EDIT = "➕ Добавить / изменить"
BTN_DELETE = "🗑 Удалить"

_TOPIC_SELECTION_LIMITS: Final = KeyboardLimits(
    max_buttons=VK_INLINE_KEYBOARD_LIMITS.max_buttons - 1,
    max_rows=VK_INLINE_KEYBOARD_LIMITS.max_rows - 1,
    max_buttons_per_row=VK_INLINE_KEYBOARD_LIMITS.max_buttons_per_row,
)
_TOPICS_PER_ROW: Final = 2


@dataclass(frozen=True, slots=True)
class TopicSelectionKeyboard:
    keyboard_json: str
    shown_topic_count: int
    total_topic_count: int
    shortened_label_count: int

    def with_notice(self, text: str) -> str:
        notices: list[str] = []
        if self.shown_topic_count < self.total_topic_count:
            notices.append(
                "⚠️ Не все кнопки поместились: показаны первые "
                f"{self.shown_topic_count} из {self.total_topic_count} топиков."
            )
        if self.shortened_label_count:
            notices.append(
                f"Некоторые названия кнопок сокращены до {VK_MAX_BUTTON_LABEL_LENGTH} символов."
            )
        if not notices:
            return text
        return f"{text}\n\n" + "\n".join(notices)


def _callback_button(label: str, action: str, topic_id: int | None = None) -> Callback:
    payload: dict[str, object] = {"action": action}
    if action == "topic":
        payload["topic_id"] = topic_id
    return Callback(label, payload)


def _keyboard(rows: Sequence[Sequence[tuple[Callback, KeyboardButtonColor]]]) -> str:
    keyboard = Keyboard(inline=True)
    for row in rows:
        for action, color in row:
            keyboard.add(action, color=color)
        keyboard.row()
    return keyboard.get_json()


def _text_keyboard(rows: Sequence[Sequence[tuple[Text, KeyboardButtonColor]]]) -> str:
    keyboard = Keyboard(inline=False)
    for row in rows:
        for action, color in row:
            keyboard.add(action, color=color)
        keyboard.row()
    return keyboard.get_json()


def main_keyboard_json() -> str:
    return _text_keyboard(
        [
            [
                (Text(BTN_ALIASES), KeyboardButtonColor.PRIMARY),
                (Text(BTN_HELP), KeyboardButtonColor.SECONDARY),
            ]
        ]
    )


def wait_destination_keyboard_json() -> str:
    return _text_keyboard([[(Text(BTN_CANCEL), KeyboardButtonColor.SECONDARY)]])


def alias_menu_keyboard_json() -> str:
    return _text_keyboard(
        [
            [(Text(BTN_EDIT), KeyboardButtonColor.POSITIVE)],
            [(Text(BTN_DELETE), KeyboardButtonColor.NEGATIVE)],
            [(Text(BTN_BACK), KeyboardButtonColor.SECONDARY)],
        ]
    )


def cancel_keyboard_json() -> str:
    return wait_destination_keyboard_json()


def topic_selection_keyboard(
    topics: Sequence[tuple[int | None, str]],
) -> TopicSelectionKeyboard:
    topic_buttons = [
        (
            _callback_button(fit_keyboard_label(title), "topic", topic_id),
            KeyboardButtonColor.POSITIVE,
        )
        for topic_id, title in topics
    ]
    rows = [
        topic_buttons[start : start + _TOPICS_PER_ROW]
        for start in range(0, len(topic_buttons), _TOPICS_PER_ROW)
    ]
    fitted = fit_keyboard_rows(rows, _TOPIC_SELECTION_LIMITS)
    visible_rows = [list(row) for row in fitted.rows]
    visible_rows.append([(_callback_button(BTN_CANCEL, "cancel"), KeyboardButtonColor.SECONDARY)])
    shown_topic_count = len(topics) - fitted.dropped_buttons
    return TopicSelectionKeyboard(
        keyboard_json=_keyboard(visible_rows),
        shown_topic_count=shown_topic_count,
        total_topic_count=len(topics),
        shortened_label_count=sum(
            fit_keyboard_label(title) != title for _, title in topics[:shown_topic_count]
        ),
    )


def is_help_trigger(text: str) -> bool:
    """Case-insensitive match against HELP_TRIGGERS after strip()."""
    normalized = text.strip().lower()
    return normalized in HELP_TRIGGERS
