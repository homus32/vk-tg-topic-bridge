"""Bootstrap smoke test: runtime dependencies and the package import under Python 3.14."""

import importlib

import pytest

RUNTIME_MODULES = [
    "vk_topic_bridge",
    "aiogram",
    "vkbottle",
    "telethon",
    "sqlalchemy",
    "sqlalchemy.ext.asyncio",
    "aiosqlite",
    "alembic",
    "pydantic_settings",
    "loguru",
    "aiohttp",
    "aiohttp_socks",
    "python_socks",
]


@pytest.mark.parametrize("module_name", RUNTIME_MODULES)
def test_runtime_module_imports(module_name: str) -> None:
    assert importlib.import_module(module_name)
