"""#755 rules 2 and 3: one test at a time on k > 1 workers; the whole-suite run lists its 25 slowest."""
from __future__ import annotations

import pytest

from tools.agentops import full_run, merge

CMD = 'python -m pytest tests -q -m "not slow and not pob" -rf'


def _built(monkeypatch, tmp_path, k):
    monkeypatch.setattr(merge, "resolve_suite_workers_probe", lambda: "probe")
    monkeypatch.setattr(merge, "_make_probe", lambda t, cwd: (lambda: f"workers {k}: x"))
    monkeypatch.setattr(merge, "_xdist_available", lambda interp, cwd: True)
    return merge._with_workers(CMD, True, tmp_path)[0]


def test_k5_has_n5_and_one_chunk_flag(monkeypatch, tmp_path):
    cmd = _built(monkeypatch, tmp_path, 5)
    assert " -n 5" in cmd and cmd.count("--maxschedchunk=1") == 1


def test_k1_has_neither_flag(monkeypatch, tmp_path):
    cmd = _built(monkeypatch, tmp_path, 1)
    assert " -n" not in cmd and "--maxschedchunk" not in cmd


def test_restart_5_to_3_keeps_exactly_one_chunk_flag(monkeypatch, tmp_path):
    cmd = merge._workers_cmd(_built(monkeypatch, tmp_path, 5), 3)
    assert " -n 3" in cmd and "-n 5" not in cmd and cmd.count("--maxschedchunk=1") == 1


def test_restart_5_to_1_drops_both(monkeypatch, tmp_path):
    cmd = merge._workers_cmd(_built(monkeypatch, tmp_path, 5), 1)
    assert " -n" not in cmd and "--maxschedchunk" not in cmd


def test_restart_from_plain_command_to_4_adds_one_chunk_flag():
    cmd = merge._workers_cmd(CMD, 4)
    assert " -n 4" in cmd and cmd.count("--maxschedchunk=1") == 1


def test_whole_suite_command_lists_25_slowest():
    assert "--durations=25" in full_run.TESTMON_FLAGS
