"""Lifecycle integration tests: entrypoint wiring, fatal startup, poller coordination.

Everything here runs on fakes and in-memory state: no network, no live dispatcher and no
persistent database beyond the temporary directories pytest provides per test. Importing
``main`` is asserted to be free of side effects (no Bot, engine or Telethon client).
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import subprocess
import sys
import textwrap
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from aiogram import Bot
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine

from config import Settings
from vk_topic_bridge.application.admin.refresh_topics import RefreshTopics
from vk_topic_bridge.application.dto.infrastructure import ChatAccessInfo
from vk_topic_bridge.application.dto.readiness import ReadinessState
from vk_topic_bridge.application.errors import ProvisioningError
from vk_topic_bridge.application.ports.telegram import TelegramAdminPort, TelethonPort
from vk_topic_bridge.application.readiness import InMemoryReadinessGate
from vk_topic_bridge.domain.errors import FatalStartupError, FatalStartupReason
from vk_topic_bridge.domain.value_objects import ChatCapabilities, TopicInfo
from vk_topic_bridge.infrastructure.telegram.mtproto import TelethonAdapter, TelethonUserClient
from vk_topic_bridge.infrastructure.vk.api import RawVkApi

if TYPE_CHECKING:
    from main import RuntimeHooks
    from vk_topic_bridge.bootstrap.container import AppContainer

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "migrations"

_IMPORT_GUARD_SCRIPT = textwrap.dedent(
    """
    import aiogram
    import sqlalchemy.ext.asyncio as sa
    import telethon


    def _forbid(name):
        def _fail(*args, **kwargs):
            raise AssertionError(name + " created at import time")

        return _fail


    aiogram.Bot.__init__ = _forbid("Bot")
    telethon.TelegramClient.__init__ = _forbid("TelegramClient")
    sa.create_async_engine = _forbid("AsyncEngine")

    import main

    assert callable(main.run)
    print("IMPORT_OK")
    """
)


def _module(name: str) -> ModuleType:
    """Import a lifecycle module lazily so RED failures surface as test failures."""
    return importlib.import_module(name)


def _settings(tmp_path: Path) -> Settings:
    return Settings.model_validate(
        {
            "TELEGRAM_BOT_TOKEN": "123456:TEST-BOT-TOKEN",
            "OWNER_IDS": "111,222",
            "TELEGRAM_API_ID": 123456,
            "TELEGRAM_API_HASH": "0123456789abcdef0123456789abcdef",
            "TELEGRAM_SESSION_PATH": "test-session",
            "VK_GROUP_TOKEN": "vk1.a.test-token",
            "DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path / 'lifecycle.db'}",
            "LOG_DIR": str(tmp_path / "logs"),
        }
    )


class FakeTelethonClient:
    """Telethon-shape fake: authorization, identity, disconnect and call recording."""

    def __init__(self, *, authorized: bool = True) -> None:
        self.authorized = authorized
        self.calls: list[str] = []
        self.disconnect_calls = 0

    async def connect(self) -> None:
        self.calls.append("connect")

    async def is_user_authorized(self) -> bool:
        self.calls.append("is_user_authorized")
        return self.authorized

    async def get_me(self) -> object:
        self.calls.append("get_me")
        return SimpleNamespace(id=1)

    async def get_entity(self, entity: int) -> object:
        return SimpleNamespace(id=entity, forum=True)

    async def get_input_entity(self, peer: object) -> object:
        return peer

    async def __call__(self, request: object) -> object:
        return SimpleNamespace(topics=[], messages=[])

    async def disconnect(self) -> None:
        self.disconnect_calls += 1


class FakeVkApi:
    """RawVkApi-shape fake answering identity and Long Poll handshake methods."""

    def __init__(self, *, long_poll_enabled: bool = True) -> None:
        self.long_poll_enabled = long_poll_enabled
        self.calls: list[str] = []

    async def request(
        self, method: str, data: dict[str, object], version: str | None = None
    ) -> dict[str, object]:
        self.calls.append(method)
        if method == "groups.getById":
            return {"response": {"groups": [{"id": 42}]}}
        if method == "groups.getLongPollSettings":
            return {"response": {"is_enabled": self.long_poll_enabled}}
        if method == "groups.getLongPollServer":
            return {"response": {"server": "lp.example", "key": "key", "ts": "1"}}
        raise AssertionError(f"unexpected VK method: {method}")


class FakeAdminPort:
    """Bot API admin port with a working identity check."""

    async def get_me(self) -> int:
        return 999

    async def get_chat_capabilities(self, chat_id: int) -> object:
        raise AssertionError("capabilities are not part of startup")

    async def send_test_into_topic(
        self, chat_id: int, message_thread_id: int | None, text: str
    ) -> int:
        raise AssertionError("test sends are not part of startup")


class FakeTelethonAdapter:
    """TelethonAdapter-shape fake: revalidation answers for a persisted chat."""

    def __init__(
        self, *, topic_id: int | None = 7, is_closed: bool = False, is_hidden: bool = False
    ) -> None:
        self.topic_id = topic_id
        self.is_closed = is_closed
        self.is_hidden = is_hidden

    async def is_authorized(self) -> bool:
        return True

    async def get_me(self) -> object:
        return SimpleNamespace(id=1)

    async def verify_chat_access(self, chat_id: int) -> ChatAccessInfo:
        return ChatAccessInfo(entity_id=chat_id, is_forum=True)

    async def list_topics(self, chat_id: int) -> list[TopicInfo]:
        return [
            TopicInfo(
                topic_id=self.topic_id,
                title="Новости",
                is_general=self.topic_id is None,
                is_closed=self.is_closed,
                is_hidden=self.is_hidden,
            )
        ]


class FailingAdminPort:
    """Bot API admin port whose identity check always fails."""

    async def get_me(self) -> int:
        raise RuntimeError("bot api getMe failed")

    async def get_chat_capabilities(self, chat_id: int) -> object:
        raise RuntimeError("bot api unreachable")

    async def send_test_into_topic(
        self, chat_id: int, message_thread_id: int | None, text: str
    ) -> int:
        raise RuntimeError("bot api unreachable")


class FakeProvisioningAdminPort:
    """Admin port with full capabilities and a positive test-send message id."""

    async def get_me(self) -> int:
        return 999

    async def get_chat_capabilities(self, chat_id: int) -> ChatCapabilities:
        return ChatCapabilities(
            can_send_text=True,
            can_send_photo=True,
            can_send_video=True,
            can_send_document=True,
            missing=(),
        )

    async def send_test_into_topic(
        self, chat_id: int, message_thread_id: int | None, text: str
    ) -> int:
        return 555


class FailingRefreshTopics(RefreshTopics):
    """RefreshTopics whose topic discovery always fails, leaving registration unready."""

    async def refresh(self, chat_id: int) -> list[TopicInfo]:
        raise ProvisioningError(f"chat {chat_id} returned no forum topics")


def _container(
    settings: Settings,
    *,
    telethon_client: TelethonUserClient | None = None,
    vk_api_raw: RawVkApi | None = None,
) -> AppContainer:
    container_module = _module("vk_topic_bridge.bootstrap.container")
    built = container_module.build_container(
        settings,
        telethon_client=telethon_client or cast(TelethonUserClient, FakeTelethonClient()),
        vk_api_raw=vk_api_raw or cast(RawVkApi, FakeVkApi()),
    )
    return cast("AppContainer", built)


def _factory_returning(container: AppContainer) -> Callable[..., AppContainer]:
    def factory(settings: Settings, *, telethon_client: object, vk_api_raw: object) -> AppContainer:
        return container

    return factory


def _hooks(
    *,
    container: AppContainer,
    startup_checks: Callable[[object], Awaitable[None]] | None = None,
    shutdown_fn: Callable[[AppContainer], Awaitable[None]] | None = None,
    telegram_poller: Callable[[AppContainer], Awaitable[None]] | None = None,
    vk_poller: Callable[[AppContainer], Awaitable[None]] | None = None,
    install_signal_handlers: Callable[[asyncio.AbstractEventLoop, asyncio.Event], None]
    | None = None,
) -> RuntimeHooks:
    main = _module("main")

    async def default_startup(deps: object) -> None:
        return None

    async def default_shutdown(target: AppContainer) -> None:
        return None

    async def default_poller(target: AppContainer) -> None:
        await asyncio.Event().wait()

    def default_installer(loop: asyncio.AbstractEventLoop, event: asyncio.Event) -> None:
        return None

    hooks: RuntimeHooks = main.RuntimeHooks(
        configure=lambda settings: None,
        container_factory=_factory_returning(container),
        startup_checks=startup_checks or default_startup,
        shutdown_fn=shutdown_fn or default_shutdown,
        telegram_poller=telegram_poller or default_poller,
        vk_poller=vk_poller or default_poller,
        install_signal_handlers=install_signal_handlers or default_installer,
    )
    return hooks


def test_importing_main_builds_no_resources() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _IMPORT_GUARD_SCRIPT],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert "IMPORT_OK" in result.stdout

    main = _module("main")
    assert callable(main.run)
    assert callable(main.main)


async def test_invalid_settings_return_nonzero_and_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    main = _module("main")

    def reject_settings() -> Settings:
        return Settings.model_validate({"OWNER_IDS": ""})

    monkeypatch.setattr(main, "get_settings", reject_settings)

    with caplog.at_level(logging.ERROR):
        code = await main.run()

    assert code != 0
    assert any("settings" in record.getMessage().lower() for record in caplog.records)


async def test_startup_failure_shuts_down_without_starting_pollers(tmp_path: Path) -> None:
    main = _module("main")
    settings = _settings(tmp_path)
    container = _container(settings)
    calls: list[str] = []

    async def failing_startup(deps: object) -> None:
        calls.append("startup")
        raise FatalStartupError(FatalStartupReason.BOT_API_UNREACHABLE, "fake getMe failure")

    async def recording_shutdown(target: object) -> None:
        calls.append("shutdown")

    async def forbidden_poller(target: object) -> None:
        calls.append("poller")
        await asyncio.Event().wait()

    hooks = _hooks(
        container=container,
        startup_checks=failing_startup,
        shutdown_fn=recording_shutdown,
        telegram_poller=forbidden_poller,
        vk_poller=forbidden_poller,
    )

    code = await main.run(settings, hooks=hooks)

    assert code != 0
    assert calls == ["startup", "shutdown"]


async def test_bot_api_failure_is_fatal_before_telethon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    startup = _module("vk_topic_bridge.bootstrap.startup")
    settings = _settings(tmp_path)
    container = _container(settings)
    await asyncio.to_thread(_upgrade_to_head, monkeypatch, settings)
    failing = replace(container, admin_port=cast(TelegramAdminPort, FailingAdminPort()))
    telethon = cast(FakeTelethonClient, container.telethon_client)

    with pytest.raises(FatalStartupError) as excinfo:
        await startup.run_startup_checks(startup.StartupDeps(settings=settings, container=failing))

    assert excinfo.value.reason is FatalStartupReason.BOT_API_UNREACHABLE
    assert telethon.calls == []
    await container.engine.dispose()


async def test_clean_database_skips_chat_revalidation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    startup = _module("vk_topic_bridge.bootstrap.startup")
    settings = _settings(tmp_path)
    container = _container(settings)
    await asyncio.to_thread(_upgrade_to_head, monkeypatch, settings)
    healthy = replace(
        container,
        admin_port=cast(TelegramAdminPort, FakeAdminPort()),
        telethon_adapter=cast(TelethonAdapter, FakeTelethonAdapter()),
    )

    await startup.run_startup_checks(startup.StartupDeps(settings=settings, container=healthy))

    assert healthy.readiness.current() is ReadinessState.CORE_READY
    await container.engine.dispose()


async def test_persisted_chat_revalidation_advances_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    startup = _module("vk_topic_bridge.bootstrap.startup")
    settings = _settings(tmp_path)
    container = _container(settings)
    await asyncio.to_thread(_upgrade_to_head, monkeypatch, settings)
    async with container.uow_factory() as uow:
        await uow.bridge_settings.upsert_chat(-1001234567890, "Тестовый чат")
        await uow.commit()
    healthy = replace(
        container,
        admin_port=cast(TelegramAdminPort, FakeAdminPort()),
        telethon_adapter=cast(TelethonAdapter, FakeTelethonAdapter()),
    )

    await startup.run_startup_checks(startup.StartupDeps(settings=settings, container=healthy))

    assert healthy.readiness.current() is ReadinessState.TOPICS_READY
    await container.engine.dispose()


async def test_persisted_destination_advances_to_forwarding_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    startup = _module("vk_topic_bridge.bootstrap.startup")
    settings = _settings(tmp_path)
    container = _container(settings)
    await asyncio.to_thread(_upgrade_to_head, monkeypatch, settings)
    async with container.uow_factory() as uow:
        await uow.bridge_settings.upsert_chat(-1001234567890, "Тестовый чат")
        await uow.bridge_settings.set_messages_topic(7)
        await uow.commit()
    healthy = replace(
        container,
        admin_port=cast(TelegramAdminPort, FakeAdminPort()),
        telethon_adapter=cast(TelethonAdapter, FakeTelethonAdapter()),
    )

    await startup.run_startup_checks(startup.StartupDeps(settings=settings, container=healthy))

    assert healthy.readiness.current() is ReadinessState.FORWARDING_ENABLED
    await container.engine.dispose()


async def test_persisted_destination_missing_from_topics_is_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    startup = _module("vk_topic_bridge.bootstrap.startup")
    settings = _settings(tmp_path)
    container = _container(settings)
    await asyncio.to_thread(_upgrade_to_head, monkeypatch, settings)
    async with container.uow_factory() as uow:
        await uow.bridge_settings.upsert_chat(-1001234567890, "Тестовый чат")
        await uow.bridge_settings.set_messages_topic(99)
        await uow.commit()
    missing = replace(
        container,
        admin_port=cast(TelegramAdminPort, FakeAdminPort()),
        telethon_adapter=cast(TelethonAdapter, FakeTelethonAdapter(topic_id=7)),
    )

    with pytest.raises(FatalStartupError) as excinfo:
        await startup.run_startup_checks(startup.StartupDeps(settings=settings, container=missing))

    assert excinfo.value.reason is FatalStartupReason.TOPICS_UNAVAILABLE
    assert "99" in str(excinfo.value)
    assert missing.readiness.current() is not ReadinessState.FORWARDING_ENABLED
    await container.engine.dispose()


async def test_persisted_destination_closed_topic_is_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    startup = _module("vk_topic_bridge.bootstrap.startup")
    settings = _settings(tmp_path)
    container = _container(settings)
    await asyncio.to_thread(_upgrade_to_head, monkeypatch, settings)
    async with container.uow_factory() as uow:
        await uow.bridge_settings.upsert_chat(-1001234567890, "Тестовый чат")
        await uow.bridge_settings.set_messages_topic(7)
        await uow.commit()
    closed = replace(
        container,
        admin_port=cast(TelegramAdminPort, FakeAdminPort()),
        telethon_adapter=cast(TelethonAdapter, FakeTelethonAdapter(topic_id=7, is_closed=True)),
    )

    with pytest.raises(FatalStartupError) as excinfo:
        await startup.run_startup_checks(startup.StartupDeps(settings=settings, container=closed))

    assert excinfo.value.reason is FatalStartupReason.TOPICS_UNAVAILABLE
    assert "7" in str(excinfo.value)
    assert closed.readiness.current() is not ReadinessState.FORWARDING_ENABLED
    await container.engine.dispose()


def test_redact_secrets_replaces_secret_values() -> None:
    logging_module = _module("logger")
    secret = "vk1.a.SECRETVALUE123"

    redacted = logging_module.redact_secrets(f"boom {secret} x", [secret])

    assert "<redacted>" in redacted
    assert secret not in redacted

    short = "abc"
    assert logging_module.redact_secrets(f"boom {short} x", [short]) == f"boom {short} x"
    assert logging_module.redact_secrets("clean", []) == "clean"


async def test_readiness_aware_register_chat_advances_topics_ready_when_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container_module = _module("vk_topic_bridge.bootstrap.container")
    settings = _settings(tmp_path)
    container = _container(settings)
    await asyncio.to_thread(_upgrade_to_head, monkeypatch, settings)
    readiness = InMemoryReadinessGate()
    refresh = RefreshTopics(container.uow_factory, cast(TelethonPort, FakeTelethonAdapter()))
    use_case = container_module.ReadinessAwareRegisterChat(
        container.uow_factory,
        cast(TelegramAdminPort, FakeProvisioningAdminPort()),
        refresh,
        readiness,
    )

    result = await use_case.execute(-1001234567890, "Тестовый чат")

    assert result.ready is True
    assert readiness.current() is ReadinessState.TOPICS_READY
    await container.engine.dispose()


async def test_readiness_aware_register_chat_stays_when_not_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container_module = _module("vk_topic_bridge.bootstrap.container")
    settings = _settings(tmp_path)
    container = _container(settings)
    await asyncio.to_thread(_upgrade_to_head, monkeypatch, settings)
    readiness = InMemoryReadinessGate()
    readiness.advance(ReadinessState.CHAT_REGISTERED)
    refresh = FailingRefreshTopics(container.uow_factory, cast(TelethonPort, FakeTelethonAdapter()))
    use_case = container_module.ReadinessAwareRegisterChat(
        container.uow_factory,
        cast(TelegramAdminPort, FakeProvisioningAdminPort()),
        refresh,
        readiness,
    )

    result = await use_case.execute(-1001234567890, "Тестовый чат")

    assert result.ready is False
    assert readiness.current() is ReadinessState.CHAT_REGISTERED
    await container.engine.dispose()


async def test_readiness_aware_select_destination_advances_to_forwarding_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container_module = _module("vk_topic_bridge.bootstrap.container")
    settings = _settings(tmp_path)
    container = _container(settings)
    await asyncio.to_thread(_upgrade_to_head, monkeypatch, settings)
    readiness = InMemoryReadinessGate()
    use_case = container_module.ReadinessAwareSelectDestination(
        container.uow_factory,
        cast(TelegramAdminPort, FakeProvisioningAdminPort()),
        readiness,
    )
    topic = TopicInfo(
        topic_id=7, title="Новости", is_general=False, is_closed=False, is_hidden=False
    )

    message_id = await use_case.execute(-1001234567890, topic, "run-1")

    assert message_id == 555
    assert readiness.current() is ReadinessState.FORWARDING_ENABLED
    await container.engine.dispose()


async def test_unexpected_poller_exit_cancels_sibling(tmp_path: Path) -> None:
    main = _module("main")
    settings = _settings(tmp_path)
    container = _container(settings)
    vk_started = asyncio.Event()
    cancelled: list[str] = []

    async def telegram_poller(target: object) -> None:
        await vk_started.wait()

    async def vk_poller(target: object) -> None:
        vk_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append("vk")
            raise

    hooks = _hooks(
        container=container,
        telegram_poller=telegram_poller,
        vk_poller=vk_poller,
    )

    code = await main.run(settings, hooks=hooks)

    assert code != 0
    assert cancelled == ["vk"]


async def test_graceful_signal_returns_zero_and_shuts_down(tmp_path: Path) -> None:
    main = _module("main")
    settings = _settings(tmp_path)
    container = _container(settings)
    order: list[str] = []
    started = 0

    async def poller(target: object) -> None:
        nonlocal started
        started += 1
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            order.append("cancelled")
            raise

    def installer(loop: asyncio.AbstractEventLoop, event: asyncio.Event) -> None:
        async def trigger_when_ready() -> None:
            while started < 2:
                await asyncio.sleep(0)
            event.set()

        loop.create_task(trigger_when_ready())

    async def recording_shutdown(target: object) -> None:
        order.append("shutdown")

    hooks = _hooks(
        container=container,
        shutdown_fn=recording_shutdown,
        telegram_poller=poller,
        vk_poller=poller,
        install_signal_handlers=installer,
    )

    code = await main.run(settings, hooks=hooks)

    assert code == 0
    assert order.count("cancelled") == 2
    assert order[-1] == "shutdown"


async def test_shutdown_closes_resources_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutdown_module = _module("vk_topic_bridge.bootstrap.shutdown")
    settings = _settings(tmp_path)
    order: list[str] = []

    class FakeSession:
        async def close(self) -> None:
            order.append("bot")

    class FakeEngine:
        async def dispose(self) -> None:
            order.append("engine")

    class FakeTelethon:
        async def disconnect(self) -> None:
            order.append("telethon")

    async def fake_polling_stop() -> None:
        order.append("vk_polling_stop")

    async def fake_polling_task_stop() -> None:
        order.append("polling_stop")

    monkeypatch.setattr(shutdown_module, "flush_logging", lambda: order.append("logging"))
    container = replace(
        _container(settings),
        bot=cast(Bot, SimpleNamespace(session=FakeSession())),
        engine=cast(AsyncEngine, FakeEngine()),
        telethon_client=cast(TelethonUserClient, FakeTelethon()),
        vk_polling_stop=fake_polling_stop,
        polling_stop=fake_polling_task_stop,
    )

    await shutdown_module.shutdown(container)

    assert order == ["vk_polling_stop", "polling_stop", "bot", "telethon", "engine", "logging"]


async def test_shutdown_continues_after_step_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutdown_module = _module("vk_topic_bridge.bootstrap.shutdown")
    settings = _settings(tmp_path)
    order: list[str] = []

    class FakeSession:
        async def close(self) -> None:
            order.append("bot")

    class FailingEngine:
        async def dispose(self) -> None:
            order.append("engine")
            raise RuntimeError("engine dispose failed")

    class FakeTelethon:
        async def disconnect(self) -> None:
            order.append("telethon")

    monkeypatch.setattr(shutdown_module, "flush_logging", lambda: order.append("logging"))
    container = replace(
        _container(settings),
        bot=cast(Bot, SimpleNamespace(session=FakeSession())),
        engine=cast(AsyncEngine, FailingEngine()),
        telethon_client=cast(TelethonUserClient, FakeTelethon()),
    )

    await shutdown_module.shutdown(container)

    assert order == ["bot", "telethon", "engine", "logging"]


async def test_startup_rejects_database_without_migrations(tmp_path: Path) -> None:
    startup = _module("vk_topic_bridge.bootstrap.startup")
    settings = _settings(tmp_path)
    container = _container(settings)

    with pytest.raises(FatalStartupError) as excinfo:
        await startup.run_startup_checks(
            startup.StartupDeps(settings=settings, container=container)
        )

    assert excinfo.value.reason is FatalStartupReason.MIGRATION_FAILED
    await container.engine.dispose()


def _upgrade_to_head(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setenv("DATABASE_URL", settings.DATABASE_URL)
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    command.upgrade(config, "head")
