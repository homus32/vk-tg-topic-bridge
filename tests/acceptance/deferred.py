"""User stories that Stage 2-6 must not claim.

Every id here belongs to a later roadmap stage: US-10-US-12 and US-14 to Stage 9
(attachments, 50 MB limit, unsupported media, wall publication), US-15-US-19 to
Stage 8 (VK manual forwarding and aliases), full US-20-US-21 to Stage 7, and
US-22 fallback behavior to Stage 10. The set exists so progress tracking stays
honest: no passing acceptance test in this slice may assert these criteria.
"""

DEFERRED_USER_STORIES: frozenset[str] = frozenset(
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
