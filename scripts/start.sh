#!/usr/bin/env bash
# Production entrypoint: migrate then run. PM2 runs this script (interpreter: none).
# Contract (docs/05 §22): migrations MUST complete before any poller starts;
# no other logic belongs here.
set -euo pipefail

cd "$(dirname "$0")/.."

uv run --locked alembic upgrade head
exec uv run --locked python main.py
