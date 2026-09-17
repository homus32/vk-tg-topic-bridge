"""Auto-forwarding toggle persistence and factory reset — temporary provisioning use case."""

from collections.abc import Callable

from vk_topic_bridge.application.dto.settings import BridgeSettingsState, ToggleKind
from vk_topic_bridge.application.ports.unit_of_work import UnitOfWork


class ToggleSettings:
    """Writes one toggle (or the factory defaults) in a single short transaction."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def execute(self, kind: ToggleKind, value: bool) -> BridgeSettingsState:
        async with self._uow_factory() as uow:
            state = await uow.bridge_settings.set_toggle(kind, value)
            await uow.commit()
        return state

    async def reset(self) -> BridgeSettingsState:
        async with self._uow_factory() as uow:
            state = await uow.bridge_settings.reset()
            await uow.commit()
        return state
