"""E2E harness: real-credential fixtures and the provisioning guard.

The root ``tests/conftest.py`` replaces every settings value with dummies and disables
the dotenv file. E2E is the single exception, so this module overrides that autouse
isolation fixture and lets ``get_settings()`` read the real environment / ``.env``.
No fixture here asserts on, logs or prints a secret value.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from config import Settings, get_settings

ENV_EXAMPLE_BOT_TOKEN_MARKER = "AAInvalidTelegramBotToken_DoNotUse"
ENV_EXAMPLE_VK_TOKEN_MARKER = "invalid_test_token"
ENV_EXAMPLE_API_HASHES = frozenset({"0123456789abcdef0123456789abcdef", "0" * 32})

SKIP_REASON_NOT_PROVISIONED = "real credentials not configured"


@pytest.fixture(autouse=True)
def _isolated_settings_env() -> None:
    """Override the root dummy-env fixture: only e2e tests may load real credentials."""


@pytest.fixture(scope="session")
def e2e_run_id() -> str:
    """Unique per-run identifier for correlating later manual E2E evidence."""
    return f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid4().hex[:8]}"


@pytest.fixture
def e2e_settings() -> Settings:
    """Real settings, or a skip when ``.env`` still carries placeholder credentials."""
    try:
        settings = get_settings()
    except ValidationError as exc:
        pytest.skip(
            f"{SKIP_REASON_NOT_PROVISIONED}: {len(exc.errors())} required setting(s) not set"
        )
    reason = _placeholder_reason(settings)
    if reason is not None:
        pytest.skip(f"{SKIP_REASON_NOT_PROVISIONED}: {reason}")
    return settings


def _placeholder_reason(settings: Settings) -> str | None:
    """Name the placeholder field (never its value) so no secret reaches the report."""
    if ENV_EXAMPLE_BOT_TOKEN_MARKER in settings.TELEGRAM_BOT_TOKEN.get_secret_value():
        return "TELEGRAM_BOT_TOKEN is the .env.example placeholder"
    if ENV_EXAMPLE_VK_TOKEN_MARKER in settings.VK_GROUP_TOKEN.get_secret_value():
        return "VK_GROUP_TOKEN is the .env.example placeholder"
    if settings.TELEGRAM_API_HASH.get_secret_value() in ENV_EXAMPLE_API_HASHES:
        return "TELEGRAM_API_HASH is the .env.example placeholder"
    return None
