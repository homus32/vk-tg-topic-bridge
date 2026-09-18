"""finish: topic availability, General three-state flags, delivery intent, alias guard

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-18

Three-state General uses an explicit ``telegram_*_topic_configured`` boolean plus the
nullable topic id (draft :32/:169/:185): ``False + NULL`` = unset, ``True + NULL`` =
explicit General, ``True + N`` = named topic. No sentinel topic ids.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DELIVERY_INTENTS = ("automatic", "manual")


def _check(column: str, allowed: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in allowed)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
    op.add_column(
        "telegram_topics",
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "telegram_topics",
        sa.Column("is_hidden", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )

    # SQLite treats NULLs as distinct, so the composite UNIQUE(vk_user_id, topic_id)
    # cannot enforce one General alias per user; the partial index closes that gap.
    op.create_index(
        "uq_vk_topic_aliases_general",
        "vk_topic_aliases",
        ["vk_user_id"],
        unique=True,
        sqlite_where=text("topic_id IS NULL"),
    )

    op.add_column(
        "bridge_settings",
        sa.Column(
            "telegram_messages_topic_configured",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "bridge_settings",
        sa.Column(
            "telegram_wall_topic_configured",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    # batch mode recreates the table on SQLite; existing constraints are reflected and
    # copied automatically, so they must not be re-declared here (that duplicates them).
    with op.batch_alter_table("delivery_records") as batch:
        batch.add_column(
            sa.Column(
                "intent",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'automatic'"),
            )
        )
        batch.create_check_constraint(
            "ck_delivery_records_intent", _check("intent", DELIVERY_INTENTS)
        )


def downgrade() -> None:
    with op.batch_alter_table("delivery_records") as batch:
        batch.drop_constraint("ck_delivery_records_intent", type_="check")
        batch.drop_column("intent")

    op.drop_column("bridge_settings", "telegram_wall_topic_configured")
    op.drop_column("bridge_settings", "telegram_messages_topic_configured")

    op.drop_index("uq_vk_topic_aliases_general", table_name="vk_topic_aliases")

    op.drop_column("telegram_topics", "is_hidden")
    op.drop_column("telegram_topics", "is_closed")
