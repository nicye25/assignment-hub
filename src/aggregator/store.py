"""Reading and writing data/assignments.json."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from aggregator.models import Assignment

log = logging.getLogger(__name__)


@dataclass
class Previous:
    sources: dict = field(default_factory=dict)
    assignments: list[Assignment] = field(default_factory=list)


def to_dict(a: Assignment) -> dict:
    d = asdict(a)
    d["due_at"] = a.due_at.isoformat()
    return d


def from_dict(d: dict) -> Assignment:
    return Assignment(
        uid=d["uid"],
        source=d["source"],
        course=d["course"],
        title=d["title"],
        due_at=datetime.fromisoformat(d["due_at"]),
        url=d.get("url"),
        submitted=d.get("submitted"),
    )


def load_previous(path: Path) -> Previous:
    """Load the last run's output; a missing or corrupt file means a fresh start."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return Previous(
            sources=dict(raw["sources"]),
            assignments=[from_dict(d) for d in raw["assignments"]],
        )
    except FileNotFoundError:
        return Previous()
    except (ValueError, KeyError, TypeError) as e:
        log.warning("Ignoring unreadable previous output %s: %s", path, e)
        return Previous()


def write_json_atomic(path: Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)  # atomic: readers never see a half-written file
