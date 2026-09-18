"""VK persistent keyboard + Help triggers (data and factories only).

Keys are VK ``messages.send`` keyboard JSON (string form): the main keyboard is
persistent and button-based; FSM-step keyboards keep only cancel/back/confirm rows.
No inline keyboards and no one_time_keyboards are used anywhere (frozen UI contract).
"""

from __future__ import annotations

import json

HELP_TRIGGERS: frozenset[str] = frozenset({"начать", "помощь", "помоги", "help"})
BTN_ALIASES = "Алиасы"
BTN_HELP = "Помощь"
BTN_CANCEL = "Отмена"
BTN_BACK = "← Назад"
BTN_ADD = "Добавить"
BTN_EDIT = "Изменить"
BTN_DELETE = "Удалить"
BTN_YES = "Да"

_POSITIVE = "positive"
_NEGATIVE = "negative"
_DEFAULT = "default"


def _text_button(label: str, color: str | None = None) -> dict[str, object]:
    return {"action": {"type": "text", "label": label}, "color": color or _DEFAULT}


def _keyboard(rows: list[list[dict[str, object]]]) -> str:
    return json.dumps(
        {"one_time": False, "inline": False, "buttons": rows},
        ensure_ascii=False,
    )


def main_keyboard_json() -> str:
    """Persistent ``Алиасы``/``Помощь`` keyboard (VK JSON, non-inline, non-one_time)."""
    return _keyboard([[_text_button(BTN_ALIASES), _text_button(BTN_HELP)]])


def wait_destination_keyboard_json() -> str:
    """Keyboard with only ``Отмена`` for WAIT_DESTINATION."""
    return _keyboard([[_text_button(BTN_CANCEL, _NEGATIVE)]])


def alias_menu_keyboard_json() -> str:
    """Rows Добавить/Изменить/Удалить + ← Назад."""
    return _keyboard(
        [
            [_text_button(BTN_ADD), _text_button(BTN_EDIT)],
            [_text_button(BTN_DELETE)],
            [_text_button(BTN_BACK)],
        ]
    )


def confirm_keyboard_json() -> str:
    """Да/Отмена (alias delete confirmation)."""
    return _keyboard([[_text_button(BTN_YES, _POSITIVE), _text_button(BTN_CANCEL, _NEGATIVE)]])


def cancel_keyboard_json() -> str:
    """Single Отмена row (topic-ordinal waits)."""
    return _keyboard([[_text_button(BTN_CANCEL, _NEGATIVE)]])


def is_help_trigger(text: str) -> bool:
    """Case-insensitive match against HELP_TRIGGERS after strip()."""
    normalized = text.strip().lower()
    return normalized in HELP_TRIGGERS
