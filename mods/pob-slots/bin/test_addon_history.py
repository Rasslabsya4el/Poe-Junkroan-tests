"""Plain-python check of the runs card history (#587): python test_history.py"""
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect  # noqa: E402,F401  (the generic collector loads the add-on)

addon = collect.addon()  # the project's add-on: the subject of this file


def job(**kw):
    base = dict(id="j1", tag="gate", argv=["benchmark.py", "--tag", "gate"], cmd="python scripts/benchmark.py --tag gate",
                workers=1, state="done", run_dir=None, start_ts="2026-10-05T10:20:30+00:00",
                end_ts="2026-10-06T10:18:20+00:00")
    base.update(kw)
    return SimpleNamespace(**base)


def test_history(monkeypatch):
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        monkeypatch.setattr(addon, "BENCH", root / "benchmark")
        monkeypatch.setattr(addon, "HISTORY_CACHE", root / "history.json")
        d = addon.BENCH / "20261005-1220-gate"
        (d / "rows").mkdir(parents=True)
        (d / "args.json").write_text(json.dumps({"slugs": ["spark"], "seed": 4, "seeds": 2}))
        (d / "rows" / "spark-s4.json").write_text(json.dumps({"ok": True, "seconds": 60}))
        # The run_dir names a deleted snapshot: the same folder name under artifacts/benchmark holds it.
        j = job(run_dir=str(root / "snapshots" / "x" / "20261005-1220-gate"))
        assert addon.job_dir(j) == d
        # No run_dir: a folder of its tag made while it ran is its own; one made before it is not.
        assert addon.job_dir(job()) == d
        assert addon.job_dir(job(start_ts="2026-10-06T08:00:00+00:00")) is None
        assert addon.job_dir(job(start_ts=None)) is None
        gone = job(id="j2", tag="old", argv=["benchmark.py", "--tag", "old"])
        counts = addon._history_counts([j, gone])
        assert counts == {"j1": {"dir": str(d), "done": 1, "total": 2}}, counts
        cache = json.loads(addon.HISTORY_CACHE.read_text())
        assert cache["j2"] == {"dir": None}, cache
        # Cached: the next pull reads no row file (a changed row would show otherwise).
        (d / "rows" / "spark-s5.json").write_text(json.dumps({"ok": True}))
        assert addon._history_counts([j, gone])["j1"]["done"] == 1


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
