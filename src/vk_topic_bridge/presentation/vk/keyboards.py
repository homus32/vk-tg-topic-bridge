from __future__ import annotations

from collections.abc import Sequence

from vkbottle.tools.keyboard import Keyboard
from vkbottle.tools.keyboard.action import Callback, Text

HELP_TRIGGERS: frozenset[str] = frozenset({"начать", "помощь", "помоги", "help"})
BTN_ALIASES = "Алиасы"
BTN_HELP = "Помощь"
BTN_CANCEL = "Отмена"
BTN_BACK = "← Назад"
BTN_EDIT = "Добавить/Изменить"
BTN_DELETE = "Удалить"


def _callback_button(label: str, action: str, topic_id: int | None = None) -> Callback:
    payload: dict[str, object] = {"action": action}
    if action == "topic":
        payload["topic_id"] = topic_id
    return Callback(label, payload)


def _keyboard(rows: Sequence[Sequence[Callback]]) -> str:
    keyboard = Keyboard(inline=True)
    for row in rows:
        for action in row:
            keyboard.add(action)
        keyboard.row()
    return keyboard.get_json()


def _text_keyboard(rows: Sequence[Sequence[Text]]) -> str:
    keyboard = Keyboard(inline=False)
    for row in rows:
        for action in row:
            keyboard.add(action)
        keyboard.row()
    return keyboard.get_json()


def main_keyboard_json() -> str:
    return _text_keyboard([[Text(BTN_ALIASES), Text(BTN_HELP)]])


def wait_destination_keyboard_json() -> str:
    return _text_keyboard([[Text(BTN_CANCEL)]])


def alias_menu_keyboard_json() -> str:
    return _text_keyboard(
        [
            [Text(BTN_EDIT)],
            [Text(BTN_DELETE)],
            [Text(BTN_BACK)],
        ]
    )


def cancel_keyboard_json() -> str:
    return wait_destination_keyboard_json()


def topic_selection_keyboard(topics: Sequence[tuple[int | None, str]]) -> str:
    rows = [[_callback_button(title, "topic", topic_id)] for topic_id, title in topics]
    rows.append([_callback_button(BTN_CANCEL, "cancel")])
    return _keyboard(rows)


def is_help_trigger(text: str) -> bool:
    """Case-insensitive match against HELP_TRIGGERS after strip()."""
    normalized = text.strip().lower()
    return normalized in HELP_TRIGGERS
