"""Chat registration — temporary pre-Stage-7 provisioning use case.

Capability gate first: if the bot lacks any publication capability, nothing is persisted
and the full missing list is reported (US-03, D21). ``can_manage_topics`` is never required
because no slice operation manages topics.

Partial-success decision (D18): once the chat is persisted, a failing topic refresh does
NOT roll the chat back — the bot stays alive for diagnostics/retry and the caller receives
``ready=False``. Startup revalidation for an already persisted chat is fatal instead.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from vk_topic_bridge.application.admin.refresh_topics import RefreshTopics
from vk_topic_bridge.application.errors import ProvisioningError
from vk_topic_bridge.application.ports.telegram import TelegramAdminPort
from vk_topic_bridge.application.ports.unit_of_work import UnitOfWork
from vk_topic_bridge.domain.value_objects import ChatCapabilities, TopicInfo

logger = logging.getLogger(__name__)


class MissingCapabilitiesError(ProvisioningError):
    """Bot lacks one or more publication capabilities in the chat being registered."""

    missing: tuple[str, ...]

    def __init__(self, missing: tuple[str, ...]) -> None:
        self.missing = missing
        super().__init__(f"missing required bot capabilities: {', '.join(missing)}")


@dataclass(frozen=True, slots=True)
class RegisterChatResult:
    """Outcome of ``/register``: persisted chat identity plus provisioning readiness."""

    chat_id: int
    title: str | None
    capabilities: ChatCapabilities
    topics: list[TopicInfo]
    ready: bool


class RegisterChat:
    """Validates capabilities, persists the chat, then triggers the topic refresh."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        admin: TelegramAdminPort,
        refresh: RefreshTopics,
    ) -> None:
        self._uow_factory = uow_factory
        self._admin = admin
        self._refresh = refresh

    async def execute(self, chat_id: int, title: str | None) -> RegisterChatResult:
        capabilities = await self._admin.get_chat_capabilities(chat_id)
        if capabilities.missing:
            raise MissingCapabilitiesError(capabilities.missing)

        async with self._uow_factory() as uow:
            await uow.bridge_settings.upsert_chat(chat_id, title)
            await uow.commit()

        try:
            topics = await self._refresh.refresh(chat_id)
        except ProvisioningError as error:
            logger.warning(
                "chat registered but topic refresh failed; provisioning not ready: %s",
                error,
                extra={"chat_id": chat_id},
            )
            return RegisterChatResult(
                chat_id=chat_id,
                title=title,
                capabilities=capabilities,
                topics=[],
                ready=False,
            )

        return RegisterChatResult(
            chat_id=chat_id,
            title=title,
            capabilities=capabilities,
            topics=topics,
            ready=True,
        )
