"""`current_mode` reads the budget in force on the host itself (issue #380). Fakes only: no ssh, no PoB,
no live var/ (modes.json isolated by the autouse fixture, the budget by JUNKROAN_POB_BUDGET / budget_path)."""

from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import runs  # noqa: E402
from junkroan.runs import hosts as runs_hosts  # noqa: E402


def _budget(host: str, mode: str, config=None) -> dict:
    cfg = config or runs_hosts.load_hosts_config()
    return runs_hosts.mode_budget(cfg[host], host, mode)


def test_row1_laptop_browser_applied_locally_reads_back_browser(tmp_path, monkeypatch, capsys):
    budget_file = tmp_path / "budget.json"
    monkeypatch.setenv("JUNKROAN_HOST", "laptop")
    monkeypatch.setenv("JUNKROAN_POB_BUDGET", str(budget_file))
    monkeypatch.setattr(runs_hosts, "find_pob_pids", lambda: [])
    monkeypatch.setattr(runs_hosts, "set_priority_class", lambda pids, prio: [])
    runs_hosts.apply_mode("laptop", "browser", events_file=tmp_path / "events.jsonl", local=True)
    assert runs_hosts.read_modes() == {}  # nothing recorded: the budget alone must answer
    assert runs_hosts.current_mode("laptop", budget_path=budget_file) == "browser"
    assert runs.main(["--store", str(tmp_path / "jobs.jsonl"), "mode", "laptop", "--current"]) == 0
    assert capsys.readouterr().out == "browser\n"


def test_cli_current_local_flag_reads_the_budget(tmp_path, monkeypatch, capsys):
    budget_file = tmp_path / "budget.json"
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    monkeypatch.setenv("JUNKROAN_POB_BUDGET", str(budget_file))
    runs_hosts.write_budget_bom_free(budget_file, _budget("laptop", "browser"))
    store = str(tmp_path / "jobs.jsonl")
    monkeypatch.setattr(runs_hosts, "run_on_host", lambda cfg, script: _reply("", 1))  # the PC's file is not the laptop's
    assert runs.main(["--store", store, "mode", "laptop", "--current"]) == 0
    assert capsys.readouterr().out == "unknown\n"
    assert runs.main(["--store", store, "mode", "laptop", "--current", "--local"]) == 0
    assert capsys.readouterr().out == "browser\n"


def test_row2_remote_apply_script_budget_reads_back_browser(tmp_path, monkeypatch):
    calls: list[str] = []

    def fake_run_on_host(host_cfg, script):
        calls.append(script)
        return subprocess.CompletedProcess(args=["ssh"], returncode=0, stdout="OK", stderr="")

    monkeypatch.setattr(runs_hosts, "run_on_host", fake_run_on_host)
    runs_hosts.apply_mode("laptop", "browser", events_file=tmp_path / "events.jsonl")
    encoded = re.search(r"FromBase64String\('([^']+)'\)", calls[0]).group(1)
    budget_file = tmp_path / "budget.json"
    budget_file.write_bytes(base64.b64decode(encoded))
    assert runs_hosts.current_mode("laptop", local=True, budget_path=budget_file) == "browser"


def test_empty_modes_json_and_matching_budget_is_not_normal(tmp_path):
    budget_file = tmp_path / "budget.json"
    runs_hosts.write_budget_bom_free(budget_file, _budget("laptop", "browser"))
    assert runs_hosts.current_mode("laptop", local=True, budget_path=budget_file) == "browser"


def test_unknown_when_nothing_says(tmp_path, monkeypatch):
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    budget_file = tmp_path / "budget.json"
    # missing budget file
    assert runs_hosts.current_mode("laptop", local=True, budget_path=budget_file) == "unknown"
    # a budget matching no mode
    runs_hosts.write_budget_bom_free(budget_file, {"day": {"hours": [0, 24], "total": 99, "others": 0, "min_free_ram_gb": 1}, "strict_reserve": True})
    assert runs_hosts.current_mode("laptop", local=True, budget_path=budget_file) == "unknown"
    # unreadable budget file
    budget_file.write_text("{not json", encoding="utf-8")
    assert runs_hosts.current_mode("laptop", local=True, budget_path=budget_file) == "unknown"
    # another machine, its file unreadable over ssh
    monkeypatch.setattr(runs_hosts, "run_on_host", lambda cfg, script: _reply("", 1))
    assert runs_hosts.current_mode("laptop", budget_path=budget_file) == "unknown"


def test_other_machine_without_ssh_returns_the_recorded_entry(monkeypatch):
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    config = json.loads(json.dumps(runs_hosts.load_hosts_config()))
    config["laptop"].pop("ssh", None)
    runs_hosts.record_mode("laptop", "off")
    assert runs_hosts.current_mode("laptop", config=config) == "off"


def _reply(stdout: str, code: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["ssh"], returncode=code, stdout=stdout, stderr=stderr)


def test_remote_reads_the_laptop_budget_over_ssh(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    scripts: list[str] = []

    def fake(cfg, script):
        scripts.append(script)
        return _reply(json.dumps(_budget("laptop", "normal")))

    monkeypatch.setattr(runs_hosts, "run_on_host", fake)
    assert runs_hosts.current_mode("laptop") == "normal"
    repo_path = runs_hosts.load_hosts_config()["laptop"]["repo_path"]
    assert f"{repo_path}\\var\\machine_budget.json" in scripts[0]
    assert runs.main(["--store", str(tmp_path / "jobs.jsonl"), "mode", "laptop", "--current"]) == 0
    assert capsys.readouterr().out == "normal\n"


@pytest.mark.parametrize("failure", ["rc255", "timeout"])
def test_remote_unreachable_is_rc1_on_stderr(tmp_path, monkeypatch, capsys, failure):
    monkeypatch.setenv("JUNKROAN_HOST", "pc")

    def fake(cfg, script):
        if failure == "timeout":
            raise subprocess.TimeoutExpired("ssh", 120)
        return _reply("", 255, "ssh: connect to host timed out")

    monkeypatch.setattr(runs_hosts, "run_on_host", fake)
    with pytest.raises(runs_hosts.HostUnreachable):
        runs_hosts.current_mode("laptop")
    assert runs.main(["--store", str(tmp_path / "jobs.jsonl"), "mode", "laptop", "--current"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("mode: laptop unreachable")


@pytest.mark.parametrize("reply", [_reply("", 1, "no such file"), _reply("{not json")])
def test_remote_bad_reply_is_unknown(monkeypatch, reply):
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    monkeypatch.setattr(runs_hosts, "run_on_host", lambda cfg, script: reply)
    assert runs_hosts.current_mode("laptop") == "unknown"


def test_ambiguous_budget_prefers_the_recorded_mode(tmp_path):
    config = json.loads(json.dumps(runs_hosts.load_hosts_config()))
    config["laptop"]["modes"]["twin"] = json.loads(json.dumps(config["laptop"]["modes"]["browser"]))
    budget_file = tmp_path / "budget.json"
    runs_hosts.write_budget_bom_free(budget_file, _budget("laptop", "browser", config))
    kw = dict(config=config, local=True, budget_path=budget_file)
    assert runs_hosts.current_mode("laptop", **kw) == "unknown"
    runs_hosts.record_mode("laptop", "twin")
    assert runs_hosts.current_mode("laptop", **kw) == "twin"


def test_unknown_host_still_raises():
    with pytest.raises(runs_hosts.HostModeError):
        runs_hosts.current_mode("nosuch")
