"""Process entrypoint: settings, startup checks, critical pollers, coordinated shutdown.

Nothing here builds a client at import time. ``run`` is the single orchestration point and
keeps its dependencies injectable so lifecycle behavior is testable without network.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import ValidationError
from telethon import TelegramClient
from vkbottle import API

from config import Settings, get_settings
from logger import configure_logging
from vk_topic_bridge.bootstrap.container import AppContainer, PollingTask, build_container
from vk_topic_bridge.bootstrap.shutdown import shutdown
from vk_topic_bridge.bootstrap.startup import StartupDeps, run_startup_checks
from vk_topic_bridge.domain.errors import FatalStartupError
from vk_topic_bridge.infrastructure.telegram.mtproto import TelethonUserClient
from vk_topic_bridge.infrastructure.telegram.proxy import client_connection_kwargs
from vk_topic_bridge.infrastructure.vk.api import RawVkApi

logger = logging.getLogger(__name__)

type ContainerFactory = Callable[..., AppContainer]
type StartupChecks = Callable[[StartupDeps], Awaitable[None]]
type ShutdownFn = Callable[[AppContainer], Awaitable[None]]
type Poller = Callable[[AppContainer], Awaitable[None]]
type SignalInstaller = Callable[[asyncio.AbstractEventLoop, asyncio.Event], None]
type TelethonClientFactory = Callable[[Settings], TelethonUserClient]
type VkApiFactory = Callable[[Settings], RawVkApi]

_TELEGRAM_CLIENT: Callable[..., TelegramClient] = TelegramClient


class CriticalTaskExited(Exception):
    """A critical poller returned while the process was supposed to keep running."""

    name: str

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"critical task exited unexpectedly: {name}")


def _default_telethon_client_factory(settings: Settings) -> TelethonUserClient:
    return _TELEGRAM_CLIENT(
        settings.TELEGRAM_SESSION_PATH,
        settings.TELEGRAM_API_ID,
        settings.TELEGRAM_API_HASH.get_secret_value(),
        receive_updates=False,
        **client_connection_kwargs(settings),
    )


def _default_vk_api_factory(settings: Settings) -> RawVkApi:
    return API(settings.VK_GROUP_TOKEN.get_secret_value())


def _install_signal_handlers(
    loop: asyncio.AbstractEventLoop, shutdown_event: asyncio.Event
) -> None:
    """Turn SIGINT/SIGTERM into a graceful-shutdown request where the loop supports it."""

    def request_shutdown() -> None:
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_shutdown)
        except NotImplementedError, RuntimeError, ValueError:
            continue


@dataclass(frozen=True, slots=True)
class RuntimeHooks:
    """Injectable lifecycle collaborators; production defaults wire the real bootstrap."""

    configure: Callable[[Settings], None] = configure_logging
    container_factory: ContainerFactory = build_container
    startup_checks: StartupChecks = run_startup_checks
    shutdown_fn: ShutdownFn = shutdown
    telegram_poller: Poller | None = None
    vk_poller: Poller | None = None
    install_signal_handlers: SignalInstaller = _install_signal_handlers
    telethon_client_factory: TelethonClientFactory | None = None
    vk_api_factory: VkApiFactory | None = None


async def _run_critical_pollers(
    container: AppContainer,
    hooks: RuntimeHooks,
    telegram_poller: Poller,
    vk_poller: Poller,
) -> bool:
    """Run both critical pollers; return whether shutdown was graceful.

    An unexpected return of either poller raises ``CriticalTaskExited``, which cancels the
    sibling through the ``TaskGroup``.
    """
    shutdown_event = asyncio.Event()
    hooks.install_signal_handlers(asyncio.get_running_loop(), shutdown_event)
    poller_tasks: list[asyncio.Task[None]] = []
    graceful = False

    async def critical(name: str, poller: Poller) -> None:
        await poller(container)
        raise CriticalTaskExited(name)

    async def watch_for_shutdown() -> None:
        nonlocal graceful
        await shutdown_event.wait()
        graceful = True
        for task in poller_tasks:
            task.cancel()

    try:
        async with asyncio.TaskGroup() as group:
            poller_tasks.append(group.create_task(critical("telegram", telegram_poller)))
            poller_tasks.append(group.create_task(critical("vk", vk_poller)))
            group.create_task(watch_for_shutdown())
    except* CriticalTaskExited as group_error:
        for error in group_error.exceptions:
            if isinstance(error, CriticalTaskExited):
                logger.error("critical task exited unexpectedly: %s", error.name)
        graceful = False
    except* Exception as group_error:
        for error in group_error.exceptions:
            logger.error("critical task failed: %s", error)
        graceful = False
    return graceful


def _container_poller(container: AppContainer, polling_task: PollingTask) -> Poller:
    """Adapt a container-bound polling task to the poller signature used by the runner."""

    async def poller(_container: AppContainer) -> None:
        await polling_task()

    return poller


async def run(
    settings: Settings | None = None,
    *,
    hooks: RuntimeHooks | None = None,
    telethon_client_factory: TelethonClientFactory | None = None,
    vk_api_factory: VkApiFactory | None = None,
) -> int:
    """Run the bridge until shutdown; return a process exit code."""
    runtime = hooks or RuntimeHooks()

    if settings is None:
        try:
            settings = get_settings()
        except ValidationError as error:
            logger.error("invalid settings, refusing to start: %s", error)
            return 1

    runtime.configure(settings)

    telethon_factory = (
        telethon_client_factory
        or runtime.telethon_client_factory
        or _default_telethon_client_factory
    )
    vk_factory = vk_api_factory or runtime.vk_api_factory or _default_vk_api_factory

    container: AppContainer | None = None
    try:
        container = runtime.container_factory(
            settings,
            telethon_client=telethon_factory(settings),
            vk_api_raw=vk_factory(settings),
        )
        await runtime.startup_checks(StartupDeps(settings=settings, container=container))
        telegram_poller = runtime.telegram_poller or _container_poller(
            container, container.telegram_polling
        )
        vk_poller = runtime.vk_poller or _container_poller(container, container.vk_polling)
        graceful = await _run_critical_pollers(container, runtime, telegram_poller, vk_poller)
        return 0 if graceful else 1
    except FatalStartupError as error:
        logger.error("fatal startup failure (%s): %s", error.reason.value, error)
        return 1
    finally:
        if container is not None:
            await runtime.shutdown_fn(container)


def main() -> int:
    """Synchronous entrypoint used by ``python main.py`` and the package ``__main__``."""
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
