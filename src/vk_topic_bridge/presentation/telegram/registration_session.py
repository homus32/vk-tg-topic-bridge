from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RegistrationCoordinator:
    active_owner_id: int | None = None
    group_chat_id: int | None = None

    def acquire(self, owner_id: int) -> bool:
        if self.active_owner_id is None:
            self.active_owner_id = owner_id
            return True
        return self.active_owner_id == owner_id

    def owns(self, owner_id: int) -> bool:
        return self.active_owner_id == owner_id

    def bind_group(self, chat_id: int) -> None:
        self.group_chat_id = chat_id

    def release(self, owner_id: int) -> int | None:
        if not self.owns(owner_id):
            return None
        group_chat_id = self.group_chat_id
        self.active_owner_id = None
        self.group_chat_id = None
        return group_chat_id
