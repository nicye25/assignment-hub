import json
from datetime import datetime, timedelta, timezone

from aggregator.merge import merge, prune
from aggregator.models import Assignment
from aggregator.store import from_dict, load_previous, to_dict, write_json_atomic

NOW = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)


def mk(uid, source="canvas", due=None, **kw):
    return Assignment(uid=uid, source=source, course="C", title=uid,
                      due_at=due or NOW + timedelta(days=1), **kw)


def test_merge_dedupes_by_uid_first_wins_and_sorts():
    a1 = mk("canvas:1", due=NOW + timedelta(days=5))
    a1_dup = mk("canvas:1", due=NOW + timedelta(days=9))
    a2 = mk("canvas:2", due=NOW + timedelta(days=2))
    assert merge([a1, a1_dup, a2]) == [a2, a1]


def test_prune_drops_only_old_items():
    old = mk("old", due=NOW - timedelta(days=15))
    recent = mk("recent", due=NOW - timedelta(days=13))
    assert prune([old, recent], NOW, 14) == [recent]


def test_roundtrip():
    a = mk("canvas:1", url="https://x", submitted=False)
    assert from_dict(json.loads(json.dumps(to_dict(a)))) == a


def test_load_previous_missing_and_corrupt(tmp_path):
    assert load_previous(tmp_path / "none.json").assignments == []
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert load_previous(bad).sources == {}
    wrong_shape = tmp_path / "shape.json"
    wrong_shape.write_text(json.dumps({"sources": {}, "assignments": [{"uid": "x"}]}))
    assert load_previous(wrong_shape).assignments == []


def test_atomic_write_creates_parent_dirs(tmp_path):
    out = tmp_path / "data" / "out.json"
    write_json_atomic(out, {"a": 1})
    assert json.loads(out.read_text()) == {"a": 1}
    assert not list(out.parent.glob("*.tmp"))
