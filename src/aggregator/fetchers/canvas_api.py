"""Fetch assignments from the Canvas (CourseWorks) REST API via `canvasapi`.

Unlike the ICS feed this gives per-assignment submission status. Auth is a personal
access token (CourseWorks: Account > Settings > Approved Integrations). Treat it like
a password: it can do anything your account can through the API.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

from canvasapi import Canvas
from canvasapi.exceptions import (
    Forbidden,
    InvalidAccessToken,
    RateLimitExceeded,
    Unauthorized,
)

from aggregator.fetchers.base import FetchError
from aggregator.models import Assignment

log = logging.getLogger(__name__)
TZ = ZoneInfo("America/New_York")
DEFAULT_BASE_URL = "https://courseworks2.columbia.edu"

# Canvas can't tell whether you're done with these, so `submitted` stays None.
# external_tool covers LTI items (e.g. Gradescope); Canvas only learns of a
# submission if the tool sends a grade back.
_UNTRACKED_TYPES = {"none", "on_paper", "not_graded", "external_tool"}
_DONE_STATES = {"submitted", "graded", "pending_review"}


def _parse_due(value: str) -> datetime:
    # Canvas sends UTC like "2026-10-06T03:59:59Z"; fromisoformat needs +00:00 before 3.11
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.replace(tzinfo=TZ) if dt.tzinfo is None else dt.astimezone(TZ)


def _submitted(a) -> bool | None:
    """True/False when Canvas tracks completion for this assignment, else None."""
    sub = getattr(a, "submission", None)
    if not isinstance(sub, dict):
        return None
    if sub.get("excused"):
        return True
    if sub.get("missing"):
        return False
    state = sub.get("workflow_state")
    if state in _DONE_STATES:
        return True
    if state == "unsubmitted":
        types = set(getattr(a, "submission_types", None) or [])
        if not types or types & _UNTRACKED_TYPES:
            return None
        return False
    return None


def to_assignment(course, a) -> Assignment | None:
    """Convert one canvasapi assignment; None if it has no due date."""
    if not getattr(a, "due_at", None):
        return None
    course_id = getattr(a, "course_id", None) or course.id
    label = getattr(course, "course_code", None) or getattr(course, "name", None) or str(course.id)
    return Assignment(
        uid=f"canvas:{course_id}:{a.id}",
        source="canvas",
        course=label,
        title=" ".join(a.name.split()),
        due_at=_parse_due(a.due_at),
        url=getattr(a, "html_url", None),
        submitted=_submitted(a),
    )


def _error(what: str, e: Exception) -> FetchError:
    if isinstance(e, InvalidAccessToken):
        return FetchError(
            f"Canvas: access token invalid, expired, or revoked while {what}. "
            "Generate a new one in CourseWorks (Account > Settings > Approved Integrations)."
        )
    # RateLimitExceeded subclasses Forbidden in canvasapi, so it must be checked first
    if isinstance(e, RateLimitExceeded):
        return FetchError(f"Canvas: rate limited while {what}; next run will retry.")
    if isinstance(e, (Unauthorized, Forbidden)):
        return FetchError(
            f"Canvas: not permitted while {what} ({type(e).__name__}). "
            "If it is a single course, add its id to CANVAS_EXCLUDE_COURSES."
        )
    return FetchError(f"Canvas: error while {what}: {type(e).__name__}: {e}")


class CanvasApiFetcher:
    name = "canvas"

    def __init__(
        self,
        base_url: str,
        token: str,
        exclude_course_ids: Iterable[str | int] = (),
        canvas_factory: Callable[[str, str], Canvas] = Canvas,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.exclude = {str(i) for i in exclude_course_ids}
        self._factory = canvas_factory
        self.courses_read: list = []

    def fetch(self) -> list[Assignment]:
        canvas = self._factory(self.base_url, self.token)

        try:
            raw_courses = list(
                canvas.get_courses(
                    enrollment_state="active",
                    enrollment_type="student",
                    include=["term"],
                    per_page=100,
                )
            )
        except Exception as e:  # PaginatedList is lazy, so errors surface here
            raise _error("listing courses", e) from e

        courses = []
        for c in raw_courses:
            if getattr(c, "access_restricted_by_date", False):
                log.warning("Canvas: skipping course %s (access restricted by date)", c.id)
            elif str(c.id) in self.exclude:
                log.info("Canvas: skipping excluded course %s", c.id)
            else:
                courses.append(c)
        self.courses_read = courses

        items: list[Assignment] = []
        for course in courses:
            label = getattr(course, "course_code", None) or getattr(course, "name", None) or course.id
            try:
                raw = list(course.get_assignments(include=["submission"], per_page=100))
            except Exception as e:
                # Fail loudly: a half-empty result would look like 'nothing due'
                raise _error(f"reading course {label} ({course.id})", e) from e
            for a in raw:
                converted = to_assignment(course, a)
                if converted is not None:
                    items.append(converted)
        return sorted(items, key=lambda a: a.due_at)
