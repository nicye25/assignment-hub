import json
from datetime import datetime, timedelta, timezone

from aggregator.fetchers.base import FetchError
from aggregator.models import Assignment
from aggregator.store import Previous
from aggregator.sync import main, redact, run_sync

NOW = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)


def mk(uid, source="canvas", days=1):
    return Assignment(uid=uid, source=source, course="C", title=uid,
                      due_at=NOW + timedelta(days=days))


class FakeFetcher:
    def __init__(self, items=(), exc=None):
        self.items, self.exc = list(items), exc

    def fetch(self):
        if self.exc:
            raise self.exc
        return self.items


def ok_builders():
    return {
        "canvas": lambda: FakeFetcher([mk("canvas:1")]),
        "gradescope": lambda: FakeFetcher([mk("gradescope:1", "gradescope", 2)]),
    }


def uids(out):
    return [a["uid"] for a in out["assignments"]]


def test_all_sources_ok():
    out, ok = run_sync(ok_builders(), Previous(), NOW)
    assert ok
    assert uids(out) == ["canvas:1", "gradescope:1"]
    s = out["sources"]["canvas"]
    assert s["ok"] and not s["stale"] and s["count"] == 1
    assert s["last_success"] == NOW.isoformat() and s["error"] is None


def test_failed_source_keeps_stale_data_and_last_success():
    prev = Previous(
        sources={"gradescope": {"ok": True, "last_success": "2026-10-02T12:00:00+00:00"}},
        assignments=[mk("gradescope:old", "gradescope", 3)],
    )
    builders = ok_builders()
    builders["gradescope"] = lambda: FakeFetcher(exc=FetchError("login failed"))
    out, ok = run_sync(builders, prev, NOW)
    assert not ok
    g = out["sources"]["gradescope"]
    assert g["ok"] is False and g["stale"] is True
    assert g["last_success"] == "2026-10-02T12:00:00+00:00"
    assert g["error"] == "login failed" and g["count"] == 1
    assert uids(out) == ["canvas:1", "gradescope:old"]  # canvas still refreshed
    assert out["sources"]["canvas"]["ok"]


def test_source_that_fails_before_ever_succeeding():
    def missing_env():
        raise FetchError("GRADESCOPE_EMAIL is not set")

    out, ok = run_sync({"gradescope": missing_env}, Previous(), NOW)
    g = out["sources"]["gradescope"]
    assert not ok and g["last_success"] is None and g["count"] == 0
    assert "GRADESCOPE_EMAIL" in g["error"]


def test_unexpected_exception_is_contained_and_redacted():
    boom = RuntimeError(
        "GET https://courseworks2.columbia.edu/feeds/calendars/user_TOPSECRET.ics failed "
        "params=session%5Bpassword%5D=hunter%402"
    )
    builders = {"canvas": lambda: FakeFetcher(exc=boom), "gradescope": ok_builders()["gradescope"]}
    out, ok = run_sync(builders, Previous(), NOW, secrets=["hunter@2", "TOPSECRET"])
    err = out["sources"]["canvas"]["error"]
    assert "RuntimeError" in err
    assert "TOPSECRET" not in err and "hunter" not in err and "courseworks2" not in err
    assert out["sources"]["gradescope"]["ok"]  # other sources unaffected


def test_redact_handles_encoded_forms():
    assert "p@ss w" not in redact("pw=p%40ss+w and p%40ss%20w and p@ss w", ["p@ss w"])


def test_sources_not_run_are_carried_over():
    prev = Previous(
        sources={"canvas": {"ok": True, "last_success": "x", "count": 1}},
        assignments=[mk("canvas:keep")],
    )
    out, ok = run_sync({"gradescope": ok_builders()["gradescope"]}, prev, NOW)
    assert ok
    assert uids(out) == ["canvas:keep", "gradescope:1"]
    assert out["sources"]["canvas"]["last_success"] == "x"


def test_old_assignments_pruned():
    builders = {"canvas": lambda: FakeFetcher([mk("canvas:old", days=-30), mk("canvas:new")])}
    out, _ = run_sync(builders, Previous(), NOW)
    assert uids(out) == ["canvas:new"]


def test_main_writes_file_and_sets_exit_code(tmp_path, capsys):
    out_path = tmp_path / "data" / "assignments.json"
    failing = ok_builders()
    failing["gradescope"] = lambda: FakeFetcher(exc=FetchError("login failed"))

    assert main(["--out", str(out_path)], builders=failing) == 1
    doc = json.loads(out_path.read_text())
    assert doc["sources"]["gradescope"]["ok"] is False  # file written despite failure
    assert "login failed" in capsys.readouterr().out

    # Next run succeeds: exit 0, status recovers
    assert main(["--out", str(out_path)], builders=ok_builders()) == 0
    doc = json.loads(out_path.read_text())
    assert doc["sources"]["gradescope"]["ok"] is True and not doc["sources"]["gradescope"]["stale"]
