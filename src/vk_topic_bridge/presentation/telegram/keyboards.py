"""ReplyKeyboard factories for the Telegram Admin UI (ReplyKeyboard-first contract).

Every keyboard is a ``ReplyKeyboardMarkup`` (never inline). Button texts are the
constants from ``presentation.telegram.filters`` so handlers and keyboards cannot drift.
"""

from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

from vk_topic_bridge.application.dto.settings import BridgeSettingsState
from vk_topic_bridge.presentation.telegram import filters as btn


def owner_main_keyboard(state: BridgeSettingsState) -> ReplyKeyboardMarkup:
    """Permanent owner keyboard with state-dependent toggle labels (AC-20.1/20.2)."""
    toggle_all = btn.TOGGLE_ALL_DISABLE if state.auto_forward_all else btn.TOGGLE_ALL_ENABLE
    toggle_hashtags = (
        btn.TOGGLE_HASHTAGS_DISABLE if state.auto_forward_hashtags else btn.TOGGLE_HASHTAGS_ENABLE
    )
    toggle_wall = btn.TOGGLE_WALL_DISABLE if state.auto_forward_wall else btn.TOGGLE_WALL_ENABLE
    rows = [
        [KeyboardButton(text=toggle_all)],
        [KeyboardButton(text=toggle_hashtags)],
        [KeyboardButton(text=toggle_wall)],
        [
            KeyboardButton(text=btn.MENU_MESSAGES_DESTINATION),
            KeyboardButton(text=btn.MENU_WALL_DESTINATION),
        ],
        [KeyboardButton(text=btn.MENU_TOPICS_SETTINGS)],
        [KeyboardButton(text=btn.MENU_DELIVERY_DIAGNOSTICS)],
        [KeyboardButton(text=btn.MENU_CHANGE_CHAT)],
    ]
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Выберите действие",
    )


def unregistered_keyboard() -> ReplyKeyboardRemove:
    """Hide the keyboard while the chat is not registered."""
    return ReplyKeyboardRemove()


def ordinal_choice_keyboard() -> ReplyKeyboardMarkup:
    """Cancel row for ordinal-wait wizards."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=btn.BTN_CANCEL)]],
        resize_keyboard=True,
    )


def topics_settings_keyboard() -> ReplyKeyboardMarkup:
    """Refresh/back row for the topics settings list."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=btn.BTN_REFRESH)], [KeyboardButton(text=btn.BTN_BACK)]],
        resize_keyboard=True,
    )


def confirm_keyboard() -> ReplyKeyboardMarkup:
    """Yes/cancel row for the change-chat confirmation."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=btn.BTN_YES), KeyboardButton(text=btn.BTN_CANCEL)]],
        resize_keyboard=True,
    )


def back_keyboard() -> ReplyKeyboardMarkup:
    """Single back row for nested menus."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=btn.BTN_BACK)]],
        resize_keyboard=True,
    )
