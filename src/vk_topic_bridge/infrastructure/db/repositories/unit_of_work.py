"""UnitOfWork adapter: one ``AsyncSession`` (and thus one transaction) per use case."""

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vk_topic_bridge.infrastructure.db.repositories.bridge_settings import (
    BridgeSettingsRepositoryImpl,
)
from vk_topic_bridge.infrastructure.db.repositories.delivery import DeliveryRepositoryImpl
from vk_topic_bridge.infrastructure.db.repositories.telegram_topics import (
    TelegramTopicsRepositoryImpl,
)
from vk_topic_bridge.infrastructure.db.repositories.vk_aliases import VkAliasRepositoryImpl

SessionFactory = async_sessionmaker[AsyncSession]


class SqlAlchemyUnitOfWork:
    """Owns the session lifecycle; repositories are bound to it and never commit."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._bridge_settings: BridgeSettingsRepositoryImpl | None = None
        self._telegram_topics: TelegramTopicsRepositoryImpl | None = None
        self._vk_aliases: VkAliasRepositoryImpl | None = None
        self._deliveries: DeliveryRepositoryImpl | None = None

    @property
    def bridge_settings(self) -> BridgeSettingsRepositoryImpl:
        return self._require(self._bridge_settings)

    @property
    def telegram_topics(self) -> TelegramTopicsRepositoryImpl:
        return self._require(self._telegram_topics)

    @property
    def vk_aliases(self) -> VkAliasRepositoryImpl:
        return self._require(self._vk_aliases)

    @property
    def deliveries(self) -> DeliveryRepositoryImpl:
        return self._require(self._deliveries)

    async def __aenter__(self) -> Self:
        session = self._session_factory()
        self._session = session
        self._bridge_settings = BridgeSettingsRepositoryImpl(session)
        self._telegram_topics = TelegramTopicsRepositoryImpl(session)
        self._vk_aliases = VkAliasRepositoryImpl(session)
        self._deliveries = DeliveryRepositoryImpl(session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        session = self._session
        self._session = None
        self._bridge_settings = None
        self._telegram_topics = None
        self._vk_aliases = None
        self._deliveries = None
        if session is not None:
            try:
                if exc_type is not None:
                    await session.rollback()
            finally:
                await session.close()
        return None

    async def commit(self) -> None:
        session = self._require_session()
        await session.commit()

    async def rollback(self) -> None:
        session = self._require_session()
        await session.rollback()

    def _require_session(self) -> AsyncSession:
        session = self._session
        if session is None:
            raise RuntimeError("UnitOfWork is not active; use it as an async context manager")
        return session

    @staticmethod
    def _require[T](repository: T | None) -> T:
        if repository is None:
            raise RuntimeError("UnitOfWork is not active; use it as an async context manager")
        return repository
