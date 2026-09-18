"""Anti-omission guard: every product user story has at least one acceptance file.

Replaces the Stage 2-6 deferred-stories guard: US-10..US-22 are now in scope, so the
guard's job changed from "these stories must not be claimed" to "no story may be
unclaimed". It also keeps the acceptance acceptance-suite honest about ids.
"""

from __future__ import annotations

from pathlib import Path

ACCEPTANCE_DIR = Path(__file__).resolve().parent

ALL_USER_STORIES = frozenset(f"US-{number:02d}" for number in range(1, 28))


def _claimed_stories() -> dict[str, list[str]]:
    claims: dict[str, list[str]] = {}
    for path in sorted(ACCEPTANCE_DIR.glob("test_us*.py")):
        number = path.name.split("_", 2)[1].removeprefix("us")
        story = f"US-{int(number):02d}"
        claims.setdefault(story, []).append(path.name)
    return claims


def test_every_user_story_has_an_acceptance_test_file() -> None:
    claims = _claimed_stories()

    missing = sorted(ALL_USER_STORIES - set(claims))
    assert missing == [], f"user stories without acceptance coverage: {missing}"


def test_no_acceptance_file_claims_an_unknown_story() -> None:
    claims = _claimed_stories()

    unknown = sorted(set(claims) - ALL_USER_STORIES)
    assert unknown == [], f"acceptance files claim unknown stories: {unknown}"


def test_in_scope_stories_formerly_deferred_are_covered() -> None:
    formerly_deferred = {
        f"US-{number:02d}" for number in (10, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22)
    }
    claims = _claimed_stories()

    missing = sorted(story for story in formerly_deferred if story not in claims)
    assert missing == [], f"formerly deferred stories are still unclaimed: {missing}"
