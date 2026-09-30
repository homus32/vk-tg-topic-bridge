from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class KeyboardLimits:
    max_buttons: int
    max_rows: int
    max_buttons_per_row: int


@dataclass(frozen=True, slots=True)
class FittedKeyboardRows[T]:
    rows: tuple[tuple[T, ...], ...]
    dropped_buttons: int


VK_INLINE_KEYBOARD_LIMITS: Final = KeyboardLimits(
    max_buttons=10,
    max_rows=5,
    max_buttons_per_row=5,
)
VK_MAX_BUTTON_LABEL_LENGTH: Final = 40
VK_REGULAR_KEYBOARD_LIMITS: Final = KeyboardLimits(
    max_buttons=40,
    max_rows=10,
    max_buttons_per_row=5,
)


def fit_keyboard_label(label: str) -> str:
    if len(label) <= VK_MAX_BUTTON_LABEL_LENGTH:
        return label
    return f"{label[: VK_MAX_BUTTON_LABEL_LENGTH - 1]}…"


def fit_keyboard_rows[T](
    rows: Sequence[Sequence[T]], limits: KeyboardLimits
) -> FittedKeyboardRows[T]:
    fitted_rows: list[tuple[T, ...]] = []
    buttons_remaining = limits.max_buttons
    dropped_buttons = 0

    for row_index, row in enumerate(rows):
        if not row:
            continue
        if len(fitted_rows) == limits.max_rows:
            dropped_buttons += sum(len(remaining_row) for remaining_row in rows[row_index:])
            break

        row_capacity = min(limits.max_buttons_per_row, buttons_remaining)
        fitted_row = tuple(row[:row_capacity])
        if fitted_row:
            fitted_rows.append(fitted_row)
        dropped_buttons += len(row) - len(fitted_row)
        buttons_remaining -= len(fitted_row)

        if buttons_remaining == 0:
            dropped_buttons += sum(len(remaining_row) for remaining_row in rows[row_index + 1 :])
            break

    return FittedKeyboardRows(tuple(fitted_rows), dropped_buttons)
