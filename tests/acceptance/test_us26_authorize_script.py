"""US-26: the root authorization script contract.

The script prompts for phone, login code and 2FA password through injectable
callables, moves an existing session of another account aside before re-authorizing
(session data overwritten), and has no side effects at import time. Only public
helpers are exercised: the interactive flow itself is never run here.
"""

from __future__ import annotations

import builtins
import getpass
import importlib
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from telethon import TelegramClient

from tests.acceptance._fakes import settings_from_env
from vk_topic_bridge.infrastructure.telegram.proxy import client_connection_kwargs

MODULE_PATH = Path(__file__).resolve().parents[2] / "authorize_telegram.py"


def _load_fresh_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("acceptance_authorize_telegram", MODULE_PATH)
    assert spec is not None
    loader = spec.loader
    assert loader is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_us26_module_lives_in_the_repository_root() -> None:
    assert MODULE_PATH.is_file()
    assert MODULE_PATH.parent.name == "vk-topic-bridge"


def test_us26_public_helpers_are_the_prompt_and_session_contract() -> None:
    module = importlib.import_module("authorize_telegram")

    assert callable(module.prompt_phone)
    assert callable(module.prompt_code)
    assert callable(module.prompt_password)
    assert callable(module.session_file_for)
    assert callable(module.prepare_fresh_session)
    assert callable(module.build_client)
    assert callable(module.main)


def test_us26_import_has_no_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts: list[str] = []
    constructions: list[object] = []

    def forbidden_input(prompt: str = "") -> str:
        prompts.append(prompt)
        raise AssertionError("input() must not run at import time")

    def forbidden_getpass(prompt: str = "", stream: object = None) -> str:
        prompts.append(prompt)
        raise AssertionError("getpass() must not run at import time")

    def forbidden_init(self: object, *args: object, **kwargs: object) -> None:
        constructions.append(args)
        raise AssertionError("TelegramClient must not be constructed at import time")

    monkeypatch.setattr(builtins, "input", forbidden_input)
    monkeypatch.setattr(getpass, "getpass", forbidden_getpass)
    monkeypatch.setattr(TelegramClient, "__init__", forbidden_init)

    module = _load_fresh_module()

    assert prompts == []
    assert constructions == []
    assert callable(module.main)


def test_us26_prompts_read_phone_code_and_two_factor_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("authorize_telegram")
    stdin_answers = iter([" +15551234567 ", " 12345 "])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(stdin_answers))
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": " 2fa-secret ")

    assert module.prompt_phone() == "+15551234567"
    assert module.prompt_code() == "12345"
    assert module.prompt_password() == "2fa-secret"


@pytest.mark.parametrize(
    "configured, expected",
    [
        pytest.param(
            "owner-account", Path("runtime/telethon/owner-account.session"), id="relative"
        ),
        pytest.param(
            "/tmp/account.session",
            Path("/tmp/account.session"),
            id="absolute-with-suffix",
        ),
    ],
)
def test_us26_session_path_is_normalized(
    monkeypatch: pytest.MonkeyPatch, configured: str, expected: Path
) -> None:
    module = importlib.import_module("authorize_telegram")
    settings = settings_from_env(monkeypatch, TELEGRAM_SESSION_PATH=configured)

    assert module.session_file_for(settings) == expected
    assert str(module.session_file_for(settings)).endswith(".session")


def test_us26_reauthorization_overwrites_the_previous_account_session(tmp_path: Path) -> None:
    module = importlib.import_module("authorize_telegram")
    session_path = tmp_path / "account.session"
    session_path.write_bytes(b"old-account-session")
    sidecars = [
        session_path.with_name(session_path.name + suffix)
        for suffix in ("-journal", "-wal", "-shm")
    ]
    for sidecar in sidecars:
        sidecar.write_bytes(b"old-sidecar")

    backup = module.prepare_fresh_session(session_path)

    assert backup is not None
    assert backup.name.startswith("account.session.bak-")
    assert backup.read_bytes() == b"old-account-session"
    assert not session_path.exists()
    assert all(not sidecar.exists() for sidecar in sidecars)


def test_us26_missing_session_needs_no_backup(tmp_path: Path) -> None:
    module = importlib.import_module("authorize_telegram")

    assert module.prepare_fresh_session(tmp_path / "fresh.session") is None


def test_us26_build_client_uses_settings_transport_kwargs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = importlib.import_module("authorize_telegram")
    settings = settings_from_env(monkeypatch, TELEGRAM_SESSION_PATH=str(tmp_path / "acc.session"))
    captured: dict[str, object] = {}

    class StubClient:
        def __init__(self, session: str, api_id: int, api_hash: str, **kwargs: object) -> None:
            captured["session"] = session
            captured["api_id"] = api_id
            captured["api_hash"] = api_hash
            captured["kwargs"] = kwargs

    monkeypatch.setattr(module, "TelegramClient", StubClient)

    client = module.build_client(settings, tmp_path / "acc.session")

    assert isinstance(client, StubClient)
    assert captured["session"] == str(tmp_path / "acc.session")
    assert captured["api_id"] == settings.TELEGRAM_API_ID
    assert captured["kwargs"] == client_connection_kwargs(settings)


def test_us26_session_settings_resolve_under_the_ignored_runtime_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = settings_from_env(monkeypatch, TELEGRAM_SESSION_PATH="my-telethon")

    assert settings.TELEGRAM_SESSION_PATH == "runtime/telethon/my-telethon.session"

    gitignore = (MODULE_PATH.parent / ".gitignore").read_text(encoding="utf-8")
    assert "runtime/telethon" in gitignore
