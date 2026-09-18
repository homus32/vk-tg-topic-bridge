"""VK presentation layer: per-user ephemeral FSM for Help, aliases, manual forwarding.

This package fans UI events out of the raw Long Poll consumer; automatic forwarding
stays in its existing application path. State is keyed by VK ``from_id`` (ephemeral,
in-memory, may be lost on restart — never persisted as business configuration).
"""

from __future__ import annotations
