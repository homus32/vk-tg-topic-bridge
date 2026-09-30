from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import TypeAdapter

from vk_topic_bridge.domain.policies.keyboard_policy import (
    VK_INLINE_KEYBOARD_LIMITS,
    VK_REGULAR_KEYBOARD_LIMITS,
    fit_keyboard_rows,
)

_KEYBOARD_ADAPTER = TypeAdapter(dict[str, object])
_BUTTON_ROWS_ADAPTER = TypeAdapter(list[list[object]])


@dataclass(frozen=True, slots=True)
class FittedVkKeyboard:
    keyboard_json: str
    inline: bool
    dropped_buttons: int


def fit_vk_keyboard(keyboard_json: str) -> FittedVkKeyboard:
    keyboard = _KEYBOARD_ADAPTER.validate_json(keyboard_json)
    inline = keyboard.get("inline") is True
    limits = VK_INLINE_KEYBOARD_LIMITS if inline else VK_REGULAR_KEYBOARD_LIMITS
    rows = _BUTTON_ROWS_ADAPTER.validate_python(keyboard["buttons"])
    fitted = fit_keyboard_rows(rows, limits)
    original_rows = tuple(tuple(row) for row in rows)
    if fitted.rows == original_rows:
        fitted_json = keyboard_json
    else:
        keyboard["buttons"] = [list(row) for row in fitted.rows]
        fitted_json = json.dumps(keyboard, ensure_ascii=True)
    return FittedVkKeyboard(
        keyboard_json=fitted_json,
        inline=inline,
        dropped_buttons=fitted.dropped_buttons,
    )
