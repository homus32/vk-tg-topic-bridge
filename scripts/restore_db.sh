#!/usr/bin/env bash
# Restore a SQLite backup produced by backup_db.sh.
# Stop the application before running this (see docs/deployment-runbook.md).
# Usage: restore_db.sh <backup_file> [db_path]
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: restore_db.sh <backup_file> [db_path]" >&2
  exit 1
fi

BACKUP_FILE="$1"
DB_PATH="${2:-data/vk_topic_bridge.db}"

if [[ ! -f "$BACKUP_FILE" ]]; then
  echo "restore_db: backup not found: $BACKUP_FILE" >&2
  exit 1
fi

mkdir -p "$(dirname "$DB_PATH")"
cp "$BACKUP_FILE" "$DB_PATH"
rm -f "$DB_PATH-wal" "$DB_PATH-shm"

REVISION="$(sqlite3 "$DB_PATH" "SELECT version_num FROM alembic_version" 2>/dev/null || true)"
if [[ -z "$REVISION" ]]; then
  echo "restore_db: restored database has no alembic_version row" >&2
  exit 1
fi

EXPECTED="$(cd "$(dirname "$0")/.." && uv run --locked python - <<'PY'
from alembic.config import Config
from alembic.script import ScriptDirectory
from pathlib import Path

root = Path.cwd()
config = Config(str(root / "alembic.ini"))
config.set_main_option("script_location", str(root / "migrations"))
print(ScriptDirectory.from_config(config).get_current_head())
PY
)"

if [[ "$REVISION" != "$EXPECTED" ]]; then
  echo "restore_db: restored revision $REVISION != head $EXPECTED" >&2
  exit 1
fi

echo "restored: $BACKUP_FILE -> $DB_PATH (revision $REVISION == head)"
