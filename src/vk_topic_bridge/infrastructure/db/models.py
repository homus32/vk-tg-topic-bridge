"""ORM models and delivery-state constants for the bridge SQLite schema (plan §5/§6)."""

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from vk_topic_bridge.infrastructure.db.base import Base

# Status strings mirror plan §6. Plain constants keep this module self-contained:
# the domain layer owns its own enums, and repositories map between the two.
PUBLICATION_STATUS_RESERVED = "reserved"
PUBLICATION_STATUS_SEND_STARTED = "send_started"
PUBLICATION_STATUS_PUBLISHED = "published"
PUBLICATION_STATUS_AMBIGUOUS = "ambiguous"
PUBLICATION_STATUS_FAILED_BEFORE_SEND = "failed_before_send"
PUBLICATION_STATUS_FAILED_PERMANENT = "failed_permanent"

PUBLICATION_STATUSES: tuple[str, ...] = (
    PUBLICATION_STATUS_RESERVED,
    PUBLICATION_STATUS_SEND_STARTED,
    PUBLICATION_STATUS_PUBLISHED,
    PUBLICATION_STATUS_AMBIGUOUS,
    PUBLICATION_STATUS_FAILED_BEFORE_SEND,
    PUBLICATION_STATUS_FAILED_PERMANENT,
)

REACTION_STATUS_NOT_DUE = "not_due"
REACTION_STATUS_PENDING = "pending"
REACTION_STATUS_SUCCEEDED = "succeeded"
REACTION_STATUS_FAILED = "failed"
REACTION_STATUS_AMBIGUOUS = "ambiguous"

REACTION_STATUSES: tuple[str, ...] = (
    REACTION_STATUS_NOT_DUE,
    REACTION_STATUS_PENDING,
    REACTION_STATUS_SUCCEEDED,
    REACTION_STATUS_FAILED,
    REACTION_STATUS_AMBIGUOUS,
)

SOURCE_TYPE_VK_MESSAGE = "vk_message"
SOURCE_TYPE_VK_WALL = "vk_wall"

DELIVERY_INTENT_AUTOMATIC = "automatic"
DELIVERY_INTENT_MANUAL = "manual"

DELIVERY_INTENTS: tuple[str, ...] = (DELIVERY_INTENT_AUTOMATIC, DELIVERY_INTENT_MANUAL)

BRIDGE_SETTINGS_SINGLETON_ID = 1

UNIQUE_GENERAL_TOPIC_INDEX = "uq_telegram_topics_general"
UNIQUE_GENERAL_ALIAS_INDEX = "uq_vk_topic_aliases_general"
DELIVERY_PUBLICATION_STATUS_INDEX = "ix_delivery_records_publication_status"
DELIVERY_REACTION_STATUS_INDEX = "ix_delivery_records_reaction_status"


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _status_check(column: str, allowed: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in allowed)
    return f"{column} IN ({quoted})"


class BridgeSettings(Base):
    """Singleton row (`id = 1`) holding mutable product configuration."""

    __tablename__ = "bridge_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=BRIDGE_SETTINGS_SINGLETON_ID)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_chat_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    auto_forward_all: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("1")
    )
    auto_forward_hashtags: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("1")
    )
    auto_forward_wall: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("1")
    )
    telegram_messages_topic_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_wall_topic_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Three-state destinations (draft :32/:169/:185): `configured=False + NULL` is unset,
    # `configured=True + NULL` is explicit General, `configured=True + N` is a named topic.
    telegram_messages_topic_configured: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0")
    )
    telegram_wall_topic_configured: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=_utc_now
    )


class TelegramTopic(Base):
    """Known Telegram forum topic; `topic_id IS NULL` represents the General topic."""

    __tablename__ = "telegram_topics"
    __table_args__ = (
        UniqueConstraint("telegram_chat_id", "topic_id", name="uq_telegram_topics_chat_topic"),
        # SQLite treats NULLs as distinct, so General (topic_id NULL) needs an explicit guard.
        Index(
            UNIQUE_GENERAL_TOPIC_INDEX,
            "telegram_chat_id",
            unique=True,
            sqlite_where=text("is_general = 1"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    topic_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    is_general: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    is_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class VkTopicAlias(Base):
    """Per-VK-user alias: at most one alias and one topic per user."""

    __tablename__ = "vk_topic_aliases"
    __table_args__ = (
        UniqueConstraint("vk_user_id", "alias_normalized", name="uq_vk_topic_aliases_user_alias"),
        UniqueConstraint("vk_user_id", "topic_id", name="uq_vk_topic_aliases_user_topic"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vk_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    topic_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    alias_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=_utc_now
    )


class DeliveryRecord(Base):
    """Idempotency ledger: one row per source event (UNIQUE source_type, source_key)."""

    __tablename__ = "delivery_records"
    __table_args__ = (
        UniqueConstraint("source_type", "source_key", name="uq_delivery_records_source"),
        CheckConstraint(
            _status_check("publication_status", PUBLICATION_STATUSES),
            name="ck_delivery_records_publication_status",
        ),
        CheckConstraint(
            _status_check("reaction_status", REACTION_STATUSES),
            name="ck_delivery_records_reaction_status",
        ),
        CheckConstraint(
            _status_check("intent", DELIVERY_INTENTS),
            name="ck_delivery_records_intent",
        ),
        Index(DELIVERY_PUBLICATION_STATUS_INDEX, "publication_status"),
        Index(DELIVERY_REACTION_STATUS_INDEX, "reaction_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_key: Mapped[str] = mapped_column(Text, nullable=False)
    publication_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text(f"'{PUBLICATION_STATUS_RESERVED}'")
    )
    reaction_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text(f"'{REACTION_STATUS_NOT_DUE}'")
    )
    intent: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text(f"'{DELIVERY_INTENT_AUTOMATIC}'")
    )
    claim_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    send_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    destination_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    destination_topic_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_message_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    ambiguous_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=_utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
