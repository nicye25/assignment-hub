"""Smoke test: log into Gradescope and print upcoming assignments.

Usage (from the repo root, venv active):
    python scripts/try_gradescope.py
Requires GRADESCOPE_EMAIL and GRADESCOPE_PASSWORD in .env.
Optional: GRADESCOPE_TERMS="Fall 2026" (comma-separated) to override the guessed term.
"""
import logging
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

from aggregator.fetchers.base import FetchError
from aggregator.fetchers.gradescope import TZ, GradescopeFetcher, parse_terms


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    load_dotenv()
    email = os.environ.get("GRADESCOPE_EMAIL")
    password = os.environ.get("GRADESCOPE_PASSWORD")
    if not email or not password:
        sys.exit("Set GRADESCOPE_EMAIL and GRADESCOPE_PASSWORD in .env (never commit that file).")

    terms_env = os.environ.get("GRADESCOPE_TERMS")
    fetcher = GradescopeFetcher(email, password, terms=parse_terms(terms_env) if terms_env else None)
    try:
        items = fetcher.fetch()
    except FetchError as e:
        sys.exit(f"FAILED: {e}")

    print("Courses read:")
    for cid, c in fetcher.selected_courses.items():
        print(f"  {c.name} ({c.semester} {c.year}) id={cid}")

    now = datetime.now(TZ)
    upcoming = [a for a in items if a.due_at >= now]
    print(f"\n{len(items)} assignments with due dates, {len(upcoming)} upcoming\n")
    for a in upcoming[:25]:
        mark = {True: "done", False: "TODO", None: "?   "}[a.submitted]
        print(f"[{mark}] {a.due_at:%a %b %d %I:%M %p}  {a.course:<14} {a.title}")
        print(f"        {a.uid}")


if __name__ == "__main__":
    main()
