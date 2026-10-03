from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class Assignment:
    uid: str            # f"{source}:{source_id}", stable across runs
    source: str         # "canvas", "gradescope", "manual", ...
    course: str
    title: str
    due_at: datetime    # timezone-aware
    url: str | None = None
    submitted: bool | None = None   # None = unknown (e.g. the Canvas ICS feed)