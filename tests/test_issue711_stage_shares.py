import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "stage_shares", Path(__file__).resolve().parents[1] / "scripts" / "stage_shares.py")
ss = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ss)


def _st(**kw):
    return [{"name": n.replace("_", " "), "seconds": s} for n, s in kw.items()]


def test_exact_shares():
    rows = [
        [{"name": "skeleton applied", "seconds": 10}, {"name": "loop pass 1", "seconds": 30},
         {"name": "loop pass 2", "seconds": 50}, {"name": "config (final lanes)", "seconds": 10}],
        [{"name": "skeleton applied", "seconds": 20}, {"name": "loop opening", "seconds": 60},
         {"name": "config (final lanes)", "seconds": 20}],
        [{"name": "skeleton applied", "seconds": 50}, {"name": "loop opening", "seconds": 50}],
    ]
    r = ss.shares(rows)
    assert r["builds"] == 3
    assert r["groups"] == {"construction": 0.2, "improvement loop": 0.6, "finish": 0.1}
    assert r["steps"]["skeleton applied"]["median_share"] == 0.2
    assert r["steps"]["loop pass <N>"] == {"median_share": 0.8, "builds": 1, "median_seconds": 80}
    assert r["steps"]["config (final lanes)"]["builds"] == 2
    assert r["unmapped"] == []


def test_unmapped_listed_and_counted():
    r = ss.shares([[{"name": "skeleton applied", "seconds": 50}, {"name": "mystery", "seconds": 50}]])
    assert r["unmapped"] == ["mystery"]
    assert r["steps"]["unmapped"]["median_share"] == 0.5
    assert r["groups"]["construction"] == 0.5


def test_load_rows(tmp_path):
    (tmp_path / "rows").mkdir()
    (tmp_path / "rows" / "a.json").write_text(json.dumps({"stages": [{"name": "anoint", "seconds": 1}]}))
    (tmp_path / "rows" / "b.json").write_text(json.dumps({}))
    assert len(ss.load_rows(tmp_path)) == 1
