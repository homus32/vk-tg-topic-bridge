"""Canonical, immutable application configuration.

Secrets and infrastructure parameters live here; mutable product state lives in the
database. This module is the single place that reads the process environment.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Annotated, ClassVar
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

RUNTIME_SESSION_DIR = Path("runtime/telethon")
SESSION_SUFFIX = ".session"
LOG_FILE_NAME = "app.log"
DATABASE_URL_PREFIX = "sqlite+aiosqlite:///"
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _with_session_suffix(path: Path) -> Path:
    """Append `.session` without truncating a dotted stem (unlike ``Path.with_suffix``)."""
    if path.name.endswith(SESSION_SUFFIX):
        return path
    return path.with_name(f"{path.name}{SESSION_SUFFIX}")


@dataclass(frozen=True, slots=True)
class MtProxyTransport:
    host: str
    port: int
    secret: str


@dataclass(frozen=True, slots=True)
class Socks5Transport:
    url: str


@dataclass(frozen=True, slots=True)
class DirectTransport:
    pass


type TelethonTransport = MtProxyTransport | Socks5Transport | DirectTransport


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="forbid",
        env_ignore_empty=True,
        case_sensitive=False,
        frozen=True,
    )

    TELEGRAM_BOT_TOKEN: SecretStr = Field(min_length=1)
    OWNER_IDS: Annotated[frozenset[int], NoDecode]
    TELEGRAM_BOT_API_URL: str | None = None
    TELEGRAM_API_ID: int = Field(gt=0)
    TELEGRAM_API_HASH: SecretStr = Field(min_length=1)
    TELEGRAM_SESSION_PATH: str = Field(min_length=1)
    TELEGRAM_MTPROXY_SERVER: str | None = None
    TELEGRAM_MTPROXY_PORT: int | None = Field(default=None, ge=1, le=65535)
    TELEGRAM_MTPROXY_SECRET: SecretStr | None = None
    SOCKS5_PROXY_URL: str | None = None
    VK_GROUP_TOKEN: SecretStr = Field(min_length=1)
    VK_GROUP_ID: int | None = None
    DATABASE_URL: str = Field(min_length=1)
    LOG_LEVEL: str = "INFO"
    LOG_LEVEL_LIBS: str = "WARNING"
    LOG_DIR: Path = Path("logs")
    LOG_ROTATION: str = "10 MB"
    LOG_RETENTION: str = "14 days"
    LOG_COMPRESSION: str = "zip"

    _MTPROXY_FIELDS: ClassVar[tuple[str, str, str]] = (
        "TELEGRAM_MTPROXY_SERVER",
        "TELEGRAM_MTPROXY_PORT",
        "TELEGRAM_MTPROXY_SECRET",
    )

    @field_validator("OWNER_IDS", mode="before")
    @classmethod
    def _parse_owner_ids(cls, value: object) -> object:
        if isinstance(value, str):
            raw = [part.strip() for part in value.split(",") if part.strip()]
        elif isinstance(value, (set, frozenset, list, tuple)):
            raw = [str(item).strip() for item in value]
        else:
            return value
        if not raw:
            raise ValueError("OWNER_IDS must contain at least one owner id")
        try:
            owner_ids = frozenset(int(item) for item in raw)
        except ValueError as exc:
            raise ValueError("OWNER_IDS must be a comma-separated list of integers") from exc
        if any(owner_id <= 0 for owner_id in owner_ids):
            raise ValueError("OWNER_IDS entries must be positive integers")
        return owner_ids

    @field_validator("TELEGRAM_BOT_API_URL", mode="before")
    @classmethod
    def _normalize_bot_api_url(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip().rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("TELEGRAM_BOT_API_URL must start with http:// or https://")
        return normalized

    @field_validator("SOCKS5_PROXY_URL", mode="before")
    @classmethod
    def _validate_socks5_url(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        if not normalized.startswith(("socks5://", "socks5h://")):
            raise ValueError("SOCKS5_PROXY_URL must use the socks5:// or socks5h:// scheme")
        return normalized

    @field_validator("TELEGRAM_SESSION_PATH")
    @classmethod
    def _normalize_session_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute():
            resolved = path.resolve()
            if not resolved.is_relative_to(RUNTIME_SESSION_DIR.resolve()):
                raise ValueError("TELEGRAM_SESSION_PATH must stay under runtime/telethon/")
            return str(_with_session_suffix(resolved))
        # A relative value is only a hint: the session must never land outside runtime/.
        return str(_with_session_suffix(RUNTIME_SESSION_DIR / path.name))

    @field_validator("DATABASE_URL")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        if not value.startswith(DATABASE_URL_PREFIX) or value == DATABASE_URL_PREFIX:
            raise ValueError("DATABASE_URL must use the sqlite+aiosqlite:/// scheme")
        return value

    @model_validator(mode="after")
    def _validate_mtproxy_triplet(self) -> Settings:
        provided = [getattr(self, name) is not None for name in self._MTPROXY_FIELDS]
        if any(provided) and not all(provided):
            raise ValueError(
                "MTProxy configuration is all-or-nothing: TELEGRAM_MTPROXY_SERVER, "
                "TELEGRAM_MTPROXY_PORT and TELEGRAM_MTPROXY_SECRET must be set together"
            )
        return self

    def telethon_transport(self) -> TelethonTransport:
        if (
            self.TELEGRAM_MTPROXY_SERVER is not None
            and self.TELEGRAM_MTPROXY_PORT is not None
            and self.TELEGRAM_MTPROXY_SECRET is not None
        ):
            return MtProxyTransport(
                host=self.TELEGRAM_MTPROXY_SERVER,
                port=self.TELEGRAM_MTPROXY_PORT,
                secret=self.TELEGRAM_MTPROXY_SECRET.get_secret_value(),
            )
        if self.SOCKS5_PROXY_URL is not None:
            return Socks5Transport(url=self.SOCKS5_PROXY_URL)
        return DirectTransport()

    def bot_api_proxy_url(self) -> str | None:
        if self.TELEGRAM_BOT_API_URL is not None:
            host = urlsplit(self.TELEGRAM_BOT_API_URL).hostname
            if host is not None and host.lower() in LOOPBACK_HOSTS:
                return None
        return self.SOCKS5_PROXY_URL

    def log_file(self) -> Path:
        return self.LOG_DIR / LOG_FILE_NAME


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.model_validate({})
