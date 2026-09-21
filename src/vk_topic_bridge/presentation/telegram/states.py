"""Extended presentation FSM states (StatesGroup definitions only, no behavior)."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class RegistrationMaster(StatesGroup):
    """Cross-chat registration master (GLOBAL_USER strategy: one per owner)."""

    pending = State()


class MessagesDestinationWizard(StatesGroup):
    """Messages destination selection; General is a selectable option."""

    wait_ordinal = State()


class WallDestinationWizard(StatesGroup):
    """Wall destination selection; General is a selectable option."""

    wait_ordinal = State()


class TopicSettingsView(StatesGroup):
    view = State()


class DeliveryDiagnosticsView(StatesGroup):
    """Compact 'Диагностика доставки' view with inline details/actions."""

    list_view = State()
    entry_detail = State()


class ChangeChatConfirm(StatesGroup):
    """Factory-reset confirmation (US-21): Да/Отмена only."""

    confirm = State()
