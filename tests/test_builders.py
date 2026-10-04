import pytest

from aggregator.fetchers.base import FetchError
from aggregator.fetchers.canvas_api import DEFAULT_BASE_URL, CanvasApiFetcher
from aggregator.fetchers.canvas_ics import CanvasIcsFetcher
from aggregator.sync import default_builders

CANVAS_VARS = ("CANVAS_API_TOKEN", "CANVAS_BASE_URL", "CANVAS_EXCLUDE_COURSES", "CANVAS_ICS_URL")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for v in CANVAS_VARS:
        monkeypatch.delenv(v, raising=False)


def canvas():
    return default_builders("manual.yaml")["canvas"]()


def test_token_selects_api_with_default_base_url(monkeypatch):
    monkeypatch.setenv("CANVAS_API_TOKEN", "tok")
    f = canvas()
    assert isinstance(f, CanvasApiFetcher) and f.base_url == DEFAULT_BASE_URL


def test_empty_base_url_falls_back_to_default(monkeypatch):
    # GitHub Actions passes an empty string for an unset variable
    monkeypatch.setenv("CANVAS_API_TOKEN", "tok")
    monkeypatch.setenv("CANVAS_BASE_URL", "")
    assert canvas().base_url == DEFAULT_BASE_URL


def test_exclude_courses_parsed(monkeypatch):
    monkeypatch.setenv("CANVAS_API_TOKEN", "tok")
    monkeypatch.setenv("CANVAS_EXCLUDE_COURSES", "12, 34,,")
    assert canvas().exclude == {"12", "34"}


def test_api_wins_over_ics_when_both_set(monkeypatch):
    monkeypatch.setenv("CANVAS_API_TOKEN", "tok")
    monkeypatch.setenv("CANVAS_ICS_URL", "https://example/feed.ics")
    assert isinstance(canvas(), CanvasApiFetcher)


def test_ics_used_when_no_token(monkeypatch):
    monkeypatch.setenv("CANVAS_ICS_URL", "https://example/feed.ics")
    assert isinstance(canvas(), CanvasIcsFetcher)


def test_neither_configured_is_an_error():
    with pytest.raises(FetchError, match="CANVAS_API_TOKEN"):
        canvas()
