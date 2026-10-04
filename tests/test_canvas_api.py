from datetime import datetime
from types import SimpleNamespace

import pytest
from canvasapi.assignment import Assignment as CanvasAssignment
from canvasapi.exceptions import (
    Forbidden,
    InvalidAccessToken,
    RateLimitExceeded,
    Unauthorized,
)
from canvasapi.requester import Requester

from aggregator.fetchers.base import FetchError
from aggregator.fetchers.canvas_api import TZ, CanvasApiFetcher, to_assignment

REQ = Requester("https://courseworks2.columbia.edu", "token")  # no network on construction


def make_assignment(id=5, name="Homework 1", due="2026-10-06T03:59:59Z", types=("online_upload",),
                    submission=None, **extra):
    data = {"id": id, "name": name, "due_at": due, "course_id": 9,
            "html_url": f"https://courseworks2.columbia.edu/courses/9/assignments/{id}",
            "submission_types": list(types), **extra}
    if submission is not None:
        data["submission"] = submission
    return CanvasAssignment(REQ, data)


def make_course(id=9, code="STAT GU4203", name="Probability Theory", assignments=(), exc=None, **extra):
    calls = []

    def get_assignments(**kwargs):
        calls.append(kwargs)
        if exc:
            raise exc
        return list(assignments)

    return SimpleNamespace(id=id, course_code=code, name=name, get_assignments=get_assignments,
                           calls=calls, **extra)


class FakeCanvas:
    def __init__(self, courses=(), exc=None):
        self._courses, self._exc, self.calls = list(courses), exc, []

    def get_courses(self, **kwargs):
        self.calls.append(kwargs)
        if self._exc:
            raise self._exc
        return list(self._courses)


def fetcher(canvas, **kw):
    return CanvasApiFetcher("https://courseworks2.columbia.edu/", "tok",
                            canvas_factory=lambda url, tok: canvas, **kw)


# ---- conversion ----------------------------------------------------------

def test_conversion_fields():
    a = to_assignment(make_course(), make_assignment(name="  Homework   1 "))
    assert a.due_at == datetime(2026, 10, 5, 23, 59, 59, tzinfo=TZ)
    assert a.uid == "canvas:9:5"
    assert a.course == "STAT GU4203"
    assert a.title == "Homework 1"
    assert a.url.endswith("/courses/9/assignments/5")
    assert a.source == "canvas"


def test_course_label_falls_back_to_name():
    assert to_assignment(make_course(code=None), make_assignment()).course == "Probability Theory"


def test_no_due_date_is_skipped():
    assert to_assignment(make_course(), make_assignment(due=None)) is None


@pytest.mark.parametrize(
    "submission,types,expected",
    [
        ({"workflow_state": "submitted"}, ["online_upload"], True),
        ({"workflow_state": "graded", "submitted_at": "2026-10-01T10:00:00Z"}, ["online_upload"], True),
        ({"workflow_state": "pending_review"}, ["online_quiz"], True),
        ({"workflow_state": "unsubmitted"}, ["online_upload"], False),
        ({"workflow_state": "unsubmitted"}, ["online_quiz"], False),
        ({"workflow_state": "unsubmitted"}, ["discussion_topic"], False),
        ({"workflow_state": "unsubmitted"}, ["none"], None),
        ({"workflow_state": "unsubmitted"}, ["on_paper"], None),
        ({"workflow_state": "unsubmitted"}, ["external_tool"], None),
        ({"workflow_state": "unsubmitted"}, [], None),
        ({"workflow_state": "unsubmitted", "excused": True}, ["online_upload"], True),
        ({"workflow_state": "unsubmitted", "missing": True}, ["online_upload"], False),
        ({"workflow_state": "graded", "missing": True}, ["online_upload"], False),
        ({"workflow_state": "something_new"}, ["online_upload"], None),
    ],
)
def test_submitted_mapping(submission, types, expected):
    a = to_assignment(make_course(), make_assignment(types=types, submission=submission))
    assert a.submitted is expected


def test_missing_submission_object_is_unknown():
    assert to_assignment(make_course(), make_assignment()).submitted is None


# ---- fetcher -------------------------------------------------------------

def test_fetch_requests_and_sorting():
    late = make_assignment(id=2, due="2026-10-20T12:00:00Z")
    early = make_assignment(id=1, due="2026-10-10T12:00:00Z")
    other = make_assignment(id=3, due="2026-10-15T12:00:00Z")
    c1 = make_course(id=9, assignments=[late, early])
    c2 = make_course(id=10, code="ECON GU4020", assignments=[other])
    canvas = FakeCanvas([c1, c2])
    f = fetcher(canvas)
    items = f.fetch()

    assert [a.uid for a in items] == ["canvas:9:1", "canvas:9:3", "canvas:9:2"]
    assert canvas.calls[0]["enrollment_state"] == "active"
    assert canvas.calls[0]["enrollment_type"] == "student"
    assert c1.calls[0]["include"] == ["submission"]
    assert [c.id for c in f.courses_read] == [9, 10]


def test_base_url_trailing_slash_is_stripped():
    assert CanvasApiFetcher("https://courseworks2.columbia.edu/", "t").base_url == \
        "https://courseworks2.columbia.edu"


def test_restricted_and_excluded_courses_are_skipped():
    ok = make_course(id=9, assignments=[make_assignment()])
    restricted = make_course(id=10, assignments=[make_assignment(id=7)], access_restricted_by_date=True)
    excluded = make_course(id=11, assignments=[make_assignment(id=8)])
    items = fetcher(FakeCanvas([ok, restricted, excluded]), exclude_course_ids=["11"]).fetch()
    assert [a.uid for a in items] == ["canvas:9:5"]
    assert restricted.calls == [] and excluded.calls == []


def test_assignments_without_due_dates_are_dropped():
    c = make_course(assignments=[make_assignment(id=1, due=None), make_assignment(id=2)])
    assert [a.uid for a in fetcher(FakeCanvas([c])).fetch()] == ["canvas:9:2"]


# ---- failures ------------------------------------------------------------

def test_bad_token_while_listing_courses():
    with pytest.raises(FetchError, match="invalid, expired, or revoked"):
        fetcher(FakeCanvas(exc=InvalidAccessToken({"errors": [{"message": "Invalid access token."}]}))).fetch()


@pytest.mark.parametrize("exc", [Unauthorized("no"), Forbidden("no")])
def test_permission_error_names_the_course(exc):
    bad = make_course(id=12, code="HIST UN1000", exc=exc)
    with pytest.raises(FetchError) as info:
        fetcher(FakeCanvas([bad])).fetch()
    assert "HIST UN1000" in str(info.value) and "CANVAS_EXCLUDE_COURSES" in str(info.value)


def test_rate_limit():
    bad = make_course(exc=RateLimitExceeded("slow down"))
    with pytest.raises(FetchError, match="rate limited"):
        fetcher(FakeCanvas([bad])).fetch()


def test_unexpected_error_is_wrapped():
    with pytest.raises(FetchError, match="listing courses"):
        fetcher(FakeCanvas(exc=ConnectionError("dns failure"))).fetch()


def test_one_failing_course_fails_the_whole_source():
    good = make_course(id=9, assignments=[make_assignment()])
    bad = make_course(id=10, exc=Forbidden("no"))
    with pytest.raises(FetchError):
        fetcher(FakeCanvas([good, bad])).fetch()
