# ruff: noqa: E501 (the frozen stage-7 marker below must stay on one exact line)
"""Temporary destination-topic selection (pre-Stage-7 provisioning).

TODO(stage-7): remove temporary destination-topic provisioning when Telegram Admin UI provides destination selection.

Persistence is proof-gated (D16): ``telegram_messages_topic_id`` is written only after a
real Bot API send into the topic thread returns a positive message id. A failed test send
propagates without persisting anything. ``telegram_wall_topic_id`` is never touched.
"""

from collections.abc import Callable

from vk_topic_bridge.application.errors import ProvisioningError
from vk_topic_bridge.application.ports.telegram import TelegramAdminPort
from vk_topic_bridge.application.ports.unit_of_work import UnitOfWork
from vk_topic_bridge.domain.value_objects import TopicInfo


class SelectDestination:
    """Confirms the messages destination by a real send, then persists the topic id."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork], admin: TelegramAdminPort) -> None:
        self._uow_factory = uow_factory
        self._admin = admin

    async def execute(self, chat_id: int, topic: TopicInfo, run_id: str) -> int:
        # TODO(stage-7): remove temporary destination-topic provisioning when Telegram Admin UI provides destination selection.
        if topic.topic_id is None:
            raise ProvisioningError(
                "General cannot be the messages destination: a NULL destination id is "
                "indistinguishable from 'not configured' after a restart, so forwarding "
                "would silently stay disabled. Choose a named topic."
            )
        confirmation_text = f"destination check for run {run_id} (topic {topic.topic_id!r})"
        message_id = await self._admin.send_test_into_topic(
            chat_id, topic.topic_id, confirmation_text
        )
        if message_id <= 0:
            raise ProvisioningError(
                f"test send into chat {chat_id} topic {topic.topic_id!r} returned no message id"
            )

        async with self._uow_factory() as uow:
            await uow.bridge_settings.set_messages_topic(topic.topic_id)
            await uow.commit()
        return message_id
