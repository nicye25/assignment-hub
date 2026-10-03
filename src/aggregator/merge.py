from __future__ import annotations

from datetime import datetime, timedelta

from aggregator.models import Assignment


def merge(items: list[Assignment]) -> list[Assignment]:
    """Dedupe by uid (first occurrence wins) and sort by due date.

    Note: this only removes exact uid duplicates. The same assignment appearing in
    two different sources (e.g. a Gradescope item mirrored into Canvas) has two
    different uids and is NOT merged here.
    """
    seen: dict[str, Assignment] = {}
    for a in items:
        seen.setdefault(a.uid, a)
    return sorted(seen.values(), key=lambda a: (a.due_at, a.uid))


def prune(items: list[Assignment], now: datetime, keep_days: int) -> list[Assignment]:
    """Drop assignments that were due more than keep_days ago."""
    cutoff = now - timedelta(days=keep_days)
    return [a for a in items if a.due_at >= cutoff]
