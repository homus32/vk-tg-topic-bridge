"""Settings router: toggles, topics settings list, refresh, delivery diagnostics,
change-chat confirmation. All actions flow through application use cases."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from aiogram import Bot, F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.fsm.context import FSMContext
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from vk_topic_bridge.application.dto.finish import DeliveryReviewEntry
from vk_topic_bridge.application.dto.settings import (
    BridgeSettingsState,
    DestinationKind,
    ToggleKind,
)
from vk_topic_bridge.application.errors import ProvisioningError
from vk_topic_bridge.domain.value_objects import TopicInfo
from vk_topic_bridge.presentation.telegram import filters as btn
from vk_topic_bridge.presentation.telegram.keyboards import (
    back_keyboard,
    confirm_keyboard,
    owner_main_keyboard,
    topics_settings_keyboard,
    unregistered_keyboard,
)
from vk_topic_bridge.presentation.telegram.states import (
    ChangeChatConfirm,
    DeliveryDiagnosticsView,
)

type SettingsReader = Callable[[], Awaitable[BridgeSettingsState | None]]
type TopicsReader = Callable[[int], Awaitable[list[TopicInfo]]]


class ToggleUseCase(Protocol):
    async def execute(self, kind: ToggleKind, value: bool) -> BridgeSettingsState: ...


class RefreshUseCase(Protocol):
    async def refresh(self, chat_id: int) -> list[TopicInfo]: ...


class ResetUseCase(Protocol):
    async def execute(self) -> object: ...


class DiagnosticsReader(Protocol):
    async def list_entries(self) -> list[DeliveryReviewEntry]: ...
    async def mark_reviewed(self, delivery_id: int) -> bool: ...


UNREGISTERED_TEXT = "Telegram-чат ещё не зарегистрирован."
CHANGE_CHAT_PROMPT = (
    "Текущий Telegram-чат будет отвязан.\n"
    "Все настройки Telegram-интеграции будут сброшены до заводского состояния.\n\n"  # noqa: RUF001
    "Продолжить?"
)
RESET_DONE_TEXT = (
    "Telegram-чат отвязан. Все настройки Telegram-интеграции сброшены.\n\n"  # noqa: RUF001
    + UNREGISTERED_TEXT
)
EMPTY_DIAGNOSTICS_TEXT = "Записей нет: проблемные доставки не найдены."
DIAGNOSTICS_HEADER = "Диагностика доставки (последние записи):"
DIAGNOSTICS_PICK_HINT = "Отправьте номер записи для подробностей."
REVIEW_FORBIDDEN_TEXT = "Запись не требует отметки: она не в состоянии ambiguous."
REVIEW_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=btn.BTN_MARK_REVIEWED)],
        [KeyboardButton(text=btn.BTN_BACK)],
    ],
    resize_keyboard=True,
)

_MESSAGES_ROLE = "Сообщения VK-чата"
_WALL_ROLE = "Посты стены VK"


def _binding_block(
    role: str, kind: DestinationKind, topic_id: int | None, titles: dict[int | None, str]
) -> str:
    if kind is DestinationKind.GENERAL:
        return f"General\n└ {role}"
    if kind is DestinationKind.NAMED_TOPIC:
        title = titles.get(topic_id)
        label = title if title is not None else f"топик {topic_id}"
        return f"{label}\n└ {role}"
    return f"{role}:\nне настроено"  # noqa: RUF001


def _render_bindings(state: BridgeSettingsState, topics: list[TopicInfo]) -> str:
    titles = {topic.topic_id: topic.title for topic in topics}
    return "\n\n".join(
        [
            "Настройки топиков:",
            _binding_block(
                _MESSAGES_ROLE,
                state.messages_destination_kind(),
                state.telegram_messages_topic_id,
                titles,
            ),
            _binding_block(
                _WALL_ROLE,
                state.wall_destination_kind(),
                state.telegram_wall_topic_id,
                titles,
            ),
        ]
    )


def _destinations_missing_after_refresh(
    state: BridgeSettingsState, topics: list[TopicInfo]
) -> list[str]:
    available = {topic.topic_id for topic in topics if _topic_available(topic)}
    warnings: list[str] = []
    for role, kind, topic_id in (
        (_MESSAGES_ROLE, state.messages_destination_kind(), state.telegram_messages_topic_id),
        (_WALL_ROLE, state.wall_destination_kind(), state.telegram_wall_topic_id),
    ):
        if kind is DestinationKind.NAMED_TOPIC and topic_id not in available:
            warnings.append(f"{role}: топик {topic_id} больше не найден в чате")
    return warnings


def _topic_available(topic: TopicInfo) -> bool:
    return not topic.is_closed and not topic.is_hidden


def _render_diagnostics(entries: list[DeliveryReviewEntry]) -> str:
    lines = [DIAGNOSTICS_HEADER]
    for index, entry in enumerate(entries, start=1):
        lines.append(
            f"{index}. #{entry.delivery_id} — {entry.status} "
            f"({entry.source_type} {entry.source_key})"
        )
    lines.append("")
    lines.append(DIAGNOSTICS_PICK_HINT)
    return "\n".join(lines)


def _render_entry_detail(entry: DeliveryReviewEntry) -> str:
    lines = [
        f"Запись #{entry.delivery_id}",
        f"Статус: {entry.status}",
        f"Источник: {entry.source_type} {entry.source_key}",
        f"Назначение: чат {entry.destination_chat_id}, топик {entry.destination_topic_id}",
        f"Попыток: {entry.attempts}",
    ]
    if entry.telegram_message_ids:
        lines.append(f"Message ids: {', '.join(str(i) for i in entry.telegram_message_ids)}")
    if entry.ambiguous_at:
        lines.append(f"Время ambiguous: {entry.ambiguous_at}")
    if entry.last_error_code or entry.last_error:
        lines.append(f"Ошибка: {entry.last_error_code or ''} {entry.last_error or ''}".strip())
    lines.append("")
    lines.append("Автоматический повтор запрещён: публикация могла быть принята Telegram.")
    lines.append(f"Нажмите «{btn.BTN_MARK_REVIEWED}», если проверка выполнена вручную.")
    return "\n".join(lines)


def _parse_ordinal(text: str | None, count: int) -> int | None:
    if text is None:
        return None
    stripped = text.strip()
    if not stripped.isdigit():
        return None
    value = int(stripped)
    return value if 1 <= value <= count else None


def _sender_id(message: Message) -> int | None:
    sender = getattr(message, "from_user", None)
    value = getattr(sender, "id", None)
    return value if isinstance(value, int) else None


def _toggle_label(kind: ToggleKind, value: bool) -> str:
    if kind is ToggleKind.ALL:
        return "по @all включена" if value else "по @all отключена"
    if kind is ToggleKind.HASHTAGS:
        return "по хештегам включена" if value else "по хештегам отключена"
    return "постов сообщества включена" if value else "постов сообщества отключена"


def build_settings_router(
    *,
    toggle_use_case: ToggleUseCase,
    refresh_use_case: RefreshUseCase,
    reset_use_case: ResetUseCase,
    diagnostics_reader: DiagnosticsReader,
    settings_reader: SettingsReader,
    topics_reader: TopicsReader,
    bot: Bot,
    owner_ids: frozenset[int],
) -> Router:
    """Wire the settings surface (toggles, topics, diagnostics, change-chat)."""
    router = Router(name="settings")

    async def _current_registered(message: Message) -> BridgeSettingsState | None:
        state = await settings_reader()
        if state is None or state.telegram_chat_id is None:
            await message.answer(UNREGISTERED_TEXT, reply_markup=unregistered_keyboard())
            return None
        return state

    async def _broadcast(message: Message, text: str, state: BridgeSettingsState) -> None:
        sender = _sender_id(message)
        for owner_id in sorted(owner_ids):
            if owner_id == sender:
                continue
            await _send_owner(bot, owner_id, text, owner_main_keyboard(state))

    async def _toggle(message: Message, kind: ToggleKind) -> None:
        state = await _current_registered(message)
        if state is None:
            return
        current_value = {
            ToggleKind.ALL: state.auto_forward_all,
            ToggleKind.HASHTAGS: state.auto_forward_hashtags,
            ToggleKind.WALL: state.auto_forward_wall,
        }[kind]
        value = not current_value
        new_state = await _execute_toggle(toggle_use_case, kind, value)
        label = _toggle_label(kind, value)
        await message.answer(
            f"Автопересылка {label}.",
            reply_markup=owner_main_keyboard(new_state),
        )
        await _broadcast(message, f"Автопересылка {label}.", new_state)

    async def toggle_all(message: Message) -> None:
        await _toggle(message, ToggleKind.ALL)

    async def toggle_hashtags(message: Message) -> None:
        await _toggle(message, ToggleKind.HASHTAGS)

    async def toggle_wall(message: Message) -> None:
        await _toggle(message, ToggleKind.WALL)

    async def topics_settings(message: Message) -> None:
        state = await _current_registered(message)
        if state is None:
            return
        chat_id = state.telegram_chat_id
        assert chat_id is not None
        topics = await topics_reader(chat_id)
        await message.answer(
            _render_bindings(state, topics), reply_markup=topics_settings_keyboard()
        )

    async def refresh_topics(message: Message) -> None:
        current = await _current_registered(message)
        if current is None:
            return
        chat_id = current.telegram_chat_id
        assert chat_id is not None
        try:
            topics = await _execute_refresh(refresh_use_case, chat_id)
        except ProvisioningError as error:
            stored = await topics_reader(chat_id)
            await message.answer(
                f"Не удалось обновить список: {error}\n\n"  # noqa: RUF001
                f"{_render_bindings(current, stored)}",
                reply_markup=topics_settings_keyboard(),
            )
            return
        fresh = await settings_reader()
        body = _render_bindings(fresh if fresh is not None else current, topics)
        warnings = _destinations_missing_after_refresh(current, topics)
        if warnings:
            body = body + "\n\n" + "\n".join(warnings)
        await message.answer(body, reply_markup=topics_settings_keyboard())

    async def diagnostics(message: Message, state: FSMContext) -> None:
        current = await _current_registered(message)
        if current is None:
            return
        await state.set_state(DeliveryDiagnosticsView.list_view)
        entries = await _list_diagnostics(diagnostics_reader)
        if not entries:
            await message.answer(EMPTY_DIAGNOSTICS_TEXT, reply_markup=back_keyboard())
            return
        await message.answer(_render_diagnostics(entries), reply_markup=back_keyboard())

    async def diag_pick(message: Message, state: FSMContext) -> None:
        if await state.get_state() != DeliveryDiagnosticsView.list_view.state:
            raise SkipHandler
        entries = await _list_diagnostics(diagnostics_reader)
        ordinal = _parse_ordinal(message.text, len(entries))
        if ordinal is None:
            await message.answer(
                f"Неверный номер. {DIAGNOSTICS_PICK_HINT}",
                reply_markup=back_keyboard(),
            )
            return
        entry = entries[ordinal - 1]
        await state.update_data(delivery_id=entry.delivery_id)
        await state.set_state(DeliveryDiagnosticsView.entry_detail)
        await message.answer(_render_entry_detail(entry), reply_markup=REVIEW_KEYBOARD)

    async def diag_mark(message: Message, state: FSMContext) -> None:
        if await state.get_state() != DeliveryDiagnosticsView.entry_detail.state:
            raise SkipHandler
        data = await state.get_data()
        delivery_id = data.get("delivery_id")
        if not isinstance(delivery_id, int):
            await message.answer("Запись не выбрана.", reply_markup=back_keyboard())
            return
        marked = await _mark_reviewed(diagnostics_reader, delivery_id)
        if not marked:
            await message.answer(REVIEW_FORBIDDEN_TEXT, reply_markup=REVIEW_KEYBOARD)
            return
        await state.set_state(DeliveryDiagnosticsView.list_view)
        entries = await _list_diagnostics(diagnostics_reader)
        await message.answer(
            f"Запись #{delivery_id} отмечена просмотренной.\n\n{_render_diagnostics(entries)}",
            reply_markup=back_keyboard(),
        )

    async def diag_back(message: Message, state: FSMContext) -> None:
        current_state = await state.get_state()
        if current_state not in (
            DeliveryDiagnosticsView.list_view.state,
            DeliveryDiagnosticsView.entry_detail.state,
        ):
            raise SkipHandler
        await state.set_state(None)
        current = await settings_reader()
        if current is None or current.telegram_chat_id is None:
            await message.answer(UNREGISTERED_TEXT, reply_markup=unregistered_keyboard())
            return
        await message.answer("Возврат в главное меню.", reply_markup=owner_main_keyboard(current))

    async def change_chat(message: Message, state: FSMContext) -> None:
        current = await _current_registered(message)
        if current is None:
            return
        await state.set_state(ChangeChatConfirm.confirm)
        await message.answer(CHANGE_CHAT_PROMPT, reply_markup=confirm_keyboard())

    async def confirm_yes(message: Message, state: FSMContext) -> None:
        if await state.get_state() != ChangeChatConfirm.confirm.state:
            raise SkipHandler
        await state.clear()
        await _execute_reset(reset_use_case)
        await message.answer(RESET_DONE_TEXT, reply_markup=unregistered_keyboard())

    async def confirm_cancel(message: Message, state: FSMContext) -> None:
        if await state.get_state() != ChangeChatConfirm.confirm.state:
            raise SkipHandler
        await state.clear()
        current = await settings_reader()
        if current is None or current.telegram_chat_id is None:
            await message.answer(UNREGISTERED_TEXT, reply_markup=unregistered_keyboard())
            return
        await message.answer("Действие отменено.", reply_markup=owner_main_keyboard(current))

    router.message.register(toggle_all, F.text.in_({btn.TOGGLE_ALL_DISABLE, btn.TOGGLE_ALL_ENABLE}))
    router.message.register(
        toggle_hashtags, F.text.in_({btn.TOGGLE_HASHTAGS_DISABLE, btn.TOGGLE_HASHTAGS_ENABLE})
    )
    router.message.register(
        toggle_wall, F.text.in_({btn.TOGGLE_WALL_DISABLE, btn.TOGGLE_WALL_ENABLE})
    )
    router.message.register(topics_settings, F.text == btn.MENU_TOPICS_SETTINGS)
    router.message.register(refresh_topics, F.text == btn.BTN_REFRESH)
    router.message.register(diagnostics, F.text == btn.MENU_DELIVERY_DIAGNOSTICS)
    router.message.register(change_chat, F.text == btn.MENU_CHANGE_CHAT)
    router.message.register(diag_pick, F.text.regexp(r"^\d+$"))
    router.message.register(diag_mark, F.text == btn.BTN_MARK_REVIEWED)
    router.message.register(diag_back, F.text == btn.BTN_BACK)
    router.message.register(confirm_yes, F.text == btn.BTN_YES)
    router.message.register(confirm_cancel, F.text == btn.BTN_CANCEL)
    return router


async def _execute_toggle(
    use_case: ToggleUseCase, kind: ToggleKind, value: bool
) -> BridgeSettingsState:
    return await use_case.execute(kind, value)


async def _execute_refresh(use_case: RefreshUseCase, chat_id: int) -> list[TopicInfo]:
    return list(await use_case.refresh(chat_id))


async def _execute_reset(use_case: ResetUseCase) -> object:
    return await use_case.execute()


async def _list_diagnostics(reader: DiagnosticsReader) -> list[DeliveryReviewEntry]:
    return list(await reader.list_entries())


async def _mark_reviewed(reader: DiagnosticsReader, delivery_id: int) -> bool:
    return await reader.mark_reviewed(delivery_id)


async def _send_owner(bot: Bot, owner_id: int, text: str, markup: object) -> None:
    await bot.send_message(chat_id=owner_id, text=text, reply_markup=markup)  # type: ignore[arg-type]
