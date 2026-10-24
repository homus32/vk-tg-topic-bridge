"""Log in via Telegram QR without requesting an SMS or in-app code.

Run from the project root: uv run --with qrcode authorize_telegram_qr.py
Stop every process using TELEGRAM_SESSION_PATH before running this script.
"""

from __future__ import annotations

import asyncio
import getpass
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import qrcode
from telethon.errors import SessionPasswordNeededError

from authorize_telegram import build_client, session_file_for
from config import get_settings

SIDECARS = ("", "-journal", "-wal", "-shm")


def show_qr(url: str) -> None:
    """Print compact black-on-white QR using ANSI and Unicode half-blocks."""
    qr = qrcode.QRCode(border=3)
    qr.add_data(url)
    qr.make(fit=True)
    matrix = qr.get_matrix()

    print("\nТелефон: Telegram → Настройки → Устройства → Подключить устройство")
    for y in range(0, len(matrix), 2):
        upper = matrix[y]
        lower = matrix[y + 1] if y + 1 < len(matrix) else [False] * len(upper)
        row = "".join(
            "█" if top and bottom else "▀" if top else "▄" if bottom else " "
            for top, bottom in zip(upper, lower, strict=True)
        )
        print(f"\x1b[30;47m{row}\x1b[0m")
    print("Подтверди вход на телефоне. Не закрывай этот терминал.\n")


def install_session(fresh: Path, destination: Path) -> Path | None:
    """Back up the existing SQLite database and sidecars before installing the new one."""
    backup = destination.with_name(
        destination.name + ".bak-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    )
    moved: list[tuple[Path, Path]] = []
    try:
        for suffix in SIDECARS:
            original = Path(str(destination) + suffix)
            if original.exists():
                target = Path(str(backup) + suffix)
                original.replace(target)
                moved.append((original, target))
        fresh.replace(destination)
    except Exception:
        for original, target in reversed(moved):
            target.replace(original)
        raise
    return backup if moved else None


async def main() -> None:
    settings = get_settings()
    destination = session_file_for(settings)
    destination.parent.mkdir(parents=True, exist_ok=True)

    # Keep an incomplete login isolated; do not touch the application session.
    with tempfile.TemporaryDirectory(prefix=".telegram-qr-", dir=destination.parent) as workdir:
        fresh = Path(workdir) / destination.name
        client = build_client(settings, fresh)
        try:
            await client.connect()
            login = await client.qr_login()

            while True:
                show_qr(login.url)
                try:
                    await login.wait()
                    break
                except TimeoutError:
                    print("Срок действия QR-кода истёк, создаю следующий...")
                    await login.recreate()
                except SessionPasswordNeededError:
                    password = getpass.getpass("Пароль двухэтапной проверки Telegram: ")
                    await client.sign_in(password=password)
                    break

            if not await client.is_user_authorized():
                raise RuntimeError("Telegram не подтвердил авторизацию")

            account = await client.get_me()
            if account is None:
                raise RuntimeError("Не удалось получить сведения об аккаунте")
            print(f"Успешный вход: ID аккаунта {account.id}")
        finally:
            await client.disconnect()

        # SQLite session is closed here. Move only after successful authorization.
        backup = install_session(fresh, destination)
        if backup is not None:
            print(f"Резервная копия прежней сессии: {backup}")
        print(f"Новая сессия сохранена: {destination}")
        print("Теперь можно запустить один экземпляр приложения.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nАвторизация прервана; рабочая сессия не заменена.")
    except Exception as exc:
        print(f"Ошибка QR-авторизации: {type(exc).__name__}: {exc}")
        raise SystemExit(1) from None
