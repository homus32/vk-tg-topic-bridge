"""Progress-honesty guard: deferred user stories are not claimed by this slice.

Stage 2-6 ships a vertical slice only. Attachments (US-10-US-12), wall posts
(US-14), VK manual forwarding and aliases (US-15-US-19), the full Telegram admin
UI (US-20-US-21) and General fallback (US-22) belong to later roadmap stages. The
guard pins the deferred set exactly and fails if any acceptance test file in this
directory starts claiming one of those stories.
"""

from __future__ import annotations

from pathlib import Path

from tests.acceptance.deferred import DEFERRED_USER_STORIES

ACCEPTANCE_DIR = Path(__file__).resolve().parent

EXPECTED_DEFERRED = frozenset(
    {
        "US-10",
        "US-11",
        "US-12",
        "US-14",
        "US-15",
        "US-16",
        "US-17",
        "US-18",
        "US-19",
        "US-20",
        "US-21",
        "US-22",
    }
)

IN_SCOPE_STORIES = frozenset(
    {
        "US-01",
        "US-02",
        "US-03",
        "US-04",
        "US-05",
        "US-06",
        "US-07",
        "US-08",
        "US-09",
        "US-13",
        "US-23",
        "US-24",
        "US-25",
        "US-26",
    }
)


def test_deferred_user_stories_are_not_claimed() -> None:
    assert DEFERRED_USER_STORIES == EXPECTED_DEFERRED
    assert not (DEFERRED_USER_STORIES & IN_SCOPE_STORIES)


def test_deferred_stories_have_no_acceptance_test_file() -> None:
    file_names = {path.name for path in ACCEPTANCE_DIR.glob("test_us*.py")}

    for story in sorted(DEFERRED_USER_STORIES):
        number = story.split("-")[1]
        claimants = sorted(name for name in file_names if name.startswith(f"test_us{number}_"))
        assert claimants == [], f"{story} is deferred to a later stage but claimed by {claimants}"


def test_every_in_scope_story_has_an_acceptance_test_file() -> None:
    file_names = {path.name for path in ACCEPTANCE_DIR.glob("test_us*.py")}

    for story in sorted(IN_SCOPE_STORIES):
        number = story.split("-")[1]
        claimants = sorted(name for name in file_names if name.startswith(f"test_us{number}_"))
        assert claimants, f"{story} is in scope for Stage 2-6 but has no acceptance test file"
