#!/usr/bin/env bash
# SQLite backup via the online-copy pattern: safe against a running app (WAL mode).
# Usage: backup_db.sh [db_path] [dest_dir]
set -euo pipefail

DB_PATH="${1:-data/vk_topic_bridge.db}"
DEST_DIR="${2:-backups}"

if [[ ! -f "$DB_PATH" ]]; then
  echo "backup_db: database not found: $DB_PATH" >&2
  exit 1
fi

mkdir -p "$DEST_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
TARGET="$DEST_DIR/vk_topic_bridge-$STAMP.db"

sqlite3 "$DB_PATH" ".backup '$TARGET'"

echo "$TARGET"
