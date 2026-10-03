"""Fetch assignments from a Canvas (CourseWorks) calendar feed (.ics)."""
from __future__ import annotations

import re
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import requests
from icalendar import Calendar

from aggregator.models import Assignment

TZ = ZoneInfo("America/New_York")

# Canvas appends the course code to the event title: "Homework 1 [COURSE_CODE]"
_COURSE_SUFFIX = re.compile(r"^(?P<title>.*?)\s*\[(?P<course>[^\]]+)\]\s*$")


def _to_due_datetime(value: date | datetime) -> datetime:
    """Normalize an ICS DTSTART value to a timezone-aware datetime in TZ."""
    if isinstance(value, datetime):  # check first: datetime is a subclass of date
        if value.tzinfo is None:
            return value.replace(tzinfo=TZ)
        return value.astimezone(TZ)
    # All-day event: treat the due time as end of day
    return datetime.combine(value, time(23, 59), tzinfo=TZ)


def parse_ics(text: str, source: str = "canvas") -> list[Assignment]:
    """Parse raw ICS text into Assignments, sorted by due date."""
    cal = Calendar.from_ical(text)
    items: list[Assignment] = []
    for ev in cal.walk("VEVENT"):
        uid = str(ev.get("uid", "")).strip()
        summary = str(ev.get("summary", "")).strip()
        dtstart = ev.get("dtstart")
        if not uid or not summary or dtstart is None:
            continue  # skip malformed events rather than crash the whole sync

        m = _COURSE_SUFFIX.match(summary)
        title, course = (m["title"], m["course"]) if m else (summary, "unknown")
        url = ev.get("url")

        items.append(
            Assignment(
                uid=f"{source}:{uid}",
                source=source,
                course=course,
                title=title,
                due_at=_to_due_datetime(dtstart.dt),
                url=str(url) if url else None,
            )
        )
    return sorted(items, key=lambda a: a.due_at)


class CanvasIcsFetcher:
    name = "canvas"

    def __init__(self, url: str, timeout: int = 30):
        # Calendar apps sometimes hand out webcal:// links; requests needs https://
        self.url = url.replace("webcal://", "https://", 1)
        self.timeout = timeout

    def fetch(self) -> list[Assignment]:
        resp = requests.get(self.url, timeout=self.timeout)
        resp.raise_for_status()
        return parse_ics(resp.text, source=self.name)
