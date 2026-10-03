"""Fetch assignments from Gradescope via the unofficial `gradescopeapi` library."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Callable
from zoneinfo import ZoneInfo

from gradescopeapi import DEFAULT_GRADESCOPE_BASE_URL
from gradescopeapi.classes.assignments import Assignment as GSAssignment
from gradescopeapi.classes.connection import GSConnection
from gradescopeapi.classes.courses import Course

from aggregator.fetchers.base import FetchError
from aggregator.models import Assignment

log = logging.getLogger(__name__)
TZ = ZoneInfo("America/New_York")

Term = tuple[str, str]  # ("Fall", "2026")


def current_term(today: date) -> Term:
    """Best-effort guess of the current Gradescope term. Override with `terms=`."""
    if today.month <= 5:
        season = "Spring"
    elif today.month <= 8:
        season = "Summer"
    else:
        season = "Fall"
    return season, str(today.year)


def parse_terms(text: str) -> list[Term]:
    """Parse 'Fall 2026, Spring 2026' into [('Fall','2026'), ('Spring','2026')]."""
    terms: list[Term] = []
    for chunk in text.split(","):
        if not chunk.strip():
            continue
        parts = chunk.split()
        if len(parts) != 2:
            raise ValueError(f"Bad term {chunk!r}; expected something like 'Fall 2026'")
        terms.append((parts[0], parts[1]))
    return terms


def _norm(term: Term) -> Term:
    return term[0].strip().lower(), str(term[1]).strip()


def _submitted(gs: GSAssignment) -> bool | None:
    """True/False when Gradescope tells us, None when we can't tell.

    The status strings below are inferred from the library's parsing code and the
    Gradescope UI; verify against your own account with scripts/try_gradescope.py.
    """
    if gs.grade is not None:
        return True
    status = (gs.submissions_status or "").strip().lower()
    if not status:
        return None  # instructor view carries no submission status
    if status == "no submission":
        return False
    if "submitted" in status:
        return True
    return None


def to_assignment(
    course_id: str,
    course: Course,
    gs: GSAssignment,
    base_url: str = DEFAULT_GRADESCOPE_BASE_URL,
) -> Assignment | None:
    """Convert one gradescopeapi assignment; None if it has no due date."""
    due = gs.due_date
    if due is None:
        return None
    due = due.replace(tzinfo=TZ) if due.tzinfo is None else due.astimezone(TZ)

    title = " ".join((gs.name or "").split())
    if gs.assignment_id:
        # Stable across runs even if the title or due date changes
        uid = f"gradescope:{course_id}:{gs.assignment_id}"
        url = f"{base_url}/courses/{course_id}/assignments/{gs.assignment_id}"
    else:
        # Non-submittable, not-yet-submitted rows have no id in the student view
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        uid = f"gradescope:{course_id}:name-{slug}"
        url = f"{base_url}/courses/{course_id}"

    return Assignment(
        uid=uid,
        source="gradescope",
        course=course.name,
        title=title,
        due_at=due,
        url=url,
        submitted=_submitted(gs),
    )


class GradescopeFetcher:
    name = "gradescope"

    def __init__(
        self,
        email: str,
        password: str,
        terms: list[Term] | None = None,
        connection_factory: Callable[[], GSConnection] = GSConnection,
        today: date | None = None,
    ):
        self.email = email
        self.password = password
        wanted = terms or [current_term(today or datetime.now(TZ).date())]
        self.terms = {_norm(t) for t in wanted}
        self._connection_factory = connection_factory
        self.selected_courses: dict[str, Course] = {}

    def fetch(self) -> list[Assignment]:
        conn = self._connection_factory()
        try:
            conn.login(self.email, self.password)
        except ValueError as e:
            raise FetchError(
                "Gradescope login failed: invalid credentials, or this account has "
                "no password (e.g. it signs in through school SSO)."
            ) from e
        except Exception as e:  # page layout change, network error, captcha...
            raise FetchError(f"Gradescope login error: {type(e).__name__}: {e}") from e

        try:
            return self._fetch_logged_in(conn)
        finally:
            try:
                conn.logout()
            except Exception:  # best effort only
                pass

    def _fetch_logged_in(self, conn) -> list[Assignment]:
        try:
            student_courses = conn.account.get_courses().get("student", {})
        except Exception as e:
            raise FetchError(f"Gradescope: could not list courses: {e}") from e

        self.selected_courses = {
            cid: c
            for cid, c in student_courses.items()
            if _norm((c.semester, c.year)) in self.terms
        }
        if not self.selected_courses:
            available = sorted({f"{c.semester} {c.year}" for c in student_courses.values()})
            log.warning(
                "Gradescope: no student courses match terms %s (available: %s)",
                sorted(self.terms),
                available,
            )

        items: list[Assignment] = []
        for cid, course in self.selected_courses.items():
            try:
                gs_assignments = conn.account.get_assignments(cid)
            except Exception as e:
                # Fail loudly: a half-empty result would look like 'nothing due'
                raise FetchError(
                    f"Gradescope: failed reading course {course.name} ({cid}): {e}"
                ) from e
            for gs in gs_assignments:
                converted = to_assignment(cid, course, gs)
                if converted is not None:
                    items.append(converted)
        return sorted(items, key=lambda a: a.due_at)
