"""#680: the collector's merge-line reading.

    python -m pytest -q bin/test_merge_status.py   (from the repo root, like the other bin tests)

The command's JSON (raw seconds) gains human durations; a repo without `merge-status` yet reads as
{"missing": True}, a failing command raises (the card shows the error line).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import collect  # noqa: E402

TICKET_JSON = """{"at": "2026-10-09T19:46:10",
 "running": {"branches": ["orch-677"], "issues": [677], "phase": "suite",
             "started": "2026-10-09T19:38:32", "percent": 62, "tests_done": 2647, "tests_total": 4270,
             "failed": 0, "eta_s": 140, "workers": 6, "suite_out": "x.out"},
 "waiting": [{"branch": "orch-621", "issues": [621], "position": 1, "queued": "2026-10-09T19:40:01",
              "waited_s": 369, "eta_start_s": 140}],
 "landed": [{"branch": "orch-674", "issues": [674], "queued": "a", "landed": "b",
             "queued_to_land_s": 302, "rc": 0}]}"""


def fake_run(rc: int, out: str = "", err: str = ""):
    def run(argv, **kw):
        assert argv[-2:] == ["merge-status", "--json"] and kw["cwd"] == str(collect.REPO)
        assert kw["creationflags"] == collect.NO_WINDOW
        return subprocess.CompletedProcess(argv, rc, out, err)
    return run


def test_ticket_example_gets_human_durations(monkeypatch):
    monkeypatch.setattr(collect.subprocess, "run", fake_run(0, TICKET_JSON))
    m = collect.merge_status()
    r = m["running"]
    assert (r["percent"], r["tests_done"], r["tests_total"], r["eta_s"]) == (62, 2647, 4270, 140)
    assert r["eta_h"] == collect.hd(140) and r["elapsed_h"] == collect.hd(458)
    w = m["waiting"][0]
    assert w["waited_h"] == collect.hd(369) and w["eta_start_h"] == collect.hd(140)
    assert m["landed"][0]["took_h"] == collect.hd(302)
    for h in (r["eta_h"], r["elapsed_h"], w["waited_h"], m["landed"][0]["took_h"]):
        assert not h.endswith(" s") or int(h.split()[0]) < 90, h


def test_idle_line(monkeypatch):
    monkeypatch.setattr(collect.subprocess, "run", fake_run(0, '{"at": "2026-10-09T19:50:00", "running": null}'))
    m = collect.merge_status()
    assert m["running"] is None and m["waiting"] == [] and m["landed"] == []


def test_command_not_on_main(monkeypatch):
    err = "agentops: error: argument command: invalid choice: 'merge-status' (choose from 'worker', ...)"
    monkeypatch.setattr(collect.subprocess, "run", fake_run(2, err=err))
    assert collect.merge_status() == {"missing": True}


def test_command_fails(monkeypatch):
    monkeypatch.setattr(collect.subprocess, "run", fake_run(1, err="Traceback ...\nKeyError: 'x'"))
    with pytest.raises(RuntimeError, match="KeyError"):
        collect.merge_status()
