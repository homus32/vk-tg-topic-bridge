"""SQLAlchemy implementation of the singleton ``bridge_settings`` repository."""

from sqlalchemy.ext.asyncio import AsyncSession

from vk_topic_bridge.application.dto.settings import BridgeSettingsState, ToggleKind
from vk_topic_bridge.infrastructure.db.models import BRIDGE_SETTINGS_SINGLETON_ID, BridgeSettings

_TOGGLE_ATTRIBUTES: dict[ToggleKind, str] = {
    ToggleKind.ALL: "auto_forward_all",
    ToggleKind.HASHTAGS: "auto_forward_hashtags",
    ToggleKind.WALL: "auto_forward_wall",
}


def _to_state(row: BridgeSettings) -> BridgeSettingsState:
    return BridgeSettingsState(
        telegram_chat_id=row.telegram_chat_id,
        telegram_chat_title=row.telegram_chat_title,
        auto_forward_all=row.auto_forward_all,
        auto_forward_hashtags=row.auto_forward_hashtags,
        auto_forward_wall=row.auto_forward_wall,
        telegram_messages_topic_id=row.telegram_messages_topic_id,
        telegram_wall_topic_id=row.telegram_wall_topic_id,
        telegram_messages_topic_configured=bool(row.telegram_messages_topic_configured),
        telegram_wall_topic_configured=bool(row.telegram_wall_topic_configured),
    )


def _new_singleton() -> BridgeSettings:
    # Mirror BridgeSettingsState.defaults() explicitly: ORM server_defaults are not
    # populated on the instance until a refresh, and toggles must read True right away.
    return BridgeSettings(
        id=BRIDGE_SETTINGS_SINGLETON_ID,
        auto_forward_all=True,
        auto_forward_hashtags=True,
        auto_forward_wall=True,
        telegram_messages_topic_configured=False,
        telegram_wall_topic_configured=False,
    )


class BridgeSettingsRepositoryImpl:
    """Reads and mutates the singleton row without owning the transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self) -> BridgeSettingsState | None:
        row = await self._session.get(BridgeSettings, BRIDGE_SETTINGS_SINGLETON_ID)
        return None if row is None else _to_state(row)

    async def upsert_chat(self, chat_id: int, title: str | None) -> BridgeSettingsState:
        row = await self._ensure_row()
        row.telegram_chat_id = chat_id
        row.telegram_chat_title = title
        return _to_state(row)

    async def set_messages_topic(self, topic_id: int | None) -> BridgeSettingsState:
        row = await self._ensure_row()
        row.telegram_messages_topic_id = topic_id
        row.telegram_messages_topic_configured = True
        return _to_state(row)

    async def set_wall_topic(self, topic_id: int | None) -> BridgeSettingsState:
        row = await self._ensure_row()
        row.telegram_wall_topic_id = topic_id
        row.telegram_wall_topic_configured = True
        return _to_state(row)

    async def set_toggle(self, kind: ToggleKind, value: bool) -> BridgeSettingsState:
        row = await self._ensure_row()
        setattr(row, _TOGGLE_ATTRIBUTES[kind], value)
        return _to_state(row)

    async def reset(self) -> BridgeSettingsState:
        row = await self._ensure_row()
        defaults = BridgeSettingsState.defaults()
        row.telegram_chat_id = defaults.telegram_chat_id
        row.telegram_chat_title = defaults.telegram_chat_title
        row.auto_forward_all = defaults.auto_forward_all
        row.auto_forward_hashtags = defaults.auto_forward_hashtags
        row.auto_forward_wall = defaults.auto_forward_wall
        row.telegram_messages_topic_id = defaults.telegram_messages_topic_id
        row.telegram_wall_topic_id = defaults.telegram_wall_topic_id
        row.telegram_messages_topic_configured = defaults.telegram_messages_topic_configured
        row.telegram_wall_topic_configured = defaults.telegram_wall_topic_configured
        return _to_state(row)

    async def _ensure_row(self) -> BridgeSettings:
        row = await self._session.get(BridgeSettings, BRIDGE_SETTINGS_SINGLETON_ID)
        if row is None:
            row = _new_singleton()
            self._session.add(row)
            await self._session.flush()
        return row
