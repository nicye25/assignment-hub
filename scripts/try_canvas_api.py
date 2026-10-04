"""Smoke test: read your real CourseWorks data through the Canvas API.

Usage (from the repo root, venv active):
    python scripts/try_canvas_api.py
Requires CANVAS_API_TOKEN in .env. Optional: CANVAS_BASE_URL, CANVAS_EXCLUDE_COURSES.
"""
import logging
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

from aggregator.fetchers.base import FetchError
from aggregator.fetchers.canvas_api import DEFAULT_BASE_URL, TZ, CanvasApiFetcher


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    load_dotenv()
    token = os.environ.get("CANVAS_API_TOKEN")
    if not token:
        sys.exit("Set CANVAS_API_TOKEN in .env (never commit that file).")

    exclude = [x.strip() for x in os.environ.get("CANVAS_EXCLUDE_COURSES", "").split(",") if x.strip()]
    fetcher = CanvasApiFetcher(os.environ.get("CANVAS_BASE_URL") or DEFAULT_BASE_URL, token,
                               exclude_course_ids=exclude)
    try:
        items = fetcher.fetch()
    except FetchError as e:
        sys.exit(f"FAILED: {e}")

    print("Courses read:")
    for c in fetcher.courses_read:
        term = (getattr(c, "term", None) or {}).get("name", "?")
        print(f"  id={c.id}  {getattr(c, 'course_code', '?')}  |  {getattr(c, 'name', '?')}  |  {term}")

    now = datetime.now(TZ)
    upcoming = [a for a in items if a.due_at >= now]
    print(f"\n{len(items)} assignments with due dates, {len(upcoming)} upcoming\n")
    for a in upcoming[:25]:
        mark = {True: "done", False: "TODO", None: "?   "}[a.submitted]
        print(f"[{mark}] {a.due_at:%a %b %d %I:%M %p}  {a.course:<18} {a.title}")
        print(f"        {a.uid}")


if __name__ == "__main__":
    main()
