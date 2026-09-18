.PHONY: sync lock lock-check format format-check lint typecheck test test-e2e check hooks backup-db restore-db

sync:
	uv sync --all-groups

hooks:
	git config --local core.hooksPath .githooks

lock:
	uv lock

lock-check:
	uv lock --check

format:
	uv run --locked ruff format .

format-check:
	uv run --locked ruff format --check .

lint:
	uv run --locked ruff check .

typecheck:
	uv run --locked basedpyright

test:
	uv run --locked pytest

test-e2e:
	uv run --locked pytest -m e2e

check: lock-check format-check lint typecheck test

backup-db:
	bash scripts/backup_db.sh

restore-db:
	bash scripts/restore_db.sh $(BACKUP)
