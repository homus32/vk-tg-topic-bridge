"""Manual composition root: one frozen container, no DI framework, no I/O at build time.

``build_container`` only constructs objects and registers routers. It never connects a
client and never sends a request; every network interaction happens in the startup
sequence (``bootstrap.startup``) after the container exists.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.fsm.strategy import FSMStrategy
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from config import Settings
from vk_topic_bridge.application.admin.destination_admin import (
    ChangeChatOutcome,
    DestinationConfirmationResult,
    RefreshTopicsV2,
    ResetBridge,
    SelectDestinationV2,
)
from vk_topic_bridge.application.admin.refresh_topics import RefreshTopics
from vk_topic_bridge.application.admin.register_chat import RegisterChat, RegisterChatResult
from vk_topic_bridge.application.admin.toggle_settings import ToggleSettings
from vk_topic_bridge.application.dto.finish import DeliveryReviewEntry, delivery_review_entry
from vk_topic_bridge.application.dto.readiness import ReadinessState
from vk_topic_bridge.application.dto.settings import BridgeSettingsState
from vk_topic_bridge.application.forwarding.forward_message import ForwardVkMessage
from vk_topic_bridge.application.forwarding.forward_wall import ForwardWallPost
from vk_topic_bridge.application.manual.aliasing import AliasManager, ManualForwarding
from vk_topic_bridge.application.manual.publish_manual import PublishManualMessage
from vk_topic_bridge.application.notifications.owner_notifier import (
    OwnerNotifier,
    history_gap_notification_text,
)
from vk_topic_bridge.application.ports.telegram import TelegramAdminPort
from vk_topic_bridge.application.ports.unit_of_work import UnitOfWork
from vk_topic_bridge.application.readiness import InMemoryReadinessGate
from vk_topic_bridge.bootstrap.vk_consumer import VkPollingRuntime
from vk_topic_bridge.domain.value_objects import Author, SourceMessage, TopicInfo
from vk_topic_bridge.infrastructure.db.engine import create_async_engine, create_session_factory
from vk_topic_bridge.infrastructure.db.repositories.unit_of_work import SqlAlchemyUnitOfWork
from vk_topic_bridge.infrastructure.telegram.bot_api_factory import create_bot
from vk_topic_bridge.infrastructure.telegram.command_menu import CommandMenuSynchronizer
from vk_topic_bridge.infrastructure.telegram.mtproto import TelethonAdapter, TelethonUserClient
from vk_topic_bridge.infrastructure.telegram.publisher import BotApiAdminPort, BotApiPublisher
from vk_topic_bridge.infrastructure.vk.api import RawVkApi, VkApiGateway
from vk_topic_bridge.infrastructure.vk.mapper import extract_forwarded_payload, map_manual_source
from vk_topic_bridge.infrastructure.vk.media_downloader import VkMediaDownloader
from vk_topic_bridge.presentation.telegram.middlewares import OwnerOnlyMiddleware
from vk_topic_bridge.presentation.telegram.registration_session import RegistrationCoordinator
from vk_topic_bridge.presentation.telegram.routers.destinations import (
    build_destinations_router,
    default_run_id,
)
from vk_topic_bridge.presentation.telegram.routers.registration import build_registration_router
from vk_topic_bridge.presentation.telegram.routers.root import build_root_router
from vk_topic_bridge.presentation.telegram.routers.settings import build_settings_router
from vk_topic_bridge.presentation.vk.handlers import SourceResolver, VkUiDispatcher, VkUiMessage
from vk_topic_bridge.presentation.vk.states import VkSessionStore

type SettingsReader = Callable[[], Awaitable[BridgeSettingsState | None]]
type TopicsReader = Callable[[int], Awaitable[list[TopicInfo]]]
type PollingStop = Callable[[], Awaitable[None]]
type PollingTask = Callable[[], Awaitable[None]]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AppContainer:
    """Every process-wide collaborator, wired once and shared by handlers and pollers."""

    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    uow_factory: Callable[[], UnitOfWork]
    bot: Bot
    dispatcher: Dispatcher
    telethon_client: TelethonUserClient
    telethon_adapter: TelethonAdapter
    vk_api_raw: RawVkApi
    vk_gateway: VkApiGateway
    publisher: BotApiPublisher
    admin_port: BotApiAdminPort
    readiness: InMemoryReadinessGate
    register_chat: RegisterChat
    refresh_topics: RefreshTopics
    refresh_topics_v2: RefreshTopicsV2
    select_destination: SelectDestinationV2
    reset_bridge: ResetBridge
    toggle_settings: ToggleSettings
    diagnostics_reader: DiagnosticsReader
    command_menu: CommandMenuSynchronizer
    forward_message: ForwardVkMessage
    forward_wall: ForwardWallPost
    owner_notifier: OwnerNotifier
    vk_ui_dispatcher: VkUiDispatcher | None
    http_session: aiohttp.ClientSession
    telegram_polling: PollingTask
    vk_polling: PollingTask
    vk_polling_stop: PollingStop | None = None
    polling_stop: PollingStop | None = None


def _build_uow_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> Callable[[], UnitOfWork]:
    def factory() -> UnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    return factory


def _build_settings_reader(uow_factory: Callable[[], UnitOfWork]) -> SettingsReader:
    async def read() -> BridgeSettingsState | None:
        async with uow_factory() as uow:
            return await uow.bridge_settings.get()

    return read


def _build_topics_reader(uow_factory: Callable[[], UnitOfWork]) -> TopicsReader:
    """Read the persisted topic list for the registered chat, or nothing when unregistered."""

    async def read(chat_id: int) -> list[TopicInfo]:
        async with uow_factory() as uow:
            state = await uow.bridge_settings.get()
            if state is None or state.telegram_chat_id != chat_id:
                return []
            return await uow.telegram_topics.list(chat_id)

    return read


class DiagnosticsReader:
    """Bootstrap wrapper over the delivery ledger for the owner diagnostics view."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def list_entries(self) -> list[DeliveryReviewEntry]:
        async with self._uow_factory() as uow:
            rows = await uow.deliveries.list_failed_terminal(limit=20)
        return [delivery_review_entry(row) for row in rows]

    async def mark_reviewed(self, delivery_id: int) -> bool:
        async with self._uow_factory() as uow:
            marked = await uow.deliveries.mark_reviewed(delivery_id)
            await uow.commit()
        return marked


def _build_telegram_polling(bot: Bot, dispatcher: Dispatcher) -> PollingTask:
    async def start() -> None:
        logger.info("telegram polling started")
        try:
            await dispatcher.start_polling(bot, handle_signals=False)
        finally:
            logger.info("telegram polling stopped")

    return start


def _build_vk_polling(
    api: RawVkApi,
    gateway: VkApiGateway,
    forward: ForwardVkMessage,
    forward_wall: ForwardWallPost,
    ui_router: object | None,
    *,
    cursor_dir: Path,
    on_history_gap: Callable[[str], Awaitable[None]] | None = None,
) -> tuple[PollingTask, PollingStop]:
    """Build the VK Long Poll coroutine and its stop callable; performs no I/O.

    The community id is resolved inside the coroutine, so container construction stays
    network-free and the poller can be started by the lifecycle runner.
    """
    runtime = VkPollingRuntime(
        api,
        gateway,
        forward,
        forward_wall=forward_wall,
        ui_router=ui_router,
        cursor_dir=cursor_dir,
        on_history_gap=on_history_gap,
    )
    return runtime.run, runtime.stop


class ReadinessAwareRegisterChat(RegisterChat):
    """RegisterChat that promotes readiness once registration is fully ready."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        admin: TelegramAdminPort,
        refresh: RefreshTopics,
        readiness: InMemoryReadinessGate,
    ) -> None:
        super().__init__(uow_factory, admin, refresh)
        self._readiness = readiness

    async def execute(self, chat_id: int, title: str | None) -> RegisterChatResult:
        result = await super().execute(chat_id, title)
        if result.ready:
            self._readiness.advance(ReadinessState.TOPICS_READY)
        return result


class ReadinessAwareSelectDestinationV2(SelectDestinationV2):
    """SelectDestinationV2 that promotes readiness after a confirmed named-topic send."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        admin: TelegramAdminPort,
        readiness: InMemoryReadinessGate,
    ) -> None:
        super().__init__(uow_factory, admin)
        self._readiness = readiness

    async def execute(
        self, chat_id: int, topic: TopicInfo, kind: str, run_id: str
    ) -> DestinationConfirmationResult:
        result = await super().execute(chat_id, topic, kind, run_id)
        if result.message_id is not None:
            self._readiness.advance(ReadinessState.DESTINATION_CONFIRMED)
            self._readiness.advance(ReadinessState.FORWARDING_ENABLED)
        return result


class ReadinessAwareResetBridge(ResetBridge):
    """ResetBridge that returns the process readiness gate to its factory state."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        readiness: InMemoryReadinessGate,
    ) -> None:
        super().__init__(uow_factory)
        self._readiness = readiness

    async def execute(self) -> ChangeChatOutcome:
        outcome = await super().execute()
        self._readiness.reset()
        return outcome


def _history_gap_notifier(notifier: OwnerNotifier) -> Callable[[str], Awaitable[None]]:
    """Build the long-poll gap callback; a failed broadcast never kills the poller."""

    async def notify(kind: str) -> None:
        logger.warning("vk history gap detected", extra={"reason": kind})
        try:
            await notifier.notify_all(history_gap_notification_text(kind=kind))
            logger.debug("vk history gap owner notification completed", extra={"reason": kind})
        except Exception:
            logger.exception("history gap owner notification failed")

    return notify


def _manual_source_resolver(vk_gateway: VkApiGateway) -> SourceResolver:
    """Resolve DM content without network access: forwarded objects are already full.

    Long Poll ``fwd_messages`` elements carry text and typed attachments (schema-verified),
    so the common path is pure mapping. Nested forwards are never expanded (guardrail);
    a forward whose attachments are cropped simply yields the warning path downstream.
    """

    async def resolve(message: VkUiMessage) -> SourceMessage | None:
        logger.debug(
            "manual VK source resolution started",
            extra={"from_id": message.from_id, "peer_id": message.peer_id},
        )
        raw = message.raw
        if not raw:
            logger.debug("manual VK source resolution skipped: raw payload missing")
            return None
        fwd = extract_forwarded_payload(raw)
        author = await _resolve_content_author(vk_gateway, fwd, message)
        source = map_manual_source(
            message=raw,
            fwd=fwd,
            author=author,
            initiator_id=message.from_id,
        )
        if source is None:
            logger.debug(
                "manual VK source resolution skipped: source missing",
                extra={"from_id": message.from_id},
            )
            return None
        logger.debug(
            "manual VK source resolution completed",
            extra={"from_id": message.from_id, "attachment_count": len(source.attachments)},
        )
        return source

    return resolve


async def _resolve_content_author(
    vk_gateway: VkApiGateway,
    fwd: Mapping[str, object] | None,
    message: VkUiMessage,
) -> Author:
    source_id = fwd.get("from_id") if fwd is not None else None
    if isinstance(source_id, int) and not isinstance(source_id, bool):
        return await vk_gateway.get_author(source_id)
    return Author(user_id=message.from_id, first_name="", last_name="", screen_name=None)


def _build_vk_ui_dispatcher(
    uow_factory: Callable[[], UnitOfWork],
    publisher: BotApiPublisher,
    vk_gateway: VkApiGateway,
    downloader: VkMediaDownloader,
) -> VkUiDispatcher:
    """Wire the VK presentation dispatcher over the shared manual/alias use cases."""
    return VkUiDispatcher(
        VkSessionStore(),
        vk_gateway,
        ManualForwarding(uow_factory),
        AliasManager(uow_factory),
        PublishManualMessage(
            uow_factory=uow_factory,
            publisher=publisher,
            plan_publisher=publisher,
            downloader=downloader,
        ),
        source_resolver=_manual_source_resolver(vk_gateway),
    )


def _register_routers(
    dispatcher: Dispatcher,
    settings: Settings,
    register_chat: RegisterChat,
    bot: Bot,
    reader: SettingsReader,
    topics_reader: TopicsReader,
    toggle_use_case: ToggleSettings,
    refresh_topics_v2: RefreshTopicsV2,
    reset_bridge: ResetBridge,
    diagnostics_reader: DiagnosticsReader,
    command_menu: CommandMenuSynchronizer,
    select_destination: SelectDestinationV2,
) -> None:
    owner_ids = frozenset(settings.OWNER_IDS)
    registration = RegistrationCoordinator()
    dispatcher.message.outer_middleware(OwnerOnlyMiddleware(owner_ids))
    dispatcher.include_router(
        build_registration_router(
            register_chat,
            reader,
            bot,
            menu_sync=command_menu,
            registration=registration,
        )
    )
    dispatcher.include_router(
        build_destinations_router(
            select_destination,
            reader,
            topics_reader,
            run_id_factory=default_run_id,
        )
    )
    dispatcher.include_router(
        build_settings_router(
            toggle_use_case=toggle_use_case,
            refresh_use_case=refresh_topics_v2,
            reset_use_case=reset_bridge,
            diagnostics_reader=diagnostics_reader,
            settings_reader=reader,
            topics_reader=topics_reader,
            bot=bot,
            owner_ids=owner_ids,
        )
    )
    # Root last: its catch-all hint must only see text no feature router claimed.
    dispatcher.include_router(
        build_root_router(reader, registration=registration, menu_sync=command_menu)
    )
    logger.info("telegram routers registered", extra={"owner_count": len(owner_ids)})


def build_dispatcher() -> Dispatcher:
    """GLOBAL_USER FSM: the registration master spans private /start and group /register."""
    return Dispatcher(fsm_strategy=FSMStrategy.GLOBAL_USER)


def build_container(
    settings: Settings,
    *,
    telethon_client: TelethonUserClient,
    vk_api_raw: RawVkApi,
) -> AppContainer:
    """Construct the whole object graph; never connects, never sends."""
    logger.info("application container build started")
    engine = create_async_engine(settings.DATABASE_URL)
    session_factory = create_session_factory(engine)
    uow_factory = _build_uow_factory(session_factory)

    bot = create_bot(settings)
    dispatcher = build_dispatcher()
    telethon_adapter = TelethonAdapter(telethon_client)
    vk_gateway = VkApiGateway(vk_api_raw, settings)
    publisher = BotApiPublisher(bot)
    admin_port = BotApiAdminPort(bot)
    readiness = InMemoryReadinessGate()
    http_session = aiohttp.ClientSession()

    refresh_topics = RefreshTopics(uow_factory, telethon_adapter)
    refresh_topics_v2 = RefreshTopicsV2(uow_factory, telethon_adapter)
    register_chat = ReadinessAwareRegisterChat(uow_factory, admin_port, refresh_topics, readiness)
    select_destination = ReadinessAwareSelectDestinationV2(uow_factory, admin_port, readiness)
    reset_bridge = ReadinessAwareResetBridge(uow_factory, readiness)
    toggle_settings = ToggleSettings(uow_factory)
    diagnostics_reader = DiagnosticsReader(uow_factory)
    command_menu = CommandMenuSynchronizer(bot, frozenset(settings.OWNER_IDS))
    owner_notifier = OwnerNotifier(frozenset(settings.OWNER_IDS), publisher)
    downloader = VkMediaDownloader(vk_api_raw, http_session, settings.VK_MEDIA_DIR)
    forward_message = ForwardVkMessage(
        uow_factory=uow_factory,
        plan_publisher=publisher,
        vk=vk_gateway,
        downloader=downloader,
        notifier=owner_notifier,
    )
    forward_wall = ForwardWallPost(
        uow_factory=uow_factory,
        plan_publisher=publisher,
        downloader=downloader,
        notifier=owner_notifier,
    )
    vk_ui_dispatcher = _build_vk_ui_dispatcher(uow_factory, publisher, vk_gateway, downloader)

    _register_routers(
        dispatcher,
        settings,
        register_chat,
        bot,
        _build_settings_reader(uow_factory),
        _build_topics_reader(uow_factory),
        toggle_settings,
        refresh_topics_v2,
        reset_bridge,
        diagnostics_reader,
        command_menu,
        select_destination,
    )

    vk_polling, vk_polling_stop = _build_vk_polling(
        vk_api_raw,
        vk_gateway,
        forward_message,
        forward_wall,
        vk_ui_dispatcher,
        cursor_dir=settings.VK_CURSOR_DIR,
        on_history_gap=_history_gap_notifier(owner_notifier),
    )

    logger.info("application container build completed")

    return AppContainer(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        uow_factory=uow_factory,
        bot=bot,
        dispatcher=dispatcher,
        telethon_client=telethon_client,
        telethon_adapter=telethon_adapter,
        vk_api_raw=vk_api_raw,
        vk_gateway=vk_gateway,
        publisher=publisher,
        admin_port=admin_port,
        readiness=readiness,
        register_chat=register_chat,
        refresh_topics=refresh_topics,
        refresh_topics_v2=refresh_topics_v2,
        select_destination=select_destination,
        reset_bridge=reset_bridge,
        toggle_settings=toggle_settings,
        diagnostics_reader=diagnostics_reader,
        command_menu=command_menu,
        forward_message=forward_message,
        forward_wall=forward_wall,
        owner_notifier=owner_notifier,
        vk_ui_dispatcher=vk_ui_dispatcher,
        http_session=http_session,
        telegram_polling=_build_telegram_polling(bot, dispatcher),
        vk_polling=vk_polling,
        vk_polling_stop=vk_polling_stop,
    )
