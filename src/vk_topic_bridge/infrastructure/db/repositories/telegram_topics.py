"""SQLAlchemy implementation of the Telegram topics repository (soft-delete refresh)."""

from collections.abc import Sequence

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from vk_topic_bridge.domain.value_objects import TopicInfo
from vk_topic_bridge.infrastructure.db.models import TelegramTopic


def _to_topic(row: TelegramTopic) -> TopicInfo:
    return TopicInfo(
        topic_id=row.topic_id,
        title=row.title,
        is_general=bool(row.is_general),
        is_closed=bool(row.is_closed),
        is_hidden=bool(row.is_hidden),
    )


class TelegramTopicsRepositoryImpl:
    """Upserts discovered topics and deactivates the ones that disappeared."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def replace_all(self, chat_id: int, topics: Sequence[TopicInfo]) -> None:
        seen: set[int | None] = set()
        for topic in topics:
            seen.add(topic.topic_id)
            await self._upsert(chat_id, topic)
        await self._deactivate_unseen(chat_id, seen)

    async def list(self, chat_id: int) -> list[TopicInfo]:
        result = await self._session.execute(
            select(TelegramTopic)
            .where(TelegramTopic.telegram_chat_id == chat_id, TelegramTopic.is_active.is_(True))
            .order_by(TelegramTopic.topic_id, TelegramTopic.id)
            .execution_options(populate_existing=True)
        )
        return [_to_topic(row) for row in result.scalars()]

    async def mark_missing(self, chat_id: int, seen_topic_ids: Sequence[int | None]) -> None:
        await self._deactivate_unseen(chat_id, set(seen_topic_ids))

    async def delete_chat(self, chat_id: int) -> None:
        """Remove every snapshot row of the chat (factory reset, not deactivation)."""
        await self._session.execute(
            delete(TelegramTopic).where(TelegramTopic.telegram_chat_id == chat_id)
        )

    async def _upsert(self, chat_id: int, topic: TopicInfo) -> None:
        values = {
            "telegram_chat_id": chat_id,
            "topic_id": topic.topic_id,
            "title": topic.title,
            "is_general": topic.is_general,
            "is_active": True,
            "is_closed": topic.is_closed,
            "is_hidden": topic.is_hidden,
            "last_seen_at": func.current_timestamp(),
        }
        # General rows carry topic_id NULL, where the composite UNIQUE does not apply:
        # SQLite treats NULLs as distinct, so the partial unique index is the target.
        if topic.is_general or topic.topic_id is None:
            stmt = (
                sqlite_insert(TelegramTopic)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=["telegram_chat_id"],
                    index_where=text("is_general = 1"),
                    set_={
                        "title": topic.title,
                        "is_general": True,
                        "is_active": True,
                        "is_closed": topic.is_closed,
                        "is_hidden": topic.is_hidden,
                        "last_seen_at": func.current_timestamp(),
                    },
                )
            )
        else:
            stmt = (
                sqlite_insert(TelegramTopic)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=["telegram_chat_id", "topic_id"],
                    set_={
                        "title": topic.title,
                        "is_general": topic.is_general,
                        "is_active": True,
                        "is_closed": topic.is_closed,
                        "is_hidden": topic.is_hidden,
                        "last_seen_at": func.current_timestamp(),
                    },
                )
            )
        await self._session.execute(stmt)

    async def _deactivate_unseen(self, chat_id: int, seen: set[int | None]) -> None:
        result = await self._session.execute(
            select(TelegramTopic)
            .where(TelegramTopic.telegram_chat_id == chat_id, TelegramTopic.is_active.is_(True))
            .execution_options(populate_existing=True)
        )
        for row in result.scalars():
            if row.topic_id not in seen:
                row.is_active = False
