"""Auto-forwarding toggle persistence and factory reset — temporary provisioning use case."""

import logging
from collections.abc import Callable

from vk_topic_bridge.application.dto.settings import BridgeSettingsState, ToggleKind
from vk_topic_bridge.application.ports.unit_of_work import UnitOfWork

logger = logging.getLogger(__name__)


class ToggleSettings:
    """Writes one toggle (or the factory defaults) in a single short transaction."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def execute(self, kind: ToggleKind, value: bool) -> BridgeSettingsState:
        async with self._uow_factory() as uow:
            state = await uow.bridge_settings.set_toggle(kind, value)
            await uow.commit()
        logger.info(
            "telegram forwarding toggle changed",
            extra={"operation": kind.value, "status": "enabled" if value else "disabled"},
        )
        return state

    async def reset(self) -> BridgeSettingsState:
        async with self._uow_factory() as uow:
            state = await uow.bridge_settings.reset()
            await uow.commit()
        logger.info("telegram forwarding settings reset")
        return state
