"""SQLAlchemy repository implementations and the UnitOfWork adapter (plan §4/§6).

Repositories never commit or roll back: transaction boundaries belong to
:class:`SqlAlchemyUnitOfWork` and the calling use case.
"""

from vk_topic_bridge.infrastructure.db.repositories.bridge_settings import (
    BridgeSettingsRepositoryImpl,
)
from vk_topic_bridge.infrastructure.db.repositories.delivery import DeliveryRepositoryImpl
from vk_topic_bridge.infrastructure.db.repositories.telegram_topics import (
    TelegramTopicsRepositoryImpl,
)
from vk_topic_bridge.infrastructure.db.repositories.unit_of_work import SqlAlchemyUnitOfWork
from vk_topic_bridge.infrastructure.db.repositories.vk_aliases import VkAliasRepositoryImpl

__all__ = [
    "BridgeSettingsRepositoryImpl",
    "DeliveryRepositoryImpl",
    "SqlAlchemyUnitOfWork",
    "TelegramTopicsRepositoryImpl",
    "VkAliasRepositoryImpl",
]
