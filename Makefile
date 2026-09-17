.PHONY: sync lock lock-check format format-check lint typecheck test check

sync:
	uv sync --all-groups

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

check: lock-check format-check lint typecheck test
