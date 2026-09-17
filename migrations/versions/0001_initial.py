"""create bridge settings, telegram topics, vk topic aliases and delivery records

Revision ID: 0001
Revises:
Create Date: 2026-09-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PUBLICATION_STATUSES = (
    "reserved",
    "send_started",
    "published",
    "ambiguous",
    "failed_before_send",
    "failed_permanent",
)
REACTION_STATUSES = ("not_due", "pending", "succeeded", "failed", "ambiguous")


def _check(column: str, allowed: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in allowed)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
    op.create_table(
        "bridge_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_chat_title", sa.Text(), nullable=True),
        sa.Column("auto_forward_all", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "auto_forward_hashtags", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("auto_forward_wall", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("telegram_messages_topic_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_wall_topic_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "telegram_topics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("topic_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("is_general", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_chat_id", "topic_id", name="uq_telegram_topics_chat_topic"),
    )
    # SQLite treats NULLs as distinct: General has topic_id NULL, so uniqueness of a single
    # General row per chat needs a partial index rather than the composite UNIQUE above.
    op.create_index(
        "uq_telegram_topics_general",
        "telegram_topics",
        ["telegram_chat_id"],
        unique=True,
        sqlite_where=text("is_general = 1"),
    )

    op.create_table(
        "vk_topic_aliases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("vk_user_id", sa.BigInteger(), nullable=False),
        sa.Column("topic_id", sa.BigInteger(), nullable=True),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("alias_normalized", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "vk_user_id", "alias_normalized", name="uq_vk_topic_aliases_user_alias"
        ),
        sa.UniqueConstraint("vk_user_id", "topic_id", name="uq_vk_topic_aliases_user_topic"),
    )

    op.create_table(
        "delivery_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_key", sa.Text(), nullable=False),
        sa.Column(
            "publication_status", sa.Text(), nullable=False, server_default=sa.text("'reserved'")
        ),
        sa.Column(
            "reaction_status", sa.Text(), nullable=False, server_default=sa.text("'not_due'")
        ),
        sa.Column("claim_token", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("send_started_at", sa.DateTime(), nullable=True),
        sa.Column("destination_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("destination_topic_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_message_ids", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("payload_hash", sa.Text(), nullable=True),
        sa.Column("ambiguous_at", sa.DateTime(), nullable=True),
        sa.Column("review_required", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()
        ),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            _check("publication_status", PUBLICATION_STATUSES),
            name="ck_delivery_records_publication_status",
        ),
        sa.CheckConstraint(
            _check("reaction_status", REACTION_STATUSES),
            name="ck_delivery_records_reaction_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_type", "source_key", name="uq_delivery_records_source"),
    )
    op.create_index(
        "ix_delivery_records_publication_status", "delivery_records", ["publication_status"]
    )
    op.create_index("ix_delivery_records_reaction_status", "delivery_records", ["reaction_status"])


def downgrade() -> None:
    op.drop_index("ix_delivery_records_reaction_status", table_name="delivery_records")
    op.drop_index("ix_delivery_records_publication_status", table_name="delivery_records")
    op.drop_table("delivery_records")
    op.drop_index("uq_telegram_topics_general", table_name="telegram_topics")
    op.drop_table("telegram_topics")
    op.drop_table("vk_topic_aliases")
    op.drop_table("bridge_settings")
