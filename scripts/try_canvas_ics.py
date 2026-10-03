"""Smoke test: fetch your real Canvas feed and print upcoming items.

Usage (from the repo root, venv active):
    python scripts/try_canvas_ics.py
Requires CANVAS_ICS_URL in .env.
"""
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

from aggregator.fetchers.canvas_ics import TZ, CanvasIcsFetcher


def main() -> None:
    load_dotenv()
    url = os.environ.get("CANVAS_ICS_URL")
    if not url:
        sys.exit("CANVAS_ICS_URL is not set. Add it to .env (never commit that file).")

    items = CanvasIcsFetcher(url).fetch()  # URL is a secret: never print it
    now = datetime.now(TZ)
    upcoming = [a for a in items if a.due_at >= now]

    print(f"{len(items)} events in feed, {len(upcoming)} upcoming\n")
    for a in upcoming[:25]:
        print(f"{a.due_at:%a %b %d %I:%M %p}  {a.course:<28} {a.title}")
        print(f"    {a.uid}")


if __name__ == "__main__":
    main()
