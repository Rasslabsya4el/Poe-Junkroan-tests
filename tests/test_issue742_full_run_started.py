"""The merge status reads the `started` a full run writes (and the older space form)."""
from __future__ import annotations

import json
import os
import time

from tools.agentops import full_run, merge_status as ms

LINE = "." * 72
CUT = "bringing up nodes...\n\n" + "".join(f"{LINE} [{p:3d}%]\n" for p in (1, 3, 5, 20, 40, 62))


def _lock_9_min_ago(root, monkeypatch):
    real = full_run._iso
    monkeypatch.setattr(full_run, "_iso", lambda t=None: real(time.time() - 540))
    assert full_run.try_lock(root)
    (root / "var" / "agentops" / "full_run").mkdir(exist_ok=True)


def test_row1_elapsed_and_text_from_the_lock_full_run_wrote(tmp_path, monkeypatch):
    _lock_9_min_ago(tmp_path, monkeypatch)
    monkeypatch.setattr(ms, "_birth", lambda p: None)  # #764: the out file's birth would be now; this row reads the lock
    (tmp_path / "var" / "agentops" / "full_run" / "bbbb2222.out").write_text(CUT, encoding="utf-8")
    f = ms.collect(tmp_path)["full_run"]
    assert abs(f["elapsed_s"] - 540) <= 2
    assert "running 9 min" in ms.render_text({"running": None, "full_run": f, "waiting": [], "landed": []})


def test_row2_out_older_than_started_shows_nothing_of_the_earlier_run(tmp_path, monkeypatch):
    out = tmp_path / "var" / "agentops" / "full_run"
    out.mkdir(parents=True)
    old = out / "aaaa1111.out"
    old.write_text(CUT, encoding="utf-8")
    past = time.time() - 3600
    os.utime(old, (past, past))
    _lock_9_min_ago(tmp_path, monkeypatch)
    f = ms.collect(tmp_path)["full_run"]
    assert f["out"] is None and f["percent"] is None and f["tests_done"] is None


def test_row3_unparsable_started_prints_a_question_mark(tmp_path):
    base = tmp_path / "var" / "agentops"
    base.mkdir(parents=True)
    (base / "full_run.lock").write_text(json.dumps({"pid": os.getpid(), "started": "garbage"}), encoding="utf-8")
    f = ms.collect(tmp_path)["full_run"]
    assert f["elapsed_s"] is None
    text = ms.render_text({"running": None, "full_run": f, "waiting": [], "landed": []})
    assert "running ?" in text and "running 0 s" not in text


def test_the_older_space_form_parses_too(tmp_path):
    base = tmp_path / "var" / "agentops"
    base.mkdir(parents=True)
    s = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 540))
    (base / "full_run.lock").write_text(json.dumps({"pid": os.getpid(), "started": s}), encoding="utf-8")
    assert abs(ms.collect(tmp_path)["full_run"]["elapsed_s"] - 540) <= 2
