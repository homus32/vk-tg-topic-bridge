"""Unit-of-work port: one controlled transaction boundary per mutating use case.

Network I/O is forbidden inside the context; adapters leave and re-enter only after the
transaction commits (send intent is committed before the Bot API call).
"""

from types import TracebackType
from typing import Protocol, Self

from vk_topic_bridge.application.ports.repositories import (
    BridgeSettingsRepository,
    DeliveryRepository,
    TelegramTopicsRepository,
    VkAliasRepository,
)


class UnitOfWork(Protocol):
    """Async transaction scope exposing the four repositories."""

    @property
    def bridge_settings(self) -> BridgeSettingsRepository: ...
    @property
    def telegram_topics(self) -> TelegramTopicsRepository: ...
    @property
    def vk_aliases(self) -> VkAliasRepository: ...
    @property
    def deliveries(self) -> DeliveryRepository: ...

    async def __aenter__(self) -> Self: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
