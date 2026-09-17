"""Unit tests for the root `authorize_telegram.py` (US-26) authorization script.

The suite never opens a network connection, never reads stdin, never builds a real
`TelegramClient` and never writes into the ignored `runtime/telethon/` directory:
session files live under `tmp_path` and Telethon is replaced by `_StubClient`.
"""

from __future__ import annotations

import builtins
import getpass
import importlib
import importlib.util
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import ClassVar

import pytest
from pydantic import ValidationError
from telethon import TelegramClient, types
from telethon.network.connection import ConnectionTcpMTProxyRandomizedIntermediate

from config import Settings
from vk_topic_bridge.infrastructure.telegram.proxy import client_connection_kwargs

MODULE_PATH = Path(__file__).resolve().parents[2] / "authorize_telegram.py"
MTPROXY_SECRET = "dd00000000000000000000000000000000"
PHONE_SECRET = "+15551234567"
CODE_SECRET = "CODE-SECRET-42"
PASSWORD_SECRET = "PASSWORD-SECRET-7"

ME_USER = types.User(id=777, first_name="Owner", last_name="Test", username="owner")


class _StubClient:
    """Recording stand-in for `TelegramClient`: no socket, no session file."""

    authorized: ClassVar[bool] = True
    start_error: ClassVar[BaseException | None] = None
    me: ClassVar[object] = ME_USER
    instances: ClassVar[list[_StubClient]] = []

    def __init__(self, session: str, api_id: int, api_hash: str, **proxy_kwargs: object) -> None:
        self.session = session
        self.api_id = api_id
        self.api_hash = api_hash
        self.proxy_kwargs = proxy_kwargs
        self.start_kwargs: dict[str, Callable[[], str]] = {}
        self.disconnected = False
        _StubClient.instances.append(self)

    async def start(
        self,
        *,
        phone: Callable[[], str],
        password: Callable[[], str],
        code_callback: Callable[[], str],
    ) -> _StubClient:
        self.start_kwargs = {"phone": phone, "password": password, "code_callback": code_callback}
        if _StubClient.start_error is not None:
            raise _StubClient.start_error
        return self

    async def is_user_authorized(self) -> bool:
        return _StubClient.authorized

    async def get_me(self) -> object:
        return _StubClient.me

    async def disconnect(self) -> None:
        self.disconnected = True


@pytest.fixture(autouse=True)
def _reset_stub_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(_StubClient, "instances", [])
    monkeypatch.setattr(_StubClient, "authorized", True)
    monkeypatch.setattr(_StubClient, "start_error", None)
    yield


def _module() -> ModuleType:
    return importlib.import_module("authorize_telegram")


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    # The conftest fixture disables the dotenv file; only the dummy env applies.
    return Settings.model_validate({})


def _load_fresh_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("authorize_telegram_import_probe", MODULE_PATH)
    assert spec is not None
    loader = spec.loader
    assert loader is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _install_module(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **env: str
) -> tuple[ModuleType, Settings, Path]:
    module = _module()
    # Settings only accepts sessions under the CWD-scoped runtime/telethon directory.
    monkeypatch.chdir(tmp_path)
    session_path = tmp_path / "runtime" / "telethon" / "account.session"
    settings = _settings(monkeypatch, TELEGRAM_SESSION_PATH=str(session_path), **env)
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr(module, "TelegramClient", _StubClient)
    return module, settings, session_path


def test_import_executes_no_prompts_and_constructs_no_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt_calls: list[str] = []
    constructions: list[tuple[object, ...]] = []

    def forbidden_input(prompt: str = "") -> str:
        prompt_calls.append(prompt)
        raise AssertionError("input() must not run while importing authorize_telegram")

    def forbidden_getpass(prompt: str = "", stream: object = None) -> str:
        prompt_calls.append(prompt)
        raise AssertionError("getpass() must not run while importing authorize_telegram")

    def forbidden_init(self: object, *args: object, **kwargs: object) -> None:
        constructions.append(args)
        raise AssertionError("TelegramClient must not be constructed while importing")

    monkeypatch.setattr(builtins, "input", forbidden_input)
    monkeypatch.setattr(getpass, "getpass", forbidden_getpass)
    monkeypatch.setattr(TelegramClient, "__init__", forbidden_init)

    module = _load_fresh_module()

    assert prompt_calls == []
    assert constructions == []
    assert callable(module.main)
    assert callable(module.build_client)


def test_session_file_for_appends_session_suffix_under_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    settings = _settings(monkeypatch, TELEGRAM_SESSION_PATH="owner-account")

    session_path = module.session_file_for(settings)

    assert session_path == Path("runtime/telethon/owner-account.session")
    assert session_path.suffix == ".session"


def test_session_file_for_appends_without_truncating_dotted_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    monkeypatch.chdir(tmp_path)
    scoped = tmp_path / "runtime" / "telethon" / "owner.account"
    settings = _settings(monkeypatch, TELEGRAM_SESSION_PATH=str(scoped))

    assert module.session_file_for(settings) == scoped.with_name("owner.account.session")


def test_prepare_fresh_session_returns_none_when_absent(tmp_path: Path) -> None:
    module = _module()
    session_path = tmp_path / "missing.session"

    assert module.prepare_fresh_session(session_path) is None
    assert not session_path.exists()


def test_prepare_fresh_session_backs_up_session_and_removes_sidecars(tmp_path: Path) -> None:
    module = _module()
    session_path = tmp_path / "account.session"
    session_path.write_bytes(b"old-sqlite-session")
    sidecars = [
        session_path.with_name(session_path.name + suffix)
        for suffix in ("-journal", "-wal", "-shm")
    ]
    for sidecar in sidecars:
        sidecar.write_bytes(b"stale-sidecar")
    unrelated = tmp_path / "keep.txt"
    unrelated.write_text("keep", encoding="utf-8")

    backup_path = module.prepare_fresh_session(session_path)

    assert backup_path is not None
    assert backup_path != session_path
    assert backup_path.name.startswith("account.session.bak-")
    assert backup_path.read_bytes() == b"old-sqlite-session"
    assert not session_path.exists()
    assert all(not sidecar.exists() for sidecar in sidecars)
    assert unrelated.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize(
    "env",
    [
        pytest.param({}, id="direct"),
        pytest.param({"SOCKS5_PROXY_URL": "socks5://127.0.0.1:10809"}, id="socks5"),
        pytest.param(
            {
                "TELEGRAM_MTPROXY_SERVER": "127.0.0.1",
                "TELEGRAM_MTPROXY_PORT": "1443",
                "TELEGRAM_MTPROXY_SECRET": MTPROXY_SECRET,
            },
            id="mtproxy",
        ),
    ],
)
def test_build_client_passes_resolved_proxy_kwargs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, env: dict[str, str]
) -> None:
    module = _module()
    settings = _settings(monkeypatch, **env)
    session_path = tmp_path / "runtime" / "telethon" / "account.session"
    sentinel = object()
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_client(*args: object, **kwargs: object) -> object:
        calls.append((args, kwargs))
        return sentinel

    monkeypatch.setattr(module, "TelegramClient", fake_client)

    result = module.build_client(settings, session_path)

    assert result is sentinel
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == (
        str(session_path),
        settings.TELEGRAM_API_ID,
        settings.TELEGRAM_API_HASH.get_secret_value(),
    )
    assert kwargs == client_connection_kwargs(settings)
    if "TELEGRAM_MTPROXY_SERVER" in env:
        assert kwargs["connection"] is ConnectionTcpMTProxyRandomizedIntermediate
        assert kwargs["proxy"] == ("127.0.0.1", 1443, MTPROXY_SECRET)


async def test_main_authorizes_and_reports_only_non_sensitive_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module, settings, session_path = _install_module(monkeypatch, tmp_path)
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_bytes(b"previous-account-session")
    sidecar = session_path.with_name(session_path.name + "-wal")
    sidecar.write_bytes(b"stale-sidecar")

    exit_code = await module.main(
        phone_prompt=lambda: PHONE_SECRET,
        code_prompt=lambda: CODE_SECRET,
        password_prompt=lambda: PASSWORD_SECRET,
    )

    assert exit_code == 0
    client = _StubClient.instances[0]
    assert client.session == str(session_path)
    assert client.proxy_kwargs == client_connection_kwargs(settings)
    assert client.start_kwargs["phone"]() == PHONE_SECRET
    assert client.start_kwargs["code_callback"]() == CODE_SECRET
    assert client.start_kwargs["password"]() == PASSWORD_SECRET
    assert client.disconnected is True
    assert not session_path.exists()
    assert len(list(session_path.parent.glob("account.session.bak-*"))) == 1
    assert not sidecar.exists()

    captured = capsys.readouterr()
    assert "777" in captured.out
    assert "Owner" in captured.out
    secrets = (
        PHONE_SECRET,
        CODE_SECRET,
        PASSWORD_SECRET,
        settings.TELEGRAM_API_HASH.get_secret_value(),
    )
    for secret in secrets:
        assert secret not in captured.out
        assert secret not in captured.err


async def test_main_returns_failure_when_account_is_not_authorized(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module, _settings_obj, _session_path = _install_module(monkeypatch, tmp_path)
    monkeypatch.setattr(_StubClient, "authorized", False)

    exit_code = await module.main(
        phone_prompt=lambda: PHONE_SECRET,
        code_prompt=lambda: CODE_SECRET,
        password_prompt=lambda: PASSWORD_SECRET,
    )

    assert exit_code != 0
    assert _StubClient.instances[0].disconnected is True
    captured = capsys.readouterr()
    assert "not authorized" in captured.out.lower()
    assert "Traceback" not in captured.out + captured.err
    assert CODE_SECRET not in captured.out + captured.err
    assert PASSWORD_SECRET not in captured.out + captured.err


async def test_main_reports_interrupted_input_without_traceback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module, _settings_obj, _session_path = _install_module(monkeypatch, tmp_path)
    monkeypatch.setattr(_StubClient, "start_error", EOFError())

    exit_code = await module.main(
        phone_prompt=lambda: PHONE_SECRET,
        code_prompt=lambda: CODE_SECRET,
        password_prompt=lambda: PASSWORD_SECRET,
    )

    assert exit_code != 0
    assert _StubClient.instances[0].disconnected is True
    captured = capsys.readouterr()
    assert "interactive" in captured.out.lower()
    assert "Traceback" not in captured.out + captured.err
    assert CODE_SECRET not in captured.out + captured.err
    assert PASSWORD_SECRET not in captured.out + captured.err


async def test_main_reports_invalid_settings_without_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _module()
    validation_error = ValidationError.from_exception_data(
        "Settings",
        [{"type": "missing", "loc": ("TELEGRAM_API_ID",), "input": None}],
    )

    def broken_settings() -> Settings:
        raise validation_error

    monkeypatch.setattr(module, "get_settings", broken_settings)
    monkeypatch.setattr(module, "TelegramClient", _StubClient)

    exit_code = await module.main(
        phone_prompt=lambda: PHONE_SECRET,
        code_prompt=lambda: CODE_SECRET,
        password_prompt=lambda: PASSWORD_SECRET,
    )

    assert exit_code != 0
    assert _StubClient.instances == []
    captured = capsys.readouterr()
    assert "TELEGRAM_API_ID" in captured.out
    assert "configuration" in captured.out.lower()
    assert "Traceback" not in captured.out + captured.err
