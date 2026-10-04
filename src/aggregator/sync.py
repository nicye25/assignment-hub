"""Run every fetcher, merge the results, and write data/assignments.json.

Usage:
    python -m aggregator.sync [--out data/assignments.json] [--manual manual.yaml]
                              [--only canvas gradescope manual]

Exit code is 1 if any source failed, so a CI run turns red (and emails you).
The output file is still written: a failed source keeps its last known
assignments, flagged stale, instead of vanishing.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import quote, quote_plus

from dotenv import load_dotenv

from aggregator.fetchers.base import Fetcher, FetchError
from aggregator.fetchers.canvas_api import DEFAULT_BASE_URL, CanvasApiFetcher
from aggregator.fetchers.canvas_ics import CanvasIcsFetcher
from aggregator.fetchers.gradescope import GradescopeFetcher, parse_terms
from aggregator.fetchers.manual import ManualFetcher
from aggregator.merge import merge, prune
from aggregator.models import Assignment
from aggregator.store import Previous, load_previous, to_dict, write_json_atomic

KEEP_DAYS = 14  # keep assignments this long after their due date
SECRET_ENV_VARS = ("CANVAS_API_TOKEN", "CANVAS_ICS_URL", "GRADESCOPE_EMAIL", "GRADESCOPE_PASSWORD")

Builder = Callable[[], Fetcher]
_URL = re.compile(r"""https?://[^\s'"<>)]+""")


def redact(text: str, secrets: Iterable[str]) -> str:
    """Scrub secrets and URLs from an error message before it is stored or logged.

    Exception text from `requests` can embed the full request URL, and both the
    Canvas feed URL and (via gradescopeapi's login) the password can appear in one.
    """
    for secret in sorted({s for s in secrets if s}, key=len, reverse=True):
        for form in {secret, quote(secret, safe=""), quote_plus(secret)}:
            text = text.replace(form, "***")
    return _URL.sub("<url>", text)


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise FetchError(f"{name} is not set")
    return value


def default_builders(manual_path: str) -> dict[str, Builder]:
    def canvas() -> Fetcher:
        # The API (submission status) wins over the ICS feed when a token is set.
        token = os.environ.get("CANVAS_API_TOKEN")
        if token:
            exclude = [x.strip() for x in os.environ.get("CANVAS_EXCLUDE_COURSES", "").split(",")]
            return CanvasApiFetcher(
                os.environ.get("CANVAS_BASE_URL") or DEFAULT_BASE_URL,
                token,
                exclude_course_ids=[x for x in exclude if x],
            )
        ics_url = os.environ.get("CANVAS_ICS_URL")
        if ics_url:
            return CanvasIcsFetcher(ics_url)
        raise FetchError("Neither CANVAS_API_TOKEN nor CANVAS_ICS_URL is set")

    def gradescope() -> Fetcher:
        terms = os.environ.get("GRADESCOPE_TERMS")
        return GradescopeFetcher(
            _require("GRADESCOPE_EMAIL"),
            _require("GRADESCOPE_PASSWORD"),
            terms=parse_terms(terms) if terms else None,
        )

    return {"canvas": canvas, "gradescope": gradescope, "manual": lambda: ManualFetcher(manual_path)}


def run_sync(
    builders: dict[str, Builder],
    previous: Previous,
    now: datetime,
    secrets: Iterable[str] = (),
    keep_days: int = KEEP_DAYS,
) -> tuple[dict, bool]:
    """Run the given sources and return (output document, all_ok)."""
    secrets = list(secrets)
    sources: dict[str, dict] = {}
    items: list[Assignment] = []

    for name, build in builders.items():
        prev = previous.sources.get(name, {})
        status = {
            "ok": True,
            "stale": False,
            "last_attempt": now.isoformat(),
            "last_success": now.isoformat(),
            "count": 0,
            "error": None,
        }
        try:
            fetched = build().fetch()
        except FetchError as e:
            error = str(e)
        except Exception as e:  # a buggy fetcher must not take down the other sources
            error = f"{type(e).__name__}: {e}"
        else:
            status["count"] = len(fetched)
            items.extend(fetched)
            sources[name] = status
            continue

        # Failure: keep what we knew last time and say so loudly
        carried = [a for a in previous.assignments if a.source == name]
        items.extend(carried)
        status.update(
            ok=False,
            stale=True,
            last_success=prev.get("last_success"),
            count=len(carried),
            error=redact(error, secrets),
        )
        sources[name] = status

    # Sources not run this time (--only) are carried over untouched
    for name, prev_status in previous.sources.items():
        if name not in builders:
            sources[name] = prev_status
    items.extend(a for a in previous.assignments if a.source not in builders)

    final = prune(merge(items), now, keep_days)
    output = {
        "schema": 1,
        "generated_at": now.isoformat(),
        "sources": sources,
        "assignments": [to_dict(a) for a in final],
    }
    all_ok = all(s["ok"] for name, s in sources.items() if name in builders)
    return output, all_ok


def main(argv: list[str] | None = None, builders: dict[str, Builder] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", default="data/assignments.json")
    parser.add_argument("--manual", default="manual.yaml")
    parser.add_argument("--only", nargs="+", help="run only these sources")
    args = parser.parse_args(argv)

    load_dotenv()
    available = builders if builders is not None else default_builders(args.manual)
    unknown = set(args.only or []) - set(available)
    if unknown:
        parser.error(f"unknown source(s): {', '.join(sorted(unknown))}")
    selected = {k: v for k, v in available.items() if not args.only or k in args.only}

    out = Path(args.out)
    now = datetime.now(timezone.utc)
    secrets = [os.environ.get(k, "") for k in SECRET_ENV_VARS]
    result, all_ok = run_sync(selected, load_previous(out), now, secrets)
    write_json_atomic(out, result)

    for name in selected:
        s = result["sources"][name]
        if s["ok"]:
            print(f"{name}: ok ({s['count']} assignments)")
        else:
            print(f"{name}: FAILED, showing {s['count']} stale assignments. {s['error']}")
    print(f"wrote {out} ({len(result['assignments'])} assignments)")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
