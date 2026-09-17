"""Interactive Telethon authorization for the owner's user account (US-26).

Standalone operator script: it never starts the application, never imports the
bootstrap, and has no side effects at import time. Sensitive input (login code,
2FA password, API hash) is read interactively and is never printed or logged; the
persistent session lives in the gitignored ``runtime/telethon/`` directory.

Telethon appends ``.session`` when the given path has no such extension, so this
script normalizes the path once and passes the fully suffixed ``.session`` path to
``TelegramClient``. That file, plus its ``-journal``/``-wal``/``-shm`` sidecars, is
the entire authorization state: re-running moves it aside so a different account
can be authorized and the previous session is no longer used.
"""

from __future__ import annotations

import asyncio
import functools
import getpass
import inspect
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError
from telethon import TelegramClient, types

from config import SESSION_SUFFIX, Settings, get_settings
from vk_topic_bridge.infrastructure.telegram.proxy import client_connection_kwargs

BACKUP_MARKER = ".bak-"
SESSION_SIDECAR_SUFFIXES = ("-journal", "-wal", "-shm")
BACKUP_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S%f"


def prompt_phone() -> str:
    return input("Enter the phone number of the Telegram account to authorize: ").strip()


def prompt_code() -> str:
    return input("Enter the login code Telegram sent you: ").strip()


def prompt_password() -> str:
    # getpass keeps the 2FA password (and the account it unlocks) off the screen.
    return getpass.getpass("Enter the account 2FA password (leave empty if not set): ").strip()


def session_file_for(settings: Settings) -> Path:
    """Return the normalized session path passed to `TelegramClient` (with `.session`)."""
    path = Path(settings.TELEGRAM_SESSION_PATH)
    if not path.name.endswith(SESSION_SUFFIX):
        # Append, never `with_suffix`: a dotted file name must not lose its stem.
        path = path.with_name(f"{path.name}{SESSION_SUFFIX}")
    return path


def prepare_fresh_session(session_path: Path) -> Path | None:
    """Move any existing session aside and remove stale sidecars.

    Returns the backup path of the previous session, or `None` when no session
    existed. An existing file is renamed (never deleted) so a failed
    re-authorization cannot destroy a still-working account.
    """
    backup_path: Path | None = None
    if session_path.exists():
        timestamp = datetime.now(UTC).strftime(BACKUP_TIMESTAMP_FORMAT)
        backup_path = session_path.with_name(f"{session_path.name}{BACKUP_MARKER}{timestamp}")
        session_path.rename(backup_path)
    for suffix in SESSION_SIDECAR_SUFFIXES:
        session_path.with_name(f"{session_path.name}{suffix}").unlink(missing_ok=True)
    return backup_path


def build_client(settings: Settings, session_path: Path) -> TelegramClient:
    """Construct the Telethon client with the transport kwargs from `proxy.py`."""
    # `client_connection_kwargs` is type-erased (`dict[str, object]`); `functools.partial`
    # lets its values reach the typed constructor without casts or ignores.
    factory = functools.partial(
        TelegramClient,
        str(session_path),
        settings.TELEGRAM_API_ID,
        settings.TELEGRAM_API_HASH.get_secret_value(),
        **client_connection_kwargs(settings),
    )
    return factory()


async def main(
    phone_prompt: Callable[[], str] = prompt_phone,
    code_prompt: Callable[[], str] = prompt_code,
    password_prompt: Callable[[], str] = prompt_password,
) -> int:
    """Run the interactive phone/code/2FA flow and persist the session. Returns the exit code."""
    try:
        settings = get_settings()
    except ValidationError as exc:
        fields = ", ".join(
            dict.fromkeys(str(error["loc"][0]) for error in exc.errors() if error["loc"])
        )
        print(f"Configuration is invalid; check these .env fields: {fields or 'unknown'}")
        return 1

    session_path = session_file_for(settings)
    client: TelegramClient | None = None
    try:
        backup_path = prepare_fresh_session(session_path)
        session_path.parent.mkdir(parents=True, exist_ok=True)
        if backup_path is not None:
            print(f"Previous session moved aside: {backup_path}")
        client = build_client(settings, session_path)
        await _await_if_needed(
            client.start(phone=phone_prompt, password=password_prompt, code_callback=code_prompt)
        )
        if not await client.is_user_authorized():
            print(
                "Authorization did not complete: the account is not authorized. "
                "Run the script again and answer all prompts."
            )
            return 1
        me = await client.get_me()
        print(f"Authorized as {_describe_account(me)}. Session stored at {session_path}")
        return 0
    except EOFError, KeyboardInterrupt:
        print(
            "Interactive input was interrupted or unavailable. "
            "Run this script in a terminal and answer the prompts."
        )
        return 1
    except Exception as exc:
        # Top-level boundary: report one line and keep secrets out of the traceback.
        print(f"Authorization failed ({type(exc).__name__}). Run the script again to retry.")
        return 1
    finally:
        if client is not None:
            await _await_if_needed(client.disconnect())


async def _await_if_needed(result: object) -> None:
    # Telethon returns a coroutine when the loop is running and a value otherwise.
    if inspect.isawaitable(result):
        await result


def _describe_account(account: object) -> str:
    if not isinstance(account, types.User):
        return "an unidentified account"
    name = " ".join(part for part in (account.first_name, account.last_name) if part)
    display = name or (f"@{account.username}" if account.username else "an unnamed account")
    return f"{display} [id={account.id}]"


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
