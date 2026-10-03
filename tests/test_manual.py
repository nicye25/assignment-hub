from datetime import datetime

import pytest

from aggregator.fetchers.base import FetchError
from aggregator.fetchers.manual import TZ, ManualFetcher


def write(tmp_path, text):
    p = tmp_path / "manual.yaml"
    p.write_text(text, encoding="utf-8")
    return ManualFetcher(p)


def test_missing_file_means_no_entries(tmp_path):
    assert ManualFetcher(tmp_path / "nope.yaml").fetch() == []


def test_empty_file_means_no_entries(tmp_path):
    assert write(tmp_path, "").fetch() == []


def test_parses_all_due_formats(tmp_path):
    f = write(
        tmp_path,
        """
- course: C++
  title: Lab 2
  due: 2026-10-14 23:59
  url: https://example.edu/lab2
- course: C++
  title: Quiz 1
  due: 2026-10-10
- course: C++
  title: Project
  due: 2026-10-20 18:30:00
  done: true
""",
    )
    a, b, c = f.fetch()  # sorted by due date
    assert b.title == "Lab 2" and b.due_at == datetime(2026, 10, 14, 23, 59, tzinfo=TZ)
    assert b.url == "https://example.edu/lab2"
    assert a.title == "Quiz 1" and a.due_at == datetime(2026, 10, 10, 23, 59, tzinfo=TZ)
    assert c.due_at == datetime(2026, 10, 20, 18, 30, tzinfo=TZ) and c.submitted is True
    assert b.uid == "manual:c-lab-2"
    assert b.source == "manual"


@pytest.mark.parametrize(
    "text,match",
    [
        ("- title: x\n  due: 2026-10-10\n", "required"),
        ("- course: A\n  title: x\n", "due"),
        ("- course: A\n  title: x\n  due: soon\n", "cannot parse"),
        ("- course: A\n  title: x\n  due: 2026-10-10\n  done: maybe\n", "true or false"),
        ("just a string", "list"),
        ("- course: A\n  title: x\n  due: 2026-10-10\n- course: A\n  title: X\n  due: 2026-10-11\n", "duplicate"),
        ("- [unclosed\n", "invalid YAML"),
    ],
)
def test_bad_entries_raise_fetch_error(tmp_path, text, match):
    with pytest.raises(FetchError, match=match):
        write(tmp_path, text).fetch()
