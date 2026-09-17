"""Contract: every I/O-backed application port method must be awaitable.

All real adapters are async (SQLAlchemy ``AsyncSession``, aiogram, Telethon,
VKBottle), so a synchronous ``def`` declaration would be rejected by
basedpyright when the real adapter is passed to a use case. ``@runtime_checkable``
Protocols only verify method-name presence, which is why this defect survived
the structural fake tests. ``ReadinessPort`` is the deliberate exception: it is
an in-memory gate with no I/O.
"""

import inspect

import pytest

from vk_topic_bridge.application.ports.readiness import ReadinessPort
from vk_topic_bridge.application.ports.repositories import (
    BridgeSettingsRepository,
    DeliveryRepository,
    TelegramTopicsRepository,
    VkAliasRepository,
)
from vk_topic_bridge.application.ports.telegram import (
    TelegramAdminPort,
    TelegramPublisher,
    TelethonPort,
)
from vk_topic_bridge.application.ports.vk import VkGateway

ASYNC_PORTS: tuple[type[object], ...] = (
    BridgeSettingsRepository,
    TelegramTopicsRepository,
    VkAliasRepository,
    DeliveryRepository,
    TelegramPublisher,
    TelegramAdminPort,
    TelethonPort,
    VkGateway,
)


def _public_sync_methods(protocol: type[object]) -> list[str]:
    return [
        name
        for name, method in inspect.getmembers(protocol, predicate=inspect.isfunction)
        if not name.startswith("_") and not inspect.iscoroutinefunction(method)
    ]


@pytest.mark.parametrize("protocol", ASYNC_PORTS, ids=[item.__qualname__ for item in ASYNC_PORTS])
def test_every_public_port_method_is_async(protocol: type[object]) -> None:
    sync_methods = _public_sync_methods(protocol)

    assert sync_methods == [], f"{protocol.__qualname__} declares sync methods: {sync_methods}"


def test_readiness_port_stays_sync_because_it_is_in_memory() -> None:
    methods = [
        name
        for name, _ in inspect.getmembers(ReadinessPort, predicate=inspect.isfunction)
        if not name.startswith("_")
    ]

    assert methods, "ReadinessPort must expose public methods"
    assert all(not inspect.iscoroutinefunction(getattr(ReadinessPort, name)) for name in methods), (
        "ReadinessPort is an in-memory gate and must stay synchronous"
    )
