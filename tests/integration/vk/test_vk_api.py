"""Fake-API tests for the VK gateway (plan §9, docs 03 §9-10, docs 05 §14).

No network is used: ``FakeVkApi`` records calls and replays canned VK responses,
including real ``vkbottle.VKAPIError`` instances for error-classification coverage.
"""

import importlib
import json
from collections.abc import Mapping
from types import ModuleType

import pytest
from vkbottle import VKAPIError
from vkbottle.tools.keyboard import Keyboard, KeyboardButtonColor
from vkbottle.tools.keyboard.action import Callback

from config import Settings
from vk_topic_bridge.domain.value_objects import Author, SourceWallPost

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


def _full_message_with_photo() -> dict[str, object]:
    message = _full_message()
    message["attachments"] = [
        {
            "type": "photo",
            "photo": {
                "owner_id": -1,
                "id": 11,
                "access_key": "PHOTO_KEY",
                "sizes": [
                    {
                        "type": "w",
                        "url": "https://vk.example/photo.jpg",
                        "width": 1920,
                        "height": 1080,
                    }
                ],
            },
        }
    ]
    return message


WALL_POST_ID = 77


def _wall_attachment(owner_id: int = -GROUP_ID, post_id: int = WALL_POST_ID) -> dict[str, object]:
    return {
        "type": "wall",
        "wall": {"owner_id": owner_id, "id": post_id, "access_key": "wall-key"},
    }


def _wall_post(owner_id: int = -GROUP_ID, post_id: int = WALL_POST_ID) -> dict[str, object]:
    return {
        "owner_id": owner_id,
        "id": post_id,
        "from_id": owner_id,
        "text": "оригинальный пост",
        "attachments": [
            {
                "type": "photo",
                "photo": {
                    "owner_id": owner_id,
                    "id": 12,
                    "sizes": [{"type": "z", "url": "https://vk.example/wall.jpg"}],
                },
            },
            {
                "type": "doc",
                "doc": {
                    "owner_id": owner_id,
                    "id": 13,
                    "title": "report.pdf",
                    "url": "https://vk.example/report.pdf",
                },
            },
        ],
    }


def _community_groups() -> dict[str, object]:
    return _ok({"groups": [{"id": GROUP_ID, "name": "Бот", "screen_name": "bot"}]})


def _keyboard_json(*, inline: bool, row_sizes: tuple[int, ...]) -> str:
    buttons: list[list[dict[str, object]]] = []
    for row_index, button_count in enumerate(row_sizes, start=1):
        row: list[dict[str, object]] = []
        for button_index in range(1, button_count + 1):
            action: dict[str, object] = {
                "type": "callback" if inline else "text",
                "label": f"{row_index}-{button_index}",
            }
            if inline:
                action["payload"] = {"action": "topic"}
            row.append({"action": action, "color": "positive"})
        buttons.append(row)
    return json.dumps({"one_time": False, "inline": inline, "buttons": buttons}, ensure_ascii=False)


def _unicode_inline_keyboard_json() -> str:
    keyboard = Keyboard(inline=True)
    keyboard.add(
        Callback("Новости", {"action": "cancel"}),
        color=KeyboardButtonColor.SECONDARY,
    )
    keyboard.row()
    return keyboard.get_json()


class FakeVkApi:
    """Minimal stand-in for ``vkbottle.API``: records calls and replays responses."""

    def __init__(
        self,
        responses: Mapping[str, dict[str, object]] | None = None,
        errors: Mapping[str, int] | None = None,
        transport_errors: Mapping[str, Exception] | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self._responses = dict(responses or {})
        self._errors = dict(errors or {})
        self._transport_errors = dict(transport_errors or {})

    async def request(
        self, method: str, data: dict[str, object], version: str | None = None
    ) -> dict[str, object]:
        _ = version
        self.calls.append((method, dict(data)))
        if method in self._transport_errors:
            raise self._transport_errors[method]
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


async def test_edit_user_message_sends_cmid_and_removes_keyboard() -> None:
    module = _api_module()
    fake = FakeVkApi({"messages.edit": _ok(1)})
    gateway = module.VkApiGateway(fake, _settings())

    await gateway.edit_user_message(PEER_ID, CMID, "Отмена", '{"buttons": []}')

    assert fake.params_for("messages.edit") == [
        {
            "peer_id": PEER_ID,
            "cmid": CMID,
            "message": "Отмена",
            "keyboard": '{"buttons": []}',
        }
    ]


async def test_send_user_message_preserves_valid_inline_keyboard_json() -> None:
    module = _api_module()
    fake = FakeVkApi({"messages.send": _ok(1234)})
    gateway = module.VkApiGateway(fake, _settings())
    keyboard_json = _unicode_inline_keyboard_json()

    await gateway.send_user_message(PEER_ID, "Меню", keyboard_json)

    assert fake.params_for("messages.send")[0]["keyboard"] == keyboard_json


async def test_edit_user_message_preserves_valid_inline_keyboard_json() -> None:
    module = _api_module()
    fake = FakeVkApi({"messages.edit": _ok(1)})
    gateway = module.VkApiGateway(fake, _settings())
    keyboard_json = _unicode_inline_keyboard_json()

    await gateway.edit_user_message(PEER_ID, CMID, "Меню", keyboard_json)

    assert fake.params_for("messages.edit")[0]["keyboard"] == keyboard_json


async def test_send_user_message_fits_inline_row_limit() -> None:
    module = _api_module()
    fake = FakeVkApi({"messages.send": _ok(1234)})
    gateway = module.VkApiGateway(fake, _settings())

    await gateway.send_user_message(
        PEER_ID,
        "Меню",
        _keyboard_json(inline=True, row_sizes=(1, 1, 1, 1, 1, 1, 1, 1)),
    )

    keyboard_json = fake.params_for("messages.send")[0]["keyboard"]
    assert isinstance(keyboard_json, str)
    keyboard = json.loads(keyboard_json)
    assert keyboard["inline"] is True
    assert [len(row) for row in keyboard["buttons"]] == [1, 1, 1, 1, 1]
    assert [button["action"]["label"] for row in keyboard["buttons"] for button in row] == [
        "1-1",
        "2-1",
        "3-1",
        "4-1",
        "5-1",
    ]


async def test_edit_user_message_fits_inline_button_limit() -> None:
    module = _api_module()
    fake = FakeVkApi({"messages.edit": _ok(1)})
    gateway = module.VkApiGateway(fake, _settings())

    await gateway.edit_user_message(
        PEER_ID,
        CMID,
        "Меню",
        _keyboard_json(inline=True, row_sizes=(5, 5, 5)),
    )

    keyboard_json = fake.params_for("messages.edit")[0]["keyboard"]
    assert isinstance(keyboard_json, str)
    keyboard = json.loads(keyboard_json)
    assert sum(len(row) for row in keyboard["buttons"]) == 10
    assert len(keyboard["buttons"]) == 2


async def test_send_user_message_fits_regular_row_limit() -> None:
    module = _api_module()
    fake = FakeVkApi({"messages.send": _ok(1234)})
    gateway = module.VkApiGateway(fake, _settings())

    await gateway.send_user_message(
        PEER_ID,
        "Меню",
        _keyboard_json(inline=False, row_sizes=(1,) * 12),
    )

    keyboard_json = fake.params_for("messages.send")[0]["keyboard"]
    assert isinstance(keyboard_json, str)
    keyboard = json.loads(keyboard_json)
    assert len(keyboard["buttons"]) == 10
    assert sum(len(row) for row in keyboard["buttons"]) == 10


async def test_edit_user_message_fits_regular_button_limit() -> None:
    module = _api_module()
    fake = FakeVkApi({"messages.edit": _ok(1)})
    gateway = module.VkApiGateway(fake, _settings())

    await gateway.edit_user_message(
        PEER_ID,
        CMID,
        "Меню",
        _keyboard_json(inline=False, row_sizes=(5,) * 10),
    )

    keyboard_json = fake.params_for("messages.edit")[0]["keyboard"]
    assert isinstance(keyboard_json, str)
    keyboard = json.loads(keyboard_json)
    assert len(keyboard["buttons"]) == 8
    assert sum(len(row) for row in keyboard["buttons"]) == 40


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


async def test_get_author_for_community_uses_group_profile_lookup() -> None:
    module = _api_module()
    fake = FakeVkApi(
        {
            "groups.getById": _ok(
                {"groups": [{"id": 123, "name": "Сообщество", "screen_name": "club123"}]}
            )
        }
    )
    gateway = module.VkApiGateway(fake, _settings())

    author = await gateway.get_author(-123)

    assert author == Author(
        user_id=-123,
        first_name="Сообщество",
        last_name="",
        screen_name="club123",
    )
    assert author.profile_url == "https://vk.com/club123"
    assert fake.params_for("groups.getById") == [{"group_ids": [123]}]


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


async def test_normalize_event_resolves_wall_repost_via_user_token() -> None:
    module = _api_module()
    user = FakeVkApi({"wall.getById": _ok({"items": [_wall_post()]})})
    group = FakeVkApi({"groups.getById": _community_groups()})
    gateway = module.VkApiGateway(group, _settings(), user_api=user)
    message = _full_message()
    message["text"] = "@all подпись пользователя"
    message["attachments"] = [
        _wall_attachment(),
        {"type": "photo", "photo": {"owner_id": -GROUP_ID, "id": 99}},
    ]

    source = await gateway.normalize_event(
        {"type": "message_new", "group_id": GROUP_ID, "object": message}, _author()
    )

    assert source.text == "@all подпись пользователя"
    assert source.has_all is True
    assert isinstance(source.wall_post, SourceWallPost)
    assert source.wall_post.text == "оригинальный пост"
    assert source.wall_post.url == "https://vk.com/wall-42_77"
    assert source.wall_link is None
    assert [item.kind.value for item in source.attachments] == ["photo", "photo", "document"]
    assert user.params_for("wall.getById") == [{"posts": "-42_77"}]
    assert group.params_for("wall.getById") == []


async def test_normalize_event_wall_repost_without_user_token_uses_link_fallback() -> None:
    module = _api_module()
    group = FakeVkApi()
    gateway = module.VkApiGateway(group, _settings())
    message = _full_message()
    message["text"] = "#важное"
    message["attachments"] = [_wall_attachment()]

    source = await gateway.normalize_event(
        {"type": "message_new", "group_id": GROUP_ID, "object": message}, _author()
    )

    assert source.wall_post is None
    assert source.wall_link == "https://vk.com/wall-42_77"
    assert source.attachments == ()
    assert group.calls == []


async def test_normalize_event_wall_repost_vk_error_uses_link_fallback() -> None:
    module = _api_module()
    user = FakeVkApi(errors={"wall.getById": 27})
    group = FakeVkApi()
    gateway = module.VkApiGateway(group, _settings(), user_api=user)
    message = _full_message()
    message["attachments"] = [_wall_attachment()]

    source = await gateway.normalize_event(
        {"type": "message_new", "group_id": GROUP_ID, "object": message}, _author()
    )

    assert source.wall_post is None
    assert source.wall_link == "https://vk.com/wall-42_77"
    assert user.params_for("wall.getById") == [{"posts": "-42_77"}]


async def test_normalize_event_wall_repost_transport_error_uses_link_fallback() -> None:
    module = _api_module()
    user = FakeVkApi(transport_errors={"wall.getById": ConnectionError("network down")})
    group = FakeVkApi()
    gateway = module.VkApiGateway(group, _settings(), user_api=user)
    message = _full_message()
    message["attachments"] = [_wall_attachment()]

    source = await gateway.normalize_event(
        {"type": "message_new", "group_id": GROUP_ID, "object": message}, _author()
    )

    assert source.wall_post is None
    assert source.wall_link == "https://vk.com/wall-42_77"


async def test_normalize_event_does_not_expand_wall_inside_forwarded_message() -> None:
    module = _api_module()
    fake = FakeVkApi()
    gateway = module.VkApiGateway(fake, _settings())
    message = _full_message()
    message["text"] = "@all только сообщение пользователя"
    message["fwd_messages"] = [
        {"text": "пост внутри обычной пересылки", "attachments": [{"type": "wall"}]}
    ]

    source = await gateway.normalize_event(
        {"type": "message_new", "group_id": GROUP_ID, "object": message}, _author()
    )

    assert source.wall_post is None
    assert source.text == "@all только сообщение пользователя"
    assert fake.calls == []


async def test_normalize_event_foreign_wall_repost_uses_link_fallback_without_fetch() -> None:
    module = _api_module()
    user = FakeVkApi()
    group = FakeVkApi()
    gateway = module.VkApiGateway(group, _settings(), user_api=user)
    message = _full_message()
    message["attachments"] = [_wall_attachment(owner_id=-999)]

    source = await gateway.normalize_event(
        {"type": "message_new", "group_id": GROUP_ID, "object": message}, _author()
    )

    assert source.wall_post is None
    assert source.wall_link == "https://vk.com/wall-999_77"
    assert user.calls == []


async def test_normalize_event_unavailable_wall_post_uses_link_fallback() -> None:
    module = _api_module()
    user = FakeVkApi({"wall.getById": _ok({"items": []})})
    group = FakeVkApi()
    gateway = module.VkApiGateway(group, _settings(), user_api=user)
    message = _full_message()
    message["attachments"] = [_wall_attachment()]

    source = await gateway.normalize_event(
        {"type": "message_new", "group_id": GROUP_ID, "object": message}, _author()
    )

    assert source.wall_post is None
    assert source.wall_link == "https://vk.com/wall-42_77"


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


async def test_cropped_wall_repost_is_resolved_after_full_message_fetch() -> None:
    module = _api_module()
    full = _full_message()
    full["attachments"] = [_wall_attachment()]
    user = FakeVkApi({"wall.getById": _ok({"items": [_wall_post()]})})
    group = FakeVkApi(
        {
            "groups.getById": _community_groups(),
            "messages.getByConversationMessageId": _ok({"items": [full]}),
            "users.get": _ok(
                [{"id": 123, "first_name": "Иван", "last_name": "Иванов", "screen_name": "ivan"}]
            ),
        }
    )
    gateway = module.VkApiGateway(group, _settings(), user_api=user)

    source = await gateway.normalize_event(
        {"type": "message_new", "group_id": GROUP_ID, "object": _cropped_object()}, _author()
    )

    assert source.wall_post is not None
    assert source.wall_post.text == "оригинальный пост"
    assert source.wall_link is None
    assert user.params_for("wall.getById") == [{"posts": "-42_77"}]


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


async def test_cropped_full_message_preserves_media_contract() -> None:
    module = _api_module()
    fake = FakeVkApi(
        {
            "groups.getById": _ok({"groups": [{"id": GROUP_ID}]}),
            "messages.getByConversationMessageId": _ok({"items": [_full_message_with_photo()]}),
            "users.get": _ok(
                [{"id": 123, "first_name": "И", "last_name": "И", "screen_name": None}]
            ),
        }
    )
    gateway = module.VkApiGateway(fake, _settings())

    source = await gateway.get_full_message(PEER_ID, CMID)

    attachment = source.attachments[0]
    assert attachment.source_ref == "-1_11_PHOTO_KEY"
    assert attachment.access_key == "PHOTO_KEY"
    assert attachment.variants[0].url == "https://vk.example/photo.jpg"


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


@pytest.mark.parametrize("code", [5, 15, 100, 911])
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
