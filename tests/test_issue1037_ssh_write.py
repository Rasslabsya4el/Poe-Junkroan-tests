"""#1037 unit 2: remote job-store writes over ssh are one function and one quote helper in `runs/hosts.py`.

(a) a grep over the four files that used to carry their own quote helper finds exactly one definition
(`hosts.quote_ps_arg`) and one `''` doubling; (b) the script each former site sends is byte-identical to
the one the base commit (fc3ada51) produced: `tests/fixtures/issue1037_old_ssh_scripts.json` holds those
scripts, captured from the base commit before the change. No real ssh: `run_on_host` / `run_bounded` are
replaced.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from junkroan.runs import daemon, hosts, rebalance
from junkroan.runs.ssh_transport import build_ssh_argv
from junkroan.runs.store import Store

ROOT = Path(__file__).resolve().parents[1]
OLD = json.loads((ROOT / "tests" / "fixtures" / "issue1037_old_ssh_scripts.json").read_text(encoding="utf-8"))
FILES = [ROOT / "src" / "junkroan" / "runs" / "hosts.py", ROOT / "src" / "junkroan" / "runs" / "daemon.py",
         ROOT / "src" / "junkroan" / "runs" / "rebalance.py", ROOT / "scripts" / "runs.py"]

CFG = {
    "ssh": "laptop-1037", "repo_path": "C:\\Coding\\poe-junkroan-v2", "daemon_repo_path": "C:\\Coding\\poe-junkroan-v2-daemon",
    "modes": {"normal": {"day": {"hours": [0, 24], "total": 3, "others": 1, "min_free_ram_gb": 4}, "pob_priority": "Normal"}},
}


@pytest.fixture
def sent(monkeypatch) -> list[str]:
    scripts: list[str] = []

    def fake(host_cfg, script):
        scripts.append(script)
        return subprocess.CompletedProcess([], 0, stdout="OK\nj-new\n", stderr="")

    monkeypatch.setattr(hosts, "run_on_host", fake)
    return scripts


def test_no_other_quote_helper_in_the_four_files() -> None:
    helper_def = re.compile(r"^[ \t]*def[ \t]+_?(quote\w*|ps_quote\w*|q)[ \t]*\(", re.MULTILINE)
    doubling = re.compile(r"""\.replace\(\s*["']'["']\s*,\s*["']''["']\s*\)""")
    defs = {f.name: helper_def.findall(f.read_text(encoding="utf-8")) for f in FILES}
    assert defs["hosts.py"] == ["quote_ps_arg"]
    assert defs["daemon.py"] == [] and defs["rebalance.py"] == [] and defs["runs.py"] == []
    assert sum(len(doubling.findall(f.read_text(encoding="utf-8"))) for f in FILES) == 1


def test_mark_posted_script_is_the_old_one(sent) -> None:
    assert hosts.mark_posted_on_host(CFG, "laptop", "j-20261014-001") is True
    assert sent == [OLD["mark_posted"]]


def test_mark_anomaly_taken_script_is_the_old_one(sent) -> None:
    assert hosts.mark_anomaly_taken_on_host(CFG, "laptop", "stuck:o'brien") is True
    assert sent == [OLD["anomaly_taken"]]


def test_mark_run_issue_script_is_the_old_one(sent) -> None:
    assert hosts.mark_run_issue_on_host(CFG, "laptop", "j-20261014-001", 42) is True
    assert sent == [OLD["run_issue"]]


def test_the_mark_scripts_still_send_no_junkroan_host(sent) -> None:
    hosts.mark_posted_on_host(CFG, "laptop", "j-1")
    hosts.mark_anomaly_taken_on_host(CFG, "laptop", "k")
    hosts.mark_run_issue_on_host(CFG, "laptop", "j-1", 1)
    assert not any("JUNKROAN_HOST" in s for s in sent)


def test_apply_mode_ssh_script_is_the_old_one(sent, tmp_path) -> None:
    hosts.apply_mode("laptop", "normal", config={"laptop": CFG}, events_file=tmp_path / "events.jsonl")
    assert sent == [OLD["apply_mode"]]


def test_daemon_ticket_stop_script_is_the_old_one(sent) -> None:
    assert daemon._remote_ticket_stop_over_ssh(CFG, "laptop", "j-20261014-001", "stop", "it's stuck") is True
    assert sent == [OLD["daemon_stop"]]


def test_rebalance_move_script_is_the_old_one(sent, tmp_path) -> None:
    job = Store(tmp_path / "jobs.jsonl").submit(host="pc", priority="P2", tag="t1", workers=1, cmd="python x.py --a 'b'", issue=5)
    assert rebalance.submit_moved_on_host(CFG, "laptop", job, "pc") == "j-new"
    assert sent == [OLD["rebalance_move"]]


def test_the_ssh_argv_is_the_old_one(monkeypatch) -> None:
    """Through the real `run_on_host` (only `run_bounded` replaced): the argv is the transport's, built from the old script."""

    argvs: list[list[str]] = []

    def fake_bounded(argv, **kwargs):
        argvs.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(hosts, "run_bounded", fake_bounded)
    monkeypatch.setattr(hosts.GUARD, "down", lambda key: False)
    assert hosts.mark_posted_on_host(CFG, "laptop", "j-20261014-001") is True
    assert argvs == [build_ssh_argv(CFG, OLD["mark_posted"])]


def test_write_over_ssh_adds_only_what_is_asked(sent) -> None:
    hosts.write_over_ssh(CFG, "do-it")
    hosts.write_over_ssh(CFG, "do-it", repo_path="C:\\r", host="laptop", pythonpath="src")
    assert sent == ["do-it", "$env:JUNKROAN_HOST = 'laptop'; $env:PYTHONPATH = 'src'; cd 'C:\\r'; do-it"]
