from typing import Protocol
from aggregator.models import Assignment


class FetchError(Exception):
    """A source could not be read. Raised loudly so sync can mark it stale
    instead of silently reporting 'no assignments'."""
    
class Fetcher(Protocol):
    name: str
    def fetch(self) -> list[Assignment]: ...