"""SQLAlchemy implementation of per-VK-user topic aliases."""

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from vk_topic_bridge.infrastructure.db.models import VkTopicAlias


class VkAliasRepositoryImpl:
    """Upserts and removes aliases; uniqueness stays enforced by the DB constraints."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_user(self, vk_user_id: int) -> list[tuple[int | None, str]]:
        result = await self._session.execute(
            select(VkTopicAlias)
            .where(VkTopicAlias.vk_user_id == vk_user_id)
            .order_by(VkTopicAlias.topic_id, VkTopicAlias.id)
            .execution_options(populate_existing=True)
        )
        return [(row.topic_id, row.alias_normalized) for row in result.scalars()]

    async def upsert(
        self, vk_user_id: int, topic_id: int | None, alias: str, alias_normalized: str
    ) -> None:
        if topic_id is None:
            # `UNIQUE(vk_user_id, topic_id)` does not cover NULLs in SQLite: the General
            # destination has to be matched explicitly before inserting.
            await self._upsert_general(vk_user_id, alias, alias_normalized)
            return

        stmt = (
            sqlite_insert(VkTopicAlias)
            .values(
                vk_user_id=vk_user_id,
                topic_id=topic_id,
                alias=alias,
                alias_normalized=alias_normalized,
            )
            .on_conflict_do_update(
                index_elements=["vk_user_id", "topic_id"],
                set_={"alias": alias, "alias_normalized": alias_normalized},
            )
        )
        await self._session.execute(stmt)

    async def delete(self, vk_user_id: int, topic_id: int | None) -> None:
        condition = (
            VkTopicAlias.topic_id.is_(None)
            if topic_id is None
            else VkTopicAlias.topic_id == topic_id
        )
        await self._session.execute(
            delete(VkTopicAlias).where(VkTopicAlias.vk_user_id == vk_user_id, condition)
        )

    async def _upsert_general(self, vk_user_id: int, alias: str, alias_normalized: str) -> None:
        existing = (
            await self._session.execute(
                select(VkTopicAlias)
                .where(VkTopicAlias.vk_user_id == vk_user_id, VkTopicAlias.topic_id.is_(None))
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if existing is None:
            self._session.add(
                VkTopicAlias(
                    vk_user_id=vk_user_id,
                    topic_id=None,
                    alias=alias,
                    alias_normalized=alias_normalized,
                )
            )
            return
        existing.alias = alias
        existing.alias_normalized = alias_normalized
