"""Unit tests for the alias policy: normalization, reserved names and uniqueness."""

import pytest

from vk_topic_bridge.domain.errors import InvalidAlias
from vk_topic_bridge.domain.policies import alias_policy


def test_normalize_lowercases_and_strips() -> None:
    assert alias_policy.normalize_alias("  Важное  ") == "важное"


def test_normalize_keeps_digits() -> None:
    assert alias_policy.normalize_alias("1") == "1"


@pytest.mark.parametrize("raw", ["", "   ", "\t\n"])
def test_normalize_rejects_blank_alias(raw: str) -> None:
    with pytest.raises(InvalidAlias):
        alias_policy.normalize_alias(raw)


@pytest.mark.parametrize("raw", ["важ ное", "два\tслова", "a b"])
def test_normalize_rejects_inner_whitespace(raw: str) -> None:
    with pytest.raises(InvalidAlias):
        alias_policy.normalize_alias(raw)


@pytest.mark.parametrize("raw", ["Помощь", "help", "ДОБАВИТЬ", " отмена "])
def test_reserved_commands_are_rejected(raw: str) -> None:
    with pytest.raises(InvalidAlias):
        alias_policy.ensure_alias_available(raw, user_aliases=[])


def test_existing_alias_of_the_same_user_is_rejected_case_insensitively() -> None:
    with pytest.raises(InvalidAlias):
        alias_policy.ensure_alias_available("Важное", user_aliases=["важное"])


def test_new_alias_is_returned_normalized() -> None:
    assert alias_policy.ensure_alias_available(" Новое ", user_aliases=["важное"]) == "новое"


def test_other_aliases_of_the_user_do_not_block_a_new_one() -> None:
    assert alias_policy.ensure_alias_available("важное", user_aliases=["другое"]) == "важное"


def test_uniqueness_is_scoped_to_one_user_list() -> None:
    # another user's alias is simply absent from the passed list
    assert alias_policy.ensure_alias_available("1", user_aliases=[]) == "1"
