"""#578: run names `P<priority>-<#issue|core>[-<n>]` derived by `runs.py submit` (kind A, no PoB)."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import runs  # noqa: E402
from junkroan.runs.finished_tag import finished_run_dir  # noqa: E402
from junkroan.runs.run_name import derive_name, import_name, with_benchmark_tag  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402

TODAY = date(2026, 10, 6)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    monkeypatch.setattr(runs, "_today", lambda: TODAY)
    monkeypatch.setattr(runs, "finished_run_dir", lambda tag, root: None)
    path = tmp_path / "jobs.jsonl"

    def submit(*flags, cmd=("echo", "hi")):
        return runs.main(["--store", str(path), "submit", "--host", "pc", *flags, "--", *cmd])
    return Store(path), submit


def test_ticket_run_name_and_second_gets_suffix(env, capsys):
    store, submit = env
    assert submit("--issue", "575", "--priority", "P1", cmd=("echo", "a")) == 0
    assert submit("--issue", "575", "--priority", "P1", cmd=("echo", "b")) == 0
    assert submit("--issue", "575", "--priority", "P1", "--again", cmd=("echo", "a")) == 0
    assert [j.tag for j in store.jobs()] == ["P1-#575", "P1-#575-2", "P1-#575-3"]


def test_core_run_name_and_tag_in_command(env):
    store, submit = env
    assert submit("--no-issue", "--priority", "P2", cmd=("python", "scripts/benchmark.py", "--set", "core14", "--seeds", "3")) == 0
    job = store.jobs()[0]
    assert job.tag == "P2-core"
    assert job.cmd.endswith("--tag P2-core") and job.argv[-2:] == ("--tag", "P2-core")


def test_old_tag_in_benchmark_command_is_replaced(env):
    store, submit = env
    assert submit("--issue", "9", "--priority", "P1", cmd=("python", "scripts/benchmark.py", "--tag", "old", "--seeds", "1")) == 0
    assert submit("--issue", "9", "--priority", "P1", cmd=("python", "scripts/benchmark.py", "--tag=old", "--seeds", "2")) == 0
    a, b = store.jobs()
    assert a.argv == ("python", "scripts/benchmark.py", "--tag", "P1-#9", "--seeds", "1", "--workers", "auto")  # #700
    assert b.argv == ("python", "scripts/benchmark.py", "--tag=P1-#9-2", "--seeds", "2", "--workers", "auto")


def test_one_line_shell_command_form(env):
    store, submit = env
    assert submit("--issue", "9", "--priority", "P1", cmd=("python scripts/benchmark.py --tag old --workers 2 && echo done",)) == 0
    assert submit("--issue", "10", "--priority", "P1", cmd=("python scripts/benchmark.py --seeds 1",)) == 0
    a, b = store.jobs()
    assert a.cmd == "python scripts/benchmark.py --tag P1-#9 --workers 2 && echo done"
    assert b.cmd == "python scripts/benchmark.py --seeds 1 --workers auto --tag P1-#10"


def test_no_issue_with_non_core_command_refused(env, capsys):
    store, submit = env
    assert submit("--no-issue", "--priority", "P2", cmd=("python", "scripts/benchmark.py", "--set", "smoke")) == 2
    assert ("runs submit: a run without a ticket is only the weekly core run (core14 benchmark); "
            "name the issue with --issue N (#578)") in capsys.readouterr().err
    assert store.jobs() == []


def test_tag_flag_before_dashes_refused(env, capsys):
    store, submit = env
    assert submit("--issue", "1", "--priority", "P1", "--tag", "x") == 2
    err = capsys.readouterr().err
    assert "--tag is gone (#578)" in err and "put free text in --note" in err
    assert submit("--issue", "1", "--priority", "P1", "--tag=x") == 2


def test_status_shows_name_and_note(env, capsys):
    store, submit = env
    assert submit("--issue", "575", "--priority", "P1", "--note", "bench of the flask") == 0
    capsys.readouterr()
    assert runs.main(["--store", str(store.path), "status"]) == 0
    out = capsys.readouterr().out
    header, _, row = out.splitlines()[:3]
    assert header.rstrip().endswith("note")
    assert "P1-#575" in row and row.rstrip().endswith("bench of the flask")


def test_finished_run_dir_finds_derived_name(tmp_path):
    d = tmp_path / "artifacts" / "benchmark" / "20261006-1000-P1-#575"
    d.mkdir(parents=True)
    (d / "results.json").write_text("{}", encoding="utf-8")
    assert finished_run_dir("P1-#575", tmp_path) == d


def test_import_name_three_cases():
    assert import_name("python scripts/benchmark.py --set core14 --seeds 3", []) == "P2-core"
    assert import_name("python scripts/x.py --issue 575", []) == "P2-#575"
    assert import_name("python scripts/x.py --issue=575", ["P2-#575"]) == "P2-#575-2"
    assert import_name("python scripts/x.py", []) == "P2-untracked"


def test_derive_name_suffixes():
    assert derive_name("P1", 580, False, []) == "P1-#580"
    assert derive_name("P1", 580, False, ["P1-#580", "P1-#580-2"]) == "P1-#580-3"
    assert derive_name("P1", 580, False, ["P1-#580", "P1-#580-2", "P1-#580-5"]) == "P1-#580-6"
    assert derive_name("P2", None, True, []) == "P2-core"
    assert derive_name("P2", None, True, ["P2-core"]) == "P2-core-2"
    assert derive_name("P1", 575, False, ["P1-#57", "P1-#5750"]) == "P1-#575"


def test_old_dated_names_are_not_the_same_base():
    assert derive_name("P1", 580, False, ["P1-#580-06.10-2"]) == "P1-#580"
    assert derive_name("P2", None, True, ["P2-core-06.10"]) == "P2-core"


def test_with_benchmark_tag_leaves_other_commands():
    assert with_benchmark_tag(["echo", "--tag", "x"], "N") == ["echo", "--tag", "x"]
    assert with_benchmark_tag("echo --tag x", "N") == "echo --tag x"
