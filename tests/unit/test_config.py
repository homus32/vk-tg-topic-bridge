"""Unit tests for the canonical root `config.py` (Settings contract + helpers).

`config` is imported lazily so that, during the RED phase, its absence surfaces as
a normal test failure instead of aborting collection of the whole suite.
"""

import importlib
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import SecretStr, ValidationError

RUNTIME_SESSION_DIR = Path("runtime/telethon")


def _config() -> ModuleType:
    return importlib.import_module("config")


def _prepare_env(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def test_full_environment_builds_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    _prepare_env(
        monkeypatch,
        TELEGRAM_BOT_TOKEN="111:full-token",
        OWNER_IDS="10,20,30",
        TELEGRAM_BOT_API_URL="https://bot.example.com",
        TELEGRAM_API_ID="4242",
        TELEGRAM_API_HASH="hash-value",
        TELEGRAM_SESSION_PATH="full-user.session",
        SOCKS5_PROXY_URL="socks5://127.0.0.1:10809",
        VK_GROUP_TOKEN="vk1.a.full",
        VK_GROUP_ID="777",
        DATABASE_URL="sqlite+aiosqlite:///full.db",
    )
    settings = config.Settings(_env_file=None)

    assert frozenset({10, 20, 30}) == settings.OWNER_IDS
    assert settings.TELEGRAM_API_ID == 4242
    assert settings.VK_GROUP_ID == 777
    assert settings.TELEGRAM_BOT_API_URL == "https://bot.example.com"
    assert settings.DATABASE_URL == "sqlite+aiosqlite:///full.db"
    assert Path(settings.TELEGRAM_SESSION_PATH) == RUNTIME_SESSION_DIR / "full-user.session"
    assert isinstance(settings.TELEGRAM_BOT_TOKEN, SecretStr)
    assert isinstance(settings.TELEGRAM_API_HASH, SecretStr)
    assert isinstance(settings.VK_GROUP_TOKEN, SecretStr)


def test_optional_vk_user_token_is_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    _prepare_env(monkeypatch, VK_USER_TOKEN="vk1.a.user-token")

    settings = config.Settings(_env_file=None)

    assert isinstance(settings.VK_USER_TOKEN, SecretStr)
    assert settings.VK_USER_TOKEN.get_secret_value() == "vk1.a.user-token"


def test_owner_ids_parsed_from_csv_with_spaces(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    _prepare_env(monkeypatch, OWNER_IDS="1, 2")
    settings = config.Settings(_env_file=None)

    assert frozenset({1, 2}) == settings.OWNER_IDS
    assert isinstance(settings.OWNER_IDS, frozenset)


def test_owner_ids_single_value(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    _prepare_env(monkeypatch, OWNER_IDS="42")
    settings = config.Settings(_env_file=None)

    assert frozenset({42}) == settings.OWNER_IDS


def test_owner_ids_empty_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    _prepare_env(monkeypatch, OWNER_IDS="")

    with pytest.raises(ValidationError):
        config.Settings(_env_file=None)


@pytest.mark.parametrize("value", ["0", "-1", "5,-5"])
def test_owner_ids_reject_non_positive(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    config = _config()
    _prepare_env(monkeypatch, OWNER_IDS=value)

    with pytest.raises(ValidationError):
        config.Settings(_env_file=None)


def test_owner_ids_reject_non_numeric(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    _prepare_env(monkeypatch, OWNER_IDS="not-an-int")

    with pytest.raises(ValidationError):
        config.Settings(_env_file=None)


def test_missing_required_bot_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    with pytest.raises(ValidationError):
        config.Settings(_env_file=None)


def test_missing_required_owner_ids_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    monkeypatch.delenv("OWNER_IDS", raising=False)

    with pytest.raises(ValidationError):
        config.Settings(_env_file=None)


def test_empty_optional_values_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    _prepare_env(
        monkeypatch,
        TELEGRAM_BOT_API_URL="",
        SOCKS5_PROXY_URL="",
        LOG_LEVEL="",
        LOG_DIR="",
    )
    settings = config.Settings(_env_file=None)

    assert settings.TELEGRAM_BOT_API_URL is None
    assert settings.SOCKS5_PROXY_URL is None
    assert settings.LOG_LEVEL == "INFO"
    assert settings.LOG_LEVEL_LIBS == "WARNING"
    assert Path("logs") == settings.LOG_DIR
    assert settings.LOG_ROTATION == "10 MB"
    assert settings.LOG_RETENTION == "14 days"
    assert settings.LOG_COMPRESSION == "zip"


def test_bot_api_url_trailing_slash_is_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    _prepare_env(monkeypatch, TELEGRAM_BOT_API_URL="https://bot.example.com/")
    settings = config.Settings(_env_file=None)

    assert settings.TELEGRAM_BOT_API_URL == "https://bot.example.com"


@pytest.mark.parametrize(
    "value", ["bot.example.com", "ftp://bot.example.com", "ws://bot.example.com"]
)
def test_bot_api_url_requires_http_scheme(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    config = _config()
    _prepare_env(monkeypatch, TELEGRAM_BOT_API_URL=value)

    with pytest.raises(ValidationError):
        config.Settings(_env_file=None)


def test_bot_api_url_absent_defaults_to_official(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    settings = config.Settings(_env_file=None)

    assert settings.TELEGRAM_BOT_API_URL is None
    assert settings.bot_api_proxy_url() is None


@pytest.mark.parametrize(
    "loopback_url",
    ["http://localhost:8081", "http://127.0.0.1:8081", "http://[::1]:8081"],
)
def test_loopback_bot_api_url_disables_socks5(
    monkeypatch: pytest.MonkeyPatch, loopback_url: str
) -> None:
    config = _config()
    _prepare_env(
        monkeypatch,
        TELEGRAM_BOT_API_URL=loopback_url,
        SOCKS5_PROXY_URL="socks5://127.0.0.1:10809",
    )
    settings = config.Settings(_env_file=None)

    assert settings.bot_api_proxy_url() is None


def test_remote_bot_api_url_uses_socks5(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    _prepare_env(
        monkeypatch,
        TELEGRAM_BOT_API_URL="https://api.custom.example",
        SOCKS5_PROXY_URL="socks5://127.0.0.1:10809",
    )
    settings = config.Settings(_env_file=None)

    assert settings.bot_api_proxy_url() == "socks5://127.0.0.1:10809"


def test_bot_api_without_configured_proxy_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    _prepare_env(monkeypatch, TELEGRAM_BOT_API_URL="https://api.custom.example")
    settings = config.Settings(_env_file=None)

    assert settings.bot_api_proxy_url() is None


def test_bot_api_absent_uses_socks5_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    _prepare_env(monkeypatch, SOCKS5_PROXY_URL="socks5h://127.0.0.1:10809")
    settings = config.Settings(_env_file=None)

    assert settings.bot_api_proxy_url() == "socks5h://127.0.0.1:10809"


@pytest.mark.parametrize(
    "value", ["http://127.0.0.1:1080", "socks4://127.0.0.1:1080", "127.0.0.1:1080"]
)
def test_socks5_url_requires_socks_scheme(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    config = _config()
    _prepare_env(monkeypatch, SOCKS5_PROXY_URL=value)

    with pytest.raises(ValidationError):
        config.Settings(_env_file=None)


@pytest.mark.parametrize(
    "partial",
    [
        {"TELEGRAM_MTPROXY_SERVER": "127.0.0.1"},
        {"TELEGRAM_MTPROXY_PORT": "1443"},
        {"TELEGRAM_MTPROXY_SECRET": "dd00000000000000000000000000000000"},
        {"TELEGRAM_MTPROXY_SERVER": "127.0.0.1", "TELEGRAM_MTPROXY_PORT": "1443"},
        {
            "TELEGRAM_MTPROXY_SERVER": "127.0.0.1",
            "TELEGRAM_MTPROXY_SECRET": "dd00000000000000000000000000000000",
        },
        {
            "TELEGRAM_MTPROXY_PORT": "1443",
            "TELEGRAM_MTPROXY_SECRET": "dd00000000000000000000000000000000",
        },
    ],
)
def test_mtproxy_partial_triplet_rejected(
    monkeypatch: pytest.MonkeyPatch, partial: dict[str, str]
) -> None:
    config = _config()
    _prepare_env(monkeypatch, **partial)

    with pytest.raises(ValidationError) as excinfo:
        config.Settings(_env_file=None)

    assert "MTProxy" in str(excinfo.value)


def test_mtproxy_complete_triplet_selects_mtproxy(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    _prepare_env(
        monkeypatch,
        TELEGRAM_MTPROXY_SERVER="127.0.0.1",
        TELEGRAM_MTPROXY_PORT="1443",
        TELEGRAM_MTPROXY_SECRET="dd00000000000000000000000000000000",
    )
    settings = config.Settings(_env_file=None)

    transport = settings.telethon_transport()
    assert isinstance(transport, config.MtProxyTransport)
    assert transport.host == "127.0.0.1"
    assert transport.port == 1443
    assert transport.secret == "dd00000000000000000000000000000000"


def test_mtproxy_takes_priority_over_socks5(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    _prepare_env(
        monkeypatch,
        TELEGRAM_MTPROXY_SERVER="proxy.local",
        TELEGRAM_MTPROXY_PORT="1443",
        TELEGRAM_MTPROXY_SECRET="secret-123",
        SOCKS5_PROXY_URL="socks5://127.0.0.1:10809",
    )
    settings = config.Settings(_env_file=None)

    assert isinstance(settings.telethon_transport(), config.MtProxyTransport)


def test_socks5_transport_selected_without_mtproxy(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    _prepare_env(monkeypatch, SOCKS5_PROXY_URL="socks5://127.0.0.1:10809")
    settings = config.Settings(_env_file=None)

    transport = settings.telethon_transport()
    assert isinstance(transport, config.Socks5Transport)
    assert transport.url == "socks5://127.0.0.1:10809"


def test_direct_transport_when_no_proxy_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    settings = config.Settings(_env_file=None)

    assert isinstance(settings.telethon_transport(), config.DirectTransport)


@pytest.mark.parametrize("port", ["0", "65536"])
def test_mtproxy_port_out_of_range_rejected(monkeypatch: pytest.MonkeyPatch, port: str) -> None:
    config = _config()
    _prepare_env(
        monkeypatch,
        TELEGRAM_MTPROXY_SERVER="127.0.0.1",
        TELEGRAM_MTPROXY_PORT=port,
        TELEGRAM_MTPROXY_SECRET="secret",
    )

    with pytest.raises(ValidationError):
        config.Settings(_env_file=None)


def test_mtproxy_secret_is_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    _prepare_env(
        monkeypatch,
        TELEGRAM_MTPROXY_SERVER="127.0.0.1",
        TELEGRAM_MTPROXY_PORT="1443",
        TELEGRAM_MTPROXY_SECRET="top-secret",
    )
    settings = config.Settings(_env_file=None)

    assert isinstance(settings.TELEGRAM_MTPROXY_SECRET, SecretStr)


def test_vk_group_id_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()

    assert config.Settings(_env_file=None).VK_GROUP_ID is None

    _prepare_env(monkeypatch, VK_GROUP_ID="555")
    assert config.Settings(_env_file=None).VK_GROUP_ID == 555


def test_database_url_requires_aiosqlite_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()

    _prepare_env(monkeypatch, DATABASE_URL="postgresql://user:pass@host/db")
    with pytest.raises(ValidationError):
        config.Settings(_env_file=None)

    _prepare_env(monkeypatch, DATABASE_URL="sqlite:///plain.db")
    with pytest.raises(ValidationError):
        config.Settings(_env_file=None)

    _prepare_env(monkeypatch, DATABASE_URL="sqlite+aiosqlite:///ok.db")
    assert config.Settings(_env_file=None).DATABASE_URL == "sqlite+aiosqlite:///ok.db"


def test_telegram_api_id_must_be_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    _prepare_env(monkeypatch, TELEGRAM_API_ID="0")

    with pytest.raises(ValidationError):
        config.Settings(_env_file=None)


def test_session_path_relative_resolved_under_runtime_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config()
    _prepare_env(monkeypatch, TELEGRAM_SESSION_PATH="vk_topic_bridge.session")
    settings = config.Settings(_env_file=None)

    assert Path(settings.TELEGRAM_SESSION_PATH) == RUNTIME_SESSION_DIR / "vk_topic_bridge.session"


def test_session_path_relative_gains_session_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    _prepare_env(monkeypatch, TELEGRAM_SESSION_PATH="my_account")
    settings = config.Settings(_env_file=None)

    assert Path(settings.TELEGRAM_SESSION_PATH) == RUNTIME_SESSION_DIR / "my_account.session"


def test_session_path_nested_relative_uses_basename(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    _prepare_env(monkeypatch, TELEGRAM_SESSION_PATH="nested/dir/account.session")
    settings = config.Settings(_env_file=None)

    assert Path(settings.TELEGRAM_SESSION_PATH) == RUNTIME_SESSION_DIR / "account.session"


def test_session_path_cannot_escape_runtime_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    _prepare_env(monkeypatch, TELEGRAM_SESSION_PATH="../evil")
    settings = config.Settings(_env_file=None)

    assert Path(settings.TELEGRAM_SESSION_PATH) == RUNTIME_SESSION_DIR / "evil.session"


def test_session_path_absolute_inside_runtime_dir_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config()
    runtime_dir = config.RUNTIME_SESSION_DIR.resolve()

    _prepare_env(monkeypatch, TELEGRAM_SESSION_PATH=str(runtime_dir / "user.session"))
    with_suffix = config.Settings(_env_file=None)
    assert Path(with_suffix.TELEGRAM_SESSION_PATH) == runtime_dir / "user.session"

    _prepare_env(monkeypatch, TELEGRAM_SESSION_PATH=str(runtime_dir / "raw"))
    without_suffix = config.Settings(_env_file=None)
    assert Path(without_suffix.TELEGRAM_SESSION_PATH) == runtime_dir / "raw.session"


def test_session_path_absolute_outside_runtime_dir_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config()
    _prepare_env(monkeypatch, TELEGRAM_SESSION_PATH="/tmp/elsewhere/acc.session")

    with pytest.raises(ValidationError) as excinfo:
        config.Settings(_env_file=None)

    assert "runtime/telethon" in str(excinfo.value)


def test_log_file_uses_log_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = _config()

    assert config.Settings(_env_file=None).log_file() == Path("logs/app.log")

    _prepare_env(monkeypatch, LOG_DIR=str(tmp_path))
    assert config.Settings(_env_file=None).log_file() == tmp_path / "app.log"


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    config.get_settings.cache_clear()

    try:
        first = config.get_settings()
        _prepare_env(monkeypatch, LOG_LEVEL="DEBUG")
        second = config.get_settings()

        assert first is second
        assert second.LOG_LEVEL == "INFO"
    finally:
        config.get_settings.cache_clear()


def test_settings_are_immutable(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    settings = config.Settings(_env_file=None)

    with pytest.raises(ValidationError):
        settings.LOG_LEVEL = "DEBUG"


def test_secrets_are_not_leaked_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    _prepare_env(
        monkeypatch,
        TELEGRAM_BOT_TOKEN="111:super-secret-token",
        TELEGRAM_API_HASH="super-secret-hash",
        VK_GROUP_TOKEN="vk1.a.super-secret-vk",
    )
    settings = config.Settings(_env_file=None)

    rendered = repr(settings)
    assert "super-secret-token" not in rendered
    assert "super-secret-hash" not in rendered
    assert "super-secret-vk" not in rendered
