from datetime import date, datetime, timezone

import pytest
from gradescopeapi.classes.assignments import Assignment as GSAssignment
from gradescopeapi.classes.courses import Course

from aggregator.fetchers.base import FetchError
from aggregator.fetchers.gradescope import (
    TZ,
    GradescopeFetcher,
    current_term,
    parse_terms,
    to_assignment,
)


def make_course(name="COMS 3827", semester="Fall", year="2026"):
    return Course(
        name=name,
        full_name="Fundamentals of Computer Systems",
        semester=semester,
        year=year,
        num_grades_published=None,
        num_assignments="5",
    )


def make_gs(
    id="111",
    name="Problem Set 2",
    due=datetime(2026, 10, 6, 3, 59, tzinfo=timezone.utc),
    status="No Submission",
    grade=None,
):
    return GSAssignment(
        assignment_id=id,
        name=name,
        release_date=None,
        due_date=due,
        late_due_date=None,
        submissions_status=status,
        grade=grade,
        max_grade=None,
    )


class FakeAccount:
    def __init__(self, courses, assignments, fail_course=None):
        self._courses = courses
        self._assignments = assignments
        self._fail = fail_course

    def get_courses(self):
        return self._courses

    def get_assignments(self, course_id):
        if course_id == self._fail:
            raise RuntimeError("boom")
        return self._assignments[course_id]


class FakeConn:
    def __init__(self, account, login_error=None):
        self.account = account
        self.login_error = login_error
        self.logged_out = False

    def login(self, email, password):
        if self.login_error:
            raise self.login_error

    def logout(self):
        self.logged_out = True


def fetcher_with(conn, **kw):
    return GradescopeFetcher(
        "me@example.com", "pw", connection_factory=lambda: conn, today=date(2026, 10, 3), **kw
    )


# ---- conversion ----------------------------------------------------------

def test_due_date_converted_to_new_york():
    a = to_assignment("c1", make_course(), make_gs())
    assert a.due_at == datetime(2026, 10, 5, 23, 59, tzinfo=TZ)
    assert a.course == "COMS 3827"
    assert a.title == "Problem Set 2"
    assert a.uid == "gradescope:c1:111"
    assert a.url.endswith("/courses/c1/assignments/111")


def test_naive_due_date_gets_new_york_timezone():
    a = to_assignment("c1", make_course(), make_gs(due=datetime(2026, 10, 5, 23, 59)))
    assert a.due_at == datetime(2026, 10, 5, 23, 59, tzinfo=TZ)


def test_no_due_date_is_skipped():
    assert to_assignment("c1", make_course(), make_gs(due=None)) is None


def test_missing_assignment_id_falls_back_to_name_slug():
    a = to_assignment("c1", make_course(), make_gs(id=None, name="Lab  Report #3"))
    assert a.uid == "gradescope:c1:name-lab-report-3"
    assert a.url.endswith("/courses/c1")


@pytest.mark.parametrize(
    "status,grade,expected",
    [
        ("No Submission", None, False),
        ("Submitted", None, True),
        ("Submitted", 8.5, True),
        ("No Submission", 0.0, True),  # a recorded grade means it was handled
        (None, None, None),            # instructor view: unknown
        ("Something new", None, None),
    ],
)
def test_submitted_flag(status, grade, expected):
    a = to_assignment("c1", make_course(), make_gs(status=status, grade=grade))
    assert a.submitted is expected


# ---- fetcher -------------------------------------------------------------

def test_only_current_term_student_courses_are_fetched():
    courses = {
        "student": {"c1": make_course(), "c2": make_course("OLD 1000", "Spring", "2026")},
        "instructor": {"c3": make_course("TA 9999")},
    }
    account = FakeAccount(courses, {"c1": [make_gs()], "c2": [make_gs(id="9")], "c3": [make_gs(id="8")]})
    conn = FakeConn(account)
    items = fetcher_with(conn).fetch()
    assert [a.uid for a in items] == ["gradescope:c1:111"]
    assert conn.logged_out


def test_terms_override():
    courses = {"student": {"c2": make_course("OLD 1000", "Spring", "2026")}}
    account = FakeAccount(courses, {"c2": [make_gs(id="9")]})
    items = fetcher_with(FakeConn(account), terms=parse_terms("Spring 2026")).fetch()
    assert [a.uid for a in items] == ["gradescope:c2:9"]


def test_results_sorted_by_due_date():
    late = make_gs(id="2", due=datetime(2026, 10, 20, 12, tzinfo=timezone.utc))
    early = make_gs(id="1", due=datetime(2026, 10, 10, 12, tzinfo=timezone.utc))
    account = FakeAccount({"student": {"c1": make_course()}}, {"c1": [late, early]})
    items = fetcher_with(FakeConn(account)).fetch()
    assert [a.uid for a in items] == ["gradescope:c1:1", "gradescope:c1:2"]


def test_login_failure_raises_fetch_error():
    conn = FakeConn(None, login_error=ValueError("Invalid credentials."))
    with pytest.raises(FetchError, match="login failed"):
        fetcher_with(conn).fetch()


def test_unexpected_login_error_raises_fetch_error():
    conn = FakeConn(None, login_error=TypeError("'NoneType' object is not subscriptable"))
    with pytest.raises(FetchError, match="login error"):
        fetcher_with(conn).fetch()


def test_course_failure_raises_instead_of_returning_partial_results():
    account = FakeAccount(
        {"student": {"c1": make_course(), "c2": make_course("ECON 1105")}},
        {"c1": [make_gs()], "c2": []},
        fail_course="c2",
    )
    with pytest.raises(FetchError, match="ECON 1105"):
        fetcher_with(FakeConn(account)).fetch()


# ---- helpers -------------------------------------------------------------

def test_current_term():
    assert current_term(date(2026, 10, 3)) == ("Fall", "2026")
    assert current_term(date(2026, 2, 1)) == ("Spring", "2026")
    assert current_term(date(2026, 7, 1)) == ("Summer", "2026")


def test_parse_terms():
    assert parse_terms("Fall 2026, Spring 2026") == [("Fall", "2026"), ("Spring", "2026")]
    with pytest.raises(ValueError):
        parse_terms("Fall")
