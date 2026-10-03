"""Hand-entered deadlines from manual.yaml, for sources we can't automate.

Example manual.yaml:

    - course: C++
      title: Lab 2
      due: 2026-10-14 23:59        # America/New_York; a bare date means 23:59
      url: https://example.edu/cpp/lab2   # optional
      done: false                  # optional
"""
from __future__ import annotations

import re
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from aggregator.fetchers.base import FetchError
from aggregator.models import Assignment

TZ = ZoneInfo("America/New_York")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _parse_due(value, where: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.strip())
        except ValueError as e:
            raise FetchError(f"{where}: cannot parse due {value!r} (use 2026-10-14 23:59)") from e
    if isinstance(value, datetime):  # check first: datetime is a subclass of date
        return value.replace(tzinfo=TZ) if value.tzinfo is None else value.astimezone(TZ)
    if isinstance(value, date):
        return datetime.combine(value, time(23, 59), tzinfo=TZ)
    raise FetchError(f"{where}: missing or invalid 'due'")


class ManualFetcher:
    name = "manual"

    def __init__(self, path: str | Path = "manual.yaml"):
        self.path = Path(path)

    def fetch(self) -> list[Assignment]:
        if not self.path.exists():
            return []
        try:
            data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise FetchError(f"{self.path}: invalid YAML: {e}") from e
        if data is None:
            return []
        if not isinstance(data, list):
            raise FetchError(f"{self.path}: expected a list of entries")

        items: dict[str, Assignment] = {}
        for i, entry in enumerate(data, 1):
            where = f"{self.path} entry {i}"
            if not isinstance(entry, dict):
                raise FetchError(f"{where}: expected a mapping")
            course = str(entry.get("course", "")).strip()
            title = str(entry.get("title", "")).strip()
            if not course or not title:
                raise FetchError(f"{where}: 'course' and 'title' are required")
            done = entry.get("done")
            if done is not None and not isinstance(done, bool):
                raise FetchError(f"{where}: 'done' must be true or false")
            uid = f"manual:{_slug(course)}-{_slug(title)}"
            if uid in items:
                raise FetchError(f"{where}: duplicate of an earlier entry ({course} / {title})")
            items[uid] = Assignment(
                uid=uid,
                source=self.name,
                course=course,
                title=title,
                due_at=_parse_due(entry.get("due"), where),
                url=str(entry["url"]) if entry.get("url") else None,
                submitted=done,
            )
        return sorted(items.values(), key=lambda a: a.due_at)
