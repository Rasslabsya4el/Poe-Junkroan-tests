"""scripts/runs.py mode --who / --current (issue #367). Fakes only: apply_mode, the tree killer and the
modes file are all redirected to tmp paths; nothing touches a real budget."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import runs  # noqa: E402
from junkroan.runs import hosts as runs_hosts  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402


def _setup(tmp_path, monkeypatch):
    monkeypatch.setenv("JUNKROAN_MODES_FILE", str(tmp_path / "modes.json"))
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    monkeypatch.setenv("JUNKROAN_POB_BUDGET", str(tmp_path / "budget.json"))
    monkeypatch.setattr(runs, "TREE_KILLER", lambda pid: True)
    applied: list[tuple] = []

    def fake_apply(host, mode, **kw):
        applied.append((host, mode))
        cfg = runs_hosts.load_hosts_config()
        runs_hosts.write_budget_bom_free(tmp_path / "budget.json", runs_hosts.mode_budget(cfg[host], host, mode))
        return {"priority": "x", "transport": "local"}

    monkeypatch.setattr(runs_hosts, "apply_mode", fake_apply)
    return tmp_path / "jobs.jsonl", applied


def test_who_names_the_stopper_on_mode_off(tmp_path, monkeypatch) -> None:
    path, _ = _setup(tmp_path, monkeypatch)
    store = Store(path)
    job = store.submit(host="pc", priority="P1", tag="a", cmd="echo hi")
    store.start(job.id, pid=77)
    assert runs.main(["--store", str(path), "mode", "pc", "off", "--who", "power-guard"]) == 0
    got = Store(path).get(job.id)
    assert got.state == "stopped" and got.reason == "stopped by power-guard"


def test_current_follows_the_last_applied_mode(tmp_path, monkeypatch, capsys) -> None:
    path, _ = _setup(tmp_path, monkeypatch)

    def current() -> str:
        capsys.readouterr()
        assert runs.main(["--store", str(path), "mode", "pc", "--current"]) == 0
        return capsys.readouterr().out

    assert current() == "unknown\n"  # no budget file, nothing recorded: not a guessed normal
    for mode in ("off", "play", "normal"):
        assert runs.main(["--store", str(path), "mode", "pc", mode]) == 0
        assert current() == f"{mode}\n"


def test_current_writes_nothing(tmp_path, monkeypatch, capsys) -> None:
    path, applied = _setup(tmp_path, monkeypatch)
    modes_file = tmp_path / "modes.json"
    assert runs.main(["--store", str(path), "mode", "pc", "play"]) == 0
    before = (modes_file.read_bytes(), modes_file.stat().st_mtime_ns)
    applied.clear()
    assert runs.main(["--store", str(path), "mode", "pc", "--current"]) == 0
    assert (modes_file.read_bytes(), modes_file.stat().st_mtime_ns) == before
    assert applied == []


def test_current_no_file_is_not_created(tmp_path, monkeypatch) -> None:
    path, _ = _setup(tmp_path, monkeypatch)
    assert runs.main(["--store", str(path), "mode", "pc", "--current"]) == 0
    assert not (tmp_path / "modes.json").exists()


def test_current_unknown_host_fails(tmp_path, monkeypatch, capsys) -> None:
    path, _ = _setup(tmp_path, monkeypatch)
    assert runs.main(["--store", str(path), "mode", "nosuchhost", "--current"]) != 0
    assert "unknown host" in capsys.readouterr().err


def test_timed_entry_still_expires_and_cli_entry_does_not(tmp_path, monkeypatch) -> None:
    from datetime import datetime, timedelta
    path, _ = _setup(tmp_path, monkeypatch)
    assert runs.main(["--store", str(path), "mode", "pc", "play"]) == 0
    assert runs_hosts.read_modes()["pc"] == {"mode": "play", "until": None}
    reverted = runs_hosts.revert_expired_modes(datetime.now() + timedelta(days=1))
    assert reverted == [] and runs_hosts.read_modes()["pc"]["mode"] == "play"


# -- remote `mode <host> off` runs the stop on that host over ssh (#73) ---------------------------

class _Result:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _capture_ssh(monkeypatch, result):
    calls: list[str] = []

    def fake_run(host_cfg, script):
        calls.append(script)
        return result

    monkeypatch.setattr(runs_hosts, "run_on_host", fake_run)
    return calls


def test_remote_off_runs_the_stop_on_the_host(tmp_path, monkeypatch, capsys) -> None:
    path, applied = _setup(tmp_path, monkeypatch)
    out = "j-x -> stopped (stopped by t)\nlaptop: stopped 1 running job(s)"
    calls = _capture_ssh(monkeypatch, _Result(0, out))
    assert runs.main(["--store", str(path), "mode", "laptop", "off", "--who", "t"]) == 0
    assert len(calls) == 1 and applied == []
    daemon = runs_hosts.daemon_repo_path(runs_hosts.load_hosts_config()["laptop"])
    # every argument is its own single-quoted PowerShell literal (_quote_ps_arg)
    for needle in ("'mode' 'laptop' 'off' '--local'", "'--who' 't'", daemon, "JUNKROAN_HOST"):
        assert needle in calls[0]
    assert capsys.readouterr().out.splitlines() == out.splitlines()
    assert runs_hosts.read_modes()["laptop"]["mode"] == "off"


def test_remote_off_failure_records_nothing(tmp_path, monkeypatch, capsys) -> None:
    path, applied = _setup(tmp_path, monkeypatch)
    _capture_ssh(monkeypatch, _Result(1, "", "ssh: no route"))
    assert runs.main(["--store", str(path), "mode", "laptop", "off"]) == 1
    assert capsys.readouterr().err.startswith("mode: laptop unreachable:")
    assert "laptop" not in runs_hosts.read_modes()


def test_remote_other_mode_still_uses_apply_mode(tmp_path, monkeypatch) -> None:
    path, applied = _setup(tmp_path, monkeypatch)
    calls = _capture_ssh(monkeypatch, _Result(0, ""))
    assert runs.main(["--store", str(path), "mode", "laptop", "browser"]) == 0
    assert applied == [("laptop", "browser")]
    assert not any("--local" in c for c in calls)
