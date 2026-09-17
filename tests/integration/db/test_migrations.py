"""Integration tests for the Alembic-managed SQLite schema (base -> head)."""

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"
INITIAL_REVISION = "0001"

PRODUCT_TABLES = frozenset(
    {"bridge_settings", "telegram_topics", "vk_topic_aliases", "delivery_records"}
)

PUBLICATION_STATUSES = (
    "reserved",
    "send_started",
    "published",
    "ambiguous",
    "failed_before_send",
    "failed_permanent",
)
REACTION_STATUSES = ("not_due", "pending", "succeeded", "failed", "ambiguous")


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    return path


def _alembic_config() -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


def _upgrade(revision: str = "head") -> None:
    command.upgrade(_alembic_config(), revision)


def _downgrade(revision: str) -> None:
    command.downgrade(_alembic_config(), revision)


def _table_names(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {name for (name,) in rows}


def _index_names(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
    return {name for (name,) in rows}


def _index_sql(db_path: Path, index_name: str) -> str:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
            (index_name,),
        ).fetchone()
    assert row is not None, f"index {index_name!r} not found"
    return str(row[0])


def _insert_general_topic(db_path: Path, chat_id: int, title: str = "General") -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO telegram_topics (telegram_chat_id, topic_id, title, is_general, is_active)"
            " VALUES (?, NULL, ?, 1, 1)",
            (chat_id, title),
        )


def _insert_alias(
    db_path: Path,
    *,
    vk_user_id: int,
    topic_id: int | None,
    alias: str,
    alias_normalized: str,
) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO vk_topic_aliases (vk_user_id, topic_id, alias, alias_normalized)"
            " VALUES (?, ?, ?, ?)",
            (vk_user_id, topic_id, alias, alias_normalized),
        )


def _insert_delivery(
    db_path: Path,
    *,
    source_key: str,
    publication_status: str = "reserved",
    reaction_status: str | None = None,
) -> None:
    columns = ["source_type", "source_key", "publication_status"]
    values: list[str | int | None] = ["vk_message", source_key, publication_status]
    if reaction_status is not None:
        columns.append("reaction_status")
        values.append(reaction_status)
    placeholders = ", ".join("?" for _ in values)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            f"INSERT INTO delivery_records ({', '.join(columns)}) VALUES ({placeholders})",
            values,
        )


def test_migration_from_base_to_head_creates_expected_tables(db_path: Path) -> None:
    _upgrade()

    assert _table_names(db_path) >= PRODUCT_TABLES | {"alembic_version"}

    heads = ScriptDirectory.from_config(_alembic_config()).get_heads()
    assert heads == [INITIAL_REVISION], f"initial migration missing: heads={heads!r}"


def test_upgrade_head_is_idempotent(db_path: Path) -> None:
    _upgrade()
    _upgrade()

    with sqlite3.connect(db_path) as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert version == (INITIAL_REVISION,)
    assert _table_names(db_path) >= PRODUCT_TABLES


def test_downgrade_to_base_removes_product_tables(db_path: Path) -> None:
    _upgrade()

    _downgrade("base")

    assert _table_names(db_path).isdisjoint(PRODUCT_TABLES)


def test_expected_delivery_indexes_exist(db_path: Path) -> None:
    _upgrade()

    assert {
        "ix_delivery_records_publication_status",
        "ix_delivery_records_reaction_status",
    } <= _index_names(db_path)


def test_general_topic_partial_index_only_covers_general_rows(db_path: Path) -> None:
    _upgrade()

    compact = "".join(_index_sql(db_path, "uq_telegram_topics_general").lower().split())

    assert "uniqueindexuq_telegram_topics_general" in compact
    assert "ontelegram_topics(telegram_chat_id)" in compact
    assert "whereis_general=1" in compact


def test_partial_unique_index_blocks_second_general_topic(db_path: Path) -> None:
    _upgrade()
    _insert_general_topic(db_path, chat_id=100)

    with pytest.raises(sqlite3.IntegrityError):
        _insert_general_topic(db_path, chat_id=100)


def test_partial_unique_index_allows_general_topic_in_another_chat(db_path: Path) -> None:
    _upgrade()
    _insert_general_topic(db_path, chat_id=100)

    _insert_general_topic(db_path, chat_id=200, title="General 2")

    with sqlite3.connect(db_path) as connection:
        count = connection.execute(
            "SELECT count(*) FROM telegram_topics WHERE is_general = 1"
        ).fetchone()
    assert count == (2,)


def test_alias_unique_per_user_and_normalized_alias(db_path: Path) -> None:
    _upgrade()
    _insert_alias(db_path, vk_user_id=7, topic_id=1, alias="Новости", alias_normalized="новости")

    with pytest.raises(sqlite3.IntegrityError):
        _insert_alias(
            db_path,
            vk_user_id=7,
            topic_id=2,
            alias="новости",
            alias_normalized="новости",
        )


def test_alias_unique_per_user_and_topic(db_path: Path) -> None:
    _upgrade()
    _insert_alias(db_path, vk_user_id=7, topic_id=5, alias="A", alias_normalized="a")

    with pytest.raises(sqlite3.IntegrityError):
        _insert_alias(db_path, vk_user_id=7, topic_id=5, alias="B", alias_normalized="b")


def test_delivery_records_defaults(db_path: Path) -> None:
    _upgrade()
    _insert_delivery(db_path, source_key="1:2:3")

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT reaction_status, attempts, review_required, completed_at FROM delivery_records"
        ).fetchone()
    assert row == ("not_due", 0, 0, None)


def test_delivery_source_key_is_unique(db_path: Path) -> None:
    _upgrade()
    _insert_delivery(db_path, source_key="1:2:3")

    with pytest.raises(sqlite3.IntegrityError):
        _insert_delivery(db_path, source_key="1:2:3")


@pytest.mark.parametrize("status", PUBLICATION_STATUSES)
def test_publication_status_accepts_known_statuses(db_path: Path, status: str) -> None:
    _upgrade()

    _insert_delivery(db_path, source_key=f"1:2:{status}", publication_status=status)


def test_publication_status_rejects_unknown_status(db_path: Path) -> None:
    _upgrade()

    with pytest.raises(sqlite3.IntegrityError):
        _insert_delivery(db_path, source_key="1:2:9", publication_status="bogus")


@pytest.mark.parametrize("status", REACTION_STATUSES)
def test_reaction_status_accepts_known_statuses(db_path: Path, status: str) -> None:
    _upgrade()

    _insert_delivery(db_path, source_key=f"1:3:{status}", reaction_status=status)


def test_reaction_status_rejects_unknown_status(db_path: Path) -> None:
    _upgrade()

    with pytest.raises(sqlite3.IntegrityError):
        _insert_delivery(db_path, source_key="1:3:9", reaction_status="bogus")
