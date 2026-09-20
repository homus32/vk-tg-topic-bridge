"""Fake-API tests for the VK gateway (plan §9, docs 03 §9-10, docs 05 §14).

No network is used: ``FakeVkApi`` records calls and replays canned VK responses,
including real ``vkbottle.VKAPIError`` instances for error-classification coverage.
"""

import importlib
from collections.abc import Mapping
from types import ModuleType

import pytest
from vkbottle import VKAPIError

from config import Settings
from vk_topic_bridge.domain.value_objects import Author

GROUP_ID = 42
PEER_ID = 2000000001
CMID = 789


def _api_module() -> ModuleType:
    return importlib.import_module("vk_topic_bridge.infrastructure.vk.api")


def _settings(**overrides: object) -> Settings:
    return Settings.model_validate(overrides)


def _ok(response: object) -> dict[str, object]:
    return {"response": response}


def _author() -> Author:
    return Author(user_id=123, first_name="Иван", last_name="Иванов", screen_name="ivan")


def _cropped_object() -> dict[str, object]:
    return {
        "id": 456,
        "from_id": 123,
        "peer_id": PEER_ID,
        "conversation_message_id": CMID,
        "text": "short",
        "attachments": [],
        "is_cropped": 1,
    }


def _full_message() -> dict[str, object]:
    return {
        "id": 456,
        "from_id": 123,
        "peer_id": PEER_ID,
        "conversation_message_id": CMID,
        "text": "@all полный текст #извк",
        "attachments": [],
        "is_cropped": 0,
    }


class FakeVkApi:
    """Minimal stand-in for ``vkbottle.API``: records calls and replays responses."""

    def __init__(
        self,
        responses: Mapping[str, dict[str, object]] | None = None,
        errors: Mapping[str, int] | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self._responses = dict(responses or {})
        self._errors = dict(errors or {})

    async def request(
        self, method: str, data: dict[str, object], version: str | None = None
    ) -> dict[str, object]:
        self.calls.append((method, dict(data)))
        if method in self._errors:
            code = self._errors[method]
            raise VKAPIError[code](error_msg=f"vk error {code}")
        try:
            return self._responses[method]
        except KeyError:
            msg = f"unexpected VK method {method}"
            raise AssertionError(msg) from None

    def params_for(self, method: str) -> list[dict[str, object]]:
        return [params for called, params in self.calls if called == method]


# --- community identity -------------------------------------------------------


async def test_get_community_id_derives_from_token() -> None:
    module = _api_module()
    fake = FakeVkApi({"groups.getById": _ok({"groups": [{"id": GROUP_ID}]})})
    gateway = module.VkApiGateway(fake, _settings())

    assert await gateway.get_community_id() == GROUP_ID
    assert fake.calls == [("groups.getById", {})]


async def test_get_community_id_accepts_matching_override() -> None:
    module = _api_module()
    fake = FakeVkApi({"groups.getById": _ok({"groups": [{"id": GROUP_ID}]})})
    gateway = module.VkApiGateway(fake, _settings(VK_GROUP_ID=GROUP_ID))

    assert await gateway.get_community_id() == GROUP_ID


async def test_get_community_id_rejects_mismatched_override() -> None:
    module = _api_module()
    fake = FakeVkApi({"groups.getById": _ok({"groups": [{"id": GROUP_ID}]})})
    gateway = module.VkApiGateway(fake, _settings(VK_GROUP_ID=7))

    with pytest.raises(module.VkFatalError, match="VK_GROUP_ID"):
        await gateway.get_community_id()


async def test_get_community_id_empty_groups_is_fatal() -> None:
    module = _api_module()
    fake = FakeVkApi({"groups.getById": _ok({"groups": []})})
    gateway = module.VkApiGateway(fake, _settings())

    with pytest.raises(module.VkFatalError):
        await gateway.get_community_id()


# --- Long Poll handshake ------------------------------------------------------


async def test_check_long_poll_shapes_info() -> None:
    module = _api_module()
    fake = FakeVkApi(
        {
            "groups.getById": _ok({"groups": [{"id": GROUP_ID}]}),
            "groups.getLongPollSettings": _ok({"is_enabled": True, "events": {"wall_post_new": 1}}),
            "groups.getLongPollServer": _ok(
                {"server": "https://lp.vk.com/wh42", "key": "abc", "ts": "99"}
            ),
        }
    )
    gateway = module.VkApiGateway(fake, _settings())

    info = await gateway.check_long_poll()

    assert info.server == "https://lp.vk.com/wh42"
    assert info.key == "abc"
    assert info.ts == "99"
    assert info.enabled is True
    assert info.wall_post_new_enabled is True
    assert fake.params_for("groups.getLongPollSettings") == [{"group_id": GROUP_ID}]
    assert fake.params_for("groups.getLongPollServer") == [{"group_id": GROUP_ID}]


async def test_check_long_poll_reports_disabled() -> None:
    module = _api_module()
    fake = FakeVkApi(
        {
            "groups.getById": _ok({"groups": [{"id": GROUP_ID}]}),
            "groups.getLongPollSettings": _ok(
                {"is_enabled": False, "events": {"wall_post_new": 0}}
            ),
            "groups.getLongPollServer": _ok({"server": "s", "key": "k", "ts": 1}),
        }
    )
    gateway = module.VkApiGateway(fake, _settings())

    info = await gateway.check_long_poll()

    assert info.enabled is False
    assert info.ts == "1"


async def test_check_long_poll_reports_wall_event_disabled() -> None:
    module = _api_module()
    fake = FakeVkApi(
        {
            "groups.getById": _ok({"groups": [{"id": GROUP_ID}]}),
            "groups.getLongPollSettings": _ok({"is_enabled": True, "events": {"wall_post_new": 0}}),
            "groups.getLongPollServer": _ok({"server": "s", "key": "k", "ts": 1}),
        }
    )
    gateway = module.VkApiGateway(fake, _settings())

    info = await gateway.check_long_poll()

    assert info.enabled is True
    assert info.wall_post_new_enabled is False


# --- author ------------------------------------------------------------------


async def test_get_author_reads_profile() -> None:
    module = _api_module()
    fake = FakeVkApi(
        {
            "users.get": _ok(
                [{"id": 123, "first_name": "Иван", "last_name": "Иванов", "screen_name": "ivan"}]
            )
        }
    )
    gateway = module.VkApiGateway(fake, _settings())

    author = await gateway.get_author(123)

    assert author == _author()
    assert fake.params_for("users.get") == [{"user_ids": [123]}]


async def test_get_author_tolerates_missing_screen_name() -> None:
    module = _api_module()
    fake = FakeVkApi({"users.get": _ok([{"id": 5, "first_name": "A", "last_name": "B"}])})
    gateway = module.VkApiGateway(fake, _settings())

    author = await gateway.get_author(5)

    assert author.screen_name is None
    assert author.profile_url == "https://vk.com/id5"


# --- cropped completion / normalization ---------------------------------------


async def test_normalize_event_non_cropped_maps_object_directly() -> None:
    module = _api_module()
    fake = FakeVkApi()
    gateway = module.VkApiGateway(fake, _settings())
    raw_event: dict[str, object] = {
        "type": "message_new",
        "group_id": GROUP_ID,
        "event_id": "e1",
        "object": _full_message(),
    }

    source = await gateway.normalize_event(raw_event, _author())

    assert source.source_key == f"{GROUP_ID}:{PEER_ID}:{CMID}"
    assert source.text == "@all полный текст #извк"
    assert source.has_all is True
    assert fake.calls == []


async def test_normalize_event_maps_nested_message_object() -> None:
    module = _api_module()
    fake = FakeVkApi()
    gateway = module.VkApiGateway(fake, _settings())
    raw_event: dict[str, object] = {
        "type": "message_new",
        "group_id": GROUP_ID,
        "event_id": "e1",
        "object": {"message": _full_message(), "client_info": {}},
    }

    source = await gateway.normalize_event(raw_event, _author())

    assert source.source_key == f"{GROUP_ID}:{PEER_ID}:{CMID}"
    assert source.text == "@all полный текст #извк"


async def test_cropped_event_triggers_full_message_fetch() -> None:
    module = _api_module()
    fake = FakeVkApi(
        {
            "groups.getById": _ok({"groups": [{"id": GROUP_ID}]}),
            "messages.getByConversationMessageId": _ok({"items": [_full_message()]}),
            "users.get": _ok(
                [{"id": 123, "first_name": "Иван", "last_name": "Иванов", "screen_name": "ivan"}]
            ),
        }
    )
    gateway = module.VkApiGateway(fake, _settings())
    raw_event: dict[str, object] = {
        "type": "message_new",
        "group_id": GROUP_ID,
        "event_id": "e1",
        "object": _cropped_object(),
    }

    source = await gateway.normalize_event(raw_event, _author())

    assert source.text == "@all полный текст #извк"
    assert source.source_key == f"{GROUP_ID}:{PEER_ID}:{CMID}"
    assert fake.params_for("messages.getByConversationMessageId") == [
        {"peer_id": PEER_ID, "conversation_message_ids": [CMID]}
    ]
    # source_key is derived from conversation_message_id, never from message.id/ts.
    assert "456" not in source.source_key


async def test_get_full_message_maps_by_conversation_message_id() -> None:
    module = _api_module()
    fake = FakeVkApi(
        {
            "groups.getById": _ok({"groups": [{"id": GROUP_ID}]}),
            "messages.getByConversationMessageId": _ok({"items": [_full_message()]}),
            "users.get": _ok(
                [{"id": 123, "first_name": "И", "last_name": "И", "screen_name": None}]
            ),
        }
    )
    gateway = module.VkApiGateway(fake, _settings())

    source = await gateway.get_full_message(PEER_ID, CMID)

    assert source.conversation_message_id == CMID
    assert source.source_key == f"{GROUP_ID}:{PEER_ID}:{CMID}"


# --- reaction ----------------------------------------------------------------


async def test_set_reaction_sends_peer_cmid_and_reaction_id() -> None:
    module = _api_module()
    fake = FakeVkApi({"messages.sendReaction": _ok(1)})
    gateway = module.VkApiGateway(fake, _settings())

    assert await gateway.set_reaction(PEER_ID, CMID) is None
    assert fake.calls == [
        (
            "messages.sendReaction",
            {"peer_id": PEER_ID, "cmid": CMID, "reaction_id": module.LIKE_REACTION_ID},
        )
    ]


# --- error classification -----------------------------------------------------


@pytest.mark.parametrize("code", [5, 15, 100])
async def test_fatal_vk_codes_are_classified(code: int) -> None:
    module = _api_module()
    fake = FakeVkApi(errors={"groups.getById": code})
    gateway = module.VkApiGateway(fake, _settings())

    with pytest.raises(module.VkFatalError) as exc_info:
        await gateway.get_community_id()

    assert exc_info.value.code == code


@pytest.mark.parametrize("code", [6, 10])
async def test_retryable_vk_codes_are_classified(code: int) -> None:
    module = _api_module()
    fake = FakeVkApi(errors={"groups.getById": code})
    gateway = module.VkApiGateway(fake, _settings())

    with pytest.raises(module.VkRetryableError) as exc_info:
        await gateway.get_community_id()

    assert exc_info.value.code == code


def test_gateway_satisfies_vk_gateway_protocol() -> None:
    module = _api_module()
    from vk_topic_bridge.application.ports.vk import VkGateway

    assert isinstance(module.VkApiGateway(FakeVkApi(), _settings()), VkGateway)
