"""Manual composition root: one frozen container, no DI framework, no I/O at build time.

``build_container`` only constructs objects and registers routers. It never connects a
client and never sends a request; every network interaction happens in the startup
sequence (``bootstrap.startup``) after the container exists.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from aiogram import Bot, Dispatcher
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from config import Settings
from vk_topic_bridge.application.admin.refresh_topics import RefreshTopics
from vk_topic_bridge.application.admin.register_chat import RegisterChat, RegisterChatResult
from vk_topic_bridge.application.admin.select_destination import SelectDestination
from vk_topic_bridge.application.admin.toggle_settings import ToggleSettings
from vk_topic_bridge.application.dto.readiness import ReadinessState
from vk_topic_bridge.application.dto.settings import BridgeSettingsState
from vk_topic_bridge.application.forwarding.forward_message import ForwardVkMessage
from vk_topic_bridge.application.ports.telegram import TelegramAdminPort
from vk_topic_bridge.application.ports.unit_of_work import UnitOfWork
from vk_topic_bridge.application.readiness import InMemoryReadinessGate
from vk_topic_bridge.bootstrap.vk_consumer import VkPollingRuntime
from vk_topic_bridge.domain.value_objects import TopicInfo
from vk_topic_bridge.infrastructure.db.engine import create_async_engine, create_session_factory
from vk_topic_bridge.infrastructure.db.repositories.unit_of_work import SqlAlchemyUnitOfWork
from vk_topic_bridge.infrastructure.telegram.bot_api_factory import create_bot
from vk_topic_bridge.infrastructure.telegram.mtproto import TelethonAdapter, TelethonUserClient
from vk_topic_bridge.infrastructure.telegram.publisher import BotApiAdminPort, BotApiPublisher
from vk_topic_bridge.infrastructure.vk.api import RawVkApi, VkApiGateway
from vk_topic_bridge.presentation.telegram.middlewares import OwnerOnlyMiddleware
from vk_topic_bridge.presentation.telegram.routers.destination import (
    TopicsReader,
    build_destination_router,
)
from vk_topic_bridge.presentation.telegram.routers.register import build_register_router
from vk_topic_bridge.presentation.telegram.routers.start import build_start_router

type SettingsReader = Callable[[], Awaitable[BridgeSettingsState | None]]
type PollingStop = Callable[[], Awaitable[None]]
type PollingTask = Callable[[], Awaitable[None]]


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
    select_destination: SelectDestination
    toggle_settings: ToggleSettings
    forward_message: ForwardVkMessage
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


def _build_telegram_polling(bot: Bot, dispatcher: Dispatcher) -> PollingTask:
    async def start() -> None:
        await dispatcher.start_polling(bot, handle_signals=False)

    return start


def _build_vk_polling(
    api: RawVkApi, gateway: VkApiGateway, forward: ForwardVkMessage
) -> tuple[PollingTask, PollingStop]:
    """Build the VK Long Poll coroutine and its stop callable; performs no I/O.

    The community id is resolved inside the coroutine, so container construction stays
    network-free and the poller can be started by the lifecycle runner.
    """
    runtime = VkPollingRuntime(api, gateway, forward)
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


class ReadinessAwareSelectDestination(SelectDestination):
    """SelectDestination that promotes readiness after the confirmed test send."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        admin: TelegramAdminPort,
        readiness: InMemoryReadinessGate,
    ) -> None:
        super().__init__(uow_factory, admin)
        self._readiness = readiness

    async def execute(self, chat_id: int, topic: TopicInfo, run_id: str) -> int:
        message_id = await super().execute(chat_id, topic, run_id)
        self._readiness.advance(ReadinessState.DESTINATION_CONFIRMED)
        self._readiness.advance(ReadinessState.FORWARDING_ENABLED)
        return message_id


def _register_routers(
    dispatcher: Dispatcher,
    settings: Settings,
    register_chat: RegisterChat,
    select_destination: SelectDestination,
    reader: SettingsReader,
    topics_reader: TopicsReader,
) -> None:
    dispatcher.message.outer_middleware(OwnerOnlyMiddleware(frozenset(settings.OWNER_IDS)))
    dispatcher.include_router(build_start_router(reader))
    dispatcher.include_router(build_register_router(register_chat))
    dispatcher.include_router(build_destination_router(select_destination, topics_reader))


def build_container(
    settings: Settings,
    *,
    telethon_client: TelethonUserClient,
    vk_api_raw: RawVkApi,
) -> AppContainer:
    """Construct the whole object graph; never connects, never sends."""
    engine = create_async_engine(settings.DATABASE_URL)
    session_factory = create_session_factory(engine)
    uow_factory = _build_uow_factory(session_factory)

    bot = create_bot(settings)
    dispatcher = Dispatcher()
    telethon_adapter = TelethonAdapter(telethon_client)
    vk_gateway = VkApiGateway(vk_api_raw, settings)
    publisher = BotApiPublisher(bot)
    admin_port = BotApiAdminPort(bot)
    readiness = InMemoryReadinessGate()

    refresh_topics = RefreshTopics(uow_factory, telethon_adapter)
    register_chat = ReadinessAwareRegisterChat(uow_factory, admin_port, refresh_topics, readiness)
    select_destination = ReadinessAwareSelectDestination(uow_factory, admin_port, readiness)
    toggle_settings = ToggleSettings(uow_factory)
    forward_message = ForwardVkMessage(
        uow_factory=uow_factory,
        publisher=publisher,
        vk=vk_gateway,
        readiness=readiness,
    )

    _register_routers(
        dispatcher,
        settings,
        register_chat,
        select_destination,
        _build_settings_reader(uow_factory),
        _build_topics_reader(uow_factory),
    )

    vk_polling, vk_polling_stop = _build_vk_polling(vk_api_raw, vk_gateway, forward_message)

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
        select_destination=select_destination,
        toggle_settings=toggle_settings,
        forward_message=forward_message,
        telegram_polling=_build_telegram_polling(bot, dispatcher),
        vk_polling=vk_polling,
        vk_polling_stop=vk_polling_stop,
    )
