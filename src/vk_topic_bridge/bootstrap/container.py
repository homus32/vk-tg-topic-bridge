"""Manual composition root: one frozen container, no DI framework, no I/O at build time.

``build_container`` only constructs objects and registers routers. It never connects a
client and never sends a request; every network interaction happens in the startup
sequence (``bootstrap.startup``) after the container exists.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from aiogram import Bot, Dispatcher
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from config import Settings
from vk_topic_bridge.application.admin.refresh_topics import RefreshTopics
from vk_topic_bridge.application.admin.register_chat import RegisterChat
from vk_topic_bridge.application.admin.select_destination import SelectDestination
from vk_topic_bridge.application.admin.toggle_settings import ToggleSettings
from vk_topic_bridge.application.dto.settings import BridgeSettingsState
from vk_topic_bridge.application.forwarding.forward_message import ForwardVkMessage
from vk_topic_bridge.application.ports.unit_of_work import UnitOfWork
from vk_topic_bridge.application.readiness import InMemoryReadinessGate
from vk_topic_bridge.infrastructure.db.engine import create_async_engine, create_session_factory
from vk_topic_bridge.infrastructure.db.repositories.unit_of_work import SqlAlchemyUnitOfWork
from vk_topic_bridge.infrastructure.telegram.bot_api_factory import create_bot
from vk_topic_bridge.infrastructure.telegram.mtproto import TelethonAdapter, TelethonUserClient
from vk_topic_bridge.infrastructure.telegram.publisher import BotApiAdminPort, BotApiPublisher
from vk_topic_bridge.infrastructure.vk.api import RawVkApi, VkApiGateway
from vk_topic_bridge.presentation.telegram.middlewares import OwnerOnlyMiddleware
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


def _build_telegram_polling(bot: Bot, dispatcher: Dispatcher) -> PollingTask:
    async def start() -> None:
        await dispatcher.start_polling(bot, handle_signals=False)

    return start


def _build_vk_polling(_api: RawVkApi) -> PollingTask:
    """Cancellable placeholder for the VK Long Poll consumer loop.

    The real loop lands in a later stage; this task exists so startup coordination,
    cancellation and shutdown are already exercised end to end.
    """
    stop_event = asyncio.Event()

    async def run() -> None:
        await stop_event.wait()

    return run


def _register_routers(
    dispatcher: Dispatcher,
    settings: Settings,
    register_chat: RegisterChat,
    reader: SettingsReader,
) -> None:
    dispatcher.message.outer_middleware(OwnerOnlyMiddleware(frozenset(settings.OWNER_IDS)))
    dispatcher.include_router(build_start_router(reader))
    dispatcher.include_router(build_register_router(register_chat))


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
    register_chat = RegisterChat(uow_factory, admin_port, refresh_topics)
    select_destination = SelectDestination(uow_factory, admin_port)
    toggle_settings = ToggleSettings(uow_factory)
    forward_message = ForwardVkMessage(
        uow_factory=uow_factory,
        publisher=publisher,
        vk=vk_gateway,
        readiness=readiness,
    )

    _register_routers(dispatcher, settings, register_chat, _build_settings_reader(uow_factory))

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
        vk_polling=_build_vk_polling(vk_api_raw),
    )
