"""#719 unit 2: the commit gate selects tests the way a merge does (rig of test_issue690_merge_select)."""

from __future__ import annotations

from pathlib import Path

from tests.test_agentops_merge import _git, _local_main_head
from tests.test_issue690_merge_select import ID_NEST, ID_PLAIN, ID_SPACE, Rig
from tools.agentops.merge import run_commit


def _commit_via_gate(rig: Rig, rel: str, content: str):
    (rig.checkout / rel).write_text(content, encoding="utf-8")
    return run_commit([rel], "change", cwd=rig.checkout, lock_path=rig.tmp / "merge.lock", lock_timeout=30,
                      suite_cmd=rig.cmd, suite_output_dir=rig.tmp / "out", merge_log_path=rig.log)


def test_a_selected_ids_run_and_the_log_carries_the_line(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    result = _commit_via_gate(rig, "src/a.py", "a = 2\n")
    assert result.ok, result.message
    (call,) = rig.calls()
    assert call["args"] == sorted([ID_PLAIN, ID_SPACE, ID_NEST])
    assert "tests" not in call["argv"] and any(a.startswith("@") for a in call["argv"])
    assert f"selected 3 of 50 tests (map {rig.c0[:8]})" in rig.log.read_text(encoding="utf-8")


def test_b_empty_selection_runs_no_pytest_and_lands(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    result = _commit_via_gate(rig, "docs/x.txt", "x\n")  # docs/*.md would skip the gate; a .txt needs it
    assert result.ok, result.message
    assert rig.calls() == []
    assert f"selected 0 of 50 tests (map {rig.c0[:8]})" in rig.log.read_text(encoding="utf-8")
    assert _git("rev-parse", "origin/main", cwd=rig.checkout).stdout.strip() == _local_main_head(rig.checkout)


def test_c_setting_off_is_todays_whole_command(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, select=False)
    result = _commit_via_gate(rig, "src/a.py", "a = 2\n")
    assert result.ok, result.message
    (call,) = rig.calls()
    assert call["argv"] == ["-m", "pytest", "tests", "-q", "-m", "not slow and not pob", "-rf"]
    assert "selected" not in rig.log.read_text(encoding="utf-8")


def test_d_failing_selected_test_is_red_and_main_returns_to_the_parent(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    rig.flag.write_text("fail", encoding="utf-8")
    before = _local_main_head(rig.checkout)
    result = _commit_via_gate(rig, "src/a.py", "a = 2\n")
    assert not result.ok and result.reason == "red-suite"
    assert _local_main_head(rig.checkout) == before
    assert _git("rev-parse", "origin/main", cwd=rig.checkout).stdout.strip() == before
    assert Path(rig.checkout / "src" / "a.py").read_text(encoding="utf-8") == "a = 2\n"
    assert f"selected 3 of 50 tests (map {rig.c0[:8]})" in rig.log.read_text(encoding="utf-8")
