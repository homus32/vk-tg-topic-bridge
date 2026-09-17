"""Minimal keyboards for the pre-Stage-7 slice: no dead buttons.

Stage 7 owns the permanent keyboard, toggles and wizards; until those handlers exist
the keyboard must stay empty rather than advertise actions the bot cannot perform.
"""

from __future__ import annotations

from aiogram.types import ReplyKeyboardMarkup


def owner_main_keyboard() -> ReplyKeyboardMarkup:
    """Return an empty but valid owner keyboard placeholder."""
    return ReplyKeyboardMarkup(keyboard=[], resize_keyboard=True)
