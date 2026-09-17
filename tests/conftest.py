"""Root test configuration: isolate every test from the developer's real `.env`.

Each test runs with dummy values for the required settings and with the
``Settings`` dotenv file disabled, so no test can read real secrets or fail
because of keys that only exist in a local ``.env``.
"""

import sys
from collections.abc import Iterator
from importlib import import_module
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    # Root modules (config.py, logger.py) must be importable regardless of how the
    # suite was invoked, including path-scoped runs.
    sys.path.insert(0, str(REPO_ROOT))

DUMMY_REQUIRED_ENV = {
    "TELEGRAM_BOT_TOKEN": "123456:TEST-BOT-TOKEN",
    "OWNER_IDS": "111,222",
    "TELEGRAM_API_ID": "123456",
    "TELEGRAM_API_HASH": "0123456789abcdef0123456789abcdef",
    "TELEGRAM_SESSION_PATH": "test-session",
    "VK_GROUP_TOKEN": "vk1.a.test-token",
    "DATABASE_URL": "sqlite+aiosqlite:///test.db",
}

OPTIONAL_KEYS = (
    "TELEGRAM_BOT_API_URL",
    "TELEGRAM_MTPROXY_SERVER",
    "TELEGRAM_MTPROXY_PORT",
    "TELEGRAM_MTPROXY_SECRET",
    "SOCKS5_PROXY_URL",
    "VK_GROUP_ID",
    "LOG_LEVEL",
    "LOG_LEVEL_LIBS",
    "LOG_DIR",
    "LOG_ROTATION",
    "LOG_RETENTION",
    "LOG_COMPRESSION",
)


def _config_module() -> ModuleType | None:
    try:
        return import_module("config")
    except ModuleNotFoundError:
        return None


@pytest.fixture(autouse=True)
def _isolated_settings_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for key, value in DUMMY_REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    for key in OPTIONAL_KEYS:
        monkeypatch.delenv(key, raising=False)

    config = _config_module()
    if config is not None:
        monkeypatch.setitem(config.Settings.model_config, "env_file", None)
    yield
