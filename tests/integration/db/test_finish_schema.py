"""Schema assertions for migration 0002 (finish): General three-state, availability, intent.

These are the RED anchor for task 1 (plan `.omo/plans/finish-vk-topic-bridge.md`):
migrations cannot be test-first in the usual sense, so the finished schema is asserted
here before the migration exists.
"""

import sqlite3
from collections.abc import Sequence
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"
FINISH_REVISION = "0002"


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "finish-schema.db"
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


def _query(db_path: Path, sql: str, params: Sequence[object] = ()) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(db_path)
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def _execute(db_path: Path, sql: str, params: Sequence[object] = ()) -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(sql, params)
        connection.commit()
    finally:
        connection.close()


def _column_names(db_path: Path, table: str) -> set[str]:
    rows = _query(db_path, f"PRAGMA table_info({table})")
    return {str(row[1]) for row in rows}


def _index_names(db_path: Path) -> set[str]:
    rows = _query(db_path, "SELECT name FROM sqlite_master WHERE type = 'index'")
    return {str(name) for (name,) in rows}


def _index_sql(db_path: Path, index_name: str) -> str:
    rows = _query(
        db_path,
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
        (index_name,),
    )
    assert rows, f"index {index_name!r} not found"
    return str(rows[0][0])


def _table_sql(db_path: Path, table: str) -> str:
    rows = _query(
        db_path, "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    )
    assert rows, f"table {table!r} not found"
    return str(rows[0][0])


def _insert_general_alias(db_path: Path, vk_user_id: int, alias: str) -> None:
    _execute(
        db_path,
        "INSERT INTO vk_topic_aliases (vk_user_id, topic_id, alias, alias_normalized)"
        " VALUES (?, NULL, ?, ?)",
        (vk_user_id, alias, alias),
    )


def test_telegram_topics_availability_columns_exist(db_path: Path) -> None:
    _upgrade()

    columns = _column_names(db_path, "telegram_topics")

    assert {"is_closed", "is_hidden"} <= columns


def test_bridge_settings_configured_flags_exist(db_path: Path) -> None:
    _upgrade()

    columns = _column_names(db_path, "bridge_settings")

    assert {
        "telegram_messages_topic_configured",
        "telegram_wall_topic_configured",
    } <= columns


def test_delivery_records_intent_column_exists(db_path: Path) -> None:
    _upgrade()

    assert "intent" in _column_names(db_path, "delivery_records")
    assert "intent in ('automatic', 'manual')" in " ".join(
        _table_sql(db_path, "delivery_records").lower().split()
    )


def test_general_alias_partial_index_exists(db_path: Path) -> None:
    _upgrade()

    assert "uq_vk_topic_aliases_general" in _index_names(db_path)
    compact = "".join(_index_sql(db_path, "uq_vk_topic_aliases_general").lower().split())
    assert "uniqueindexuq_vk_topic_aliases_general" in compact
    assert "onvk_topic_aliases(vk_user_id)" in compact
    assert "wheretopic_idisnull" in compact


def test_general_alias_is_unique_per_user(db_path: Path) -> None:
    _upgrade()
    _insert_general_alias(db_path, vk_user_id=7, alias="general")

    with pytest.raises(sqlite3.IntegrityError):
        _insert_general_alias(db_path, vk_user_id=7, alias="другой")


def test_general_alias_allows_another_user(db_path: Path) -> None:
    _upgrade()
    _insert_general_alias(db_path, vk_user_id=7, alias="general")

    _insert_general_alias(db_path, vk_user_id=8, alias="general")

    count = _query(db_path, "SELECT count(*) FROM vk_topic_aliases WHERE topic_id IS NULL")
    assert count == [(2,)]


def test_delivery_intent_defaults_to_automatic(db_path: Path) -> None:
    _upgrade()
    _execute(
        db_path,
        "INSERT INTO delivery_records (source_type, source_key) VALUES ('vk_message', '1:1:1')",
    )

    assert _query(db_path, "SELECT intent FROM delivery_records") == [("automatic",)]


def test_delivery_intent_rejects_unknown_value(db_path: Path) -> None:
    _upgrade()

    with pytest.raises(sqlite3.IntegrityError):
        _execute(
            db_path,
            "INSERT INTO delivery_records (source_type, source_key, intent)"
            " VALUES ('vk_message', '1:1:2', 'bogus')",
        )


def test_availability_flags_survive_repository_roundtrip(db_path: Path) -> None:
    """The migration must not reuse the frozen-schema failure of discarding the flags."""
    _upgrade()

    _execute(
        db_path,
        "INSERT INTO telegram_topics (telegram_chat_id, topic_id, title, is_general, is_active,"
        " is_closed, is_hidden) VALUES (100, 5, 'Ticket', 0, 1, 1, 0)",
    )

    assert _query(
        db_path, "SELECT is_closed, is_hidden FROM telegram_topics WHERE topic_id = 5"
    ) == [(1, 0)]


def test_downgrade_then_upgrade_preserves_existing_rows(db_path: Path) -> None:
    _upgrade()
    _execute(
        db_path,
        "INSERT INTO delivery_records (source_type, source_key) VALUES ('vk_message', '7:7:7')",
    )

    _downgrade("0001")
    _upgrade()

    assert _query(
        db_path, "SELECT source_key FROM delivery_records WHERE source_key = '7:7:7'"
    ) == [("7:7:7",)]
    assert _query(db_path, "SELECT version_num FROM alembic_version") == [(FINISH_REVISION,)]


def test_migration_head_is_finish_revision(db_path: Path) -> None:
    _upgrade()

    assert _query(db_path, "SELECT version_num FROM alembic_version") == [(FINISH_REVISION,)]
