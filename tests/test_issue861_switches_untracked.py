"""#861 unit 1: a host's own switches never touch a tracked file (`runs.py fillers` writes var/host_switches.json)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from junkroan.runs import hosts as runs_hosts
from junkroan.runs.fillers import fillers_switch

ROOT = Path(__file__).resolve().parents[1]
# JUNKROAN_TEST_REPO lets the red run point the CLI at an unmodified checkout.
CLI_ROOT = Path(os.environ.get("JUNKROAN_TEST_REPO", ROOT))
REAL = ROOT / "config" / "hosts.json"


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=60)


@pytest.fixture
def checkout(tmp_path):
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    (repo / "config" / "hosts.json").write_bytes(REAL.read_bytes())
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "fixture")
    switches = tmp_path / "var" / "host_switches.json"
    env = dict(os.environ, JUNKROAN_HOSTS_CONFIG=str(repo / "config" / "hosts.json"),
               JUNKROAN_HOST_SWITCHES_FILE=str(switches),
               PYTHONPATH=str(CLI_ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""))
    return repo, switches, env


def _cli(repo, env, *args):
    return subprocess.run([sys.executable, str(CLI_ROOT / "scripts" / "runs.py"), "fillers", *args],
                          capture_output=True, text=True, env=env, timeout=60, cwd=str(repo))


def test_fillers_flip_leaves_tracked_tree_clean(checkout):
    repo, switches, env = checkout
    for host in ("laptop", "pc"):
        for state in ("off", "on", "off"):
            assert _cli(repo, env, host, state).stdout.strip() == f"{host} fillers {state}"
    assert _git(repo, "status", "--porcelain").stdout.strip().splitlines() == []
    assert json.loads(switches.read_text(encoding="utf-8")) == {"laptop": {"fillers": False}, "pc": {"fillers": False}}
    assert _cli(repo, env, "laptop", "--current").stdout.strip() == "laptop fillers off"


def test_tracked_true_is_carried_over_then_untracked_wins(checkout, monkeypatch):
    repo, switches, env = checkout
    cfg_path = repo / "config" / "hosts.json"
    doc = json.loads(cfg_path.read_text(encoding="utf-8"))
    doc["laptop"]["fillers"] = True
    cfg_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    before = cfg_path.read_bytes()
    monkeypatch.setenv("JUNKROAN_HOSTS_CONFIG", str(cfg_path))
    monkeypatch.setenv("JUNKROAN_HOST_SWITCHES_FILE", str(switches))
    assert not switches.exists()
    assert fillers_switch("laptop", flag=False)() is True
    assert _cli(repo, env, "laptop", "--current").stdout.strip() == "laptop fillers on"
    assert _cli(repo, env, "laptop", "off").returncode == 0
    assert fillers_switch("laptop", flag=False)() is False
    assert cfg_path.read_bytes() == before


def test_set_fillers_never_opens_tracked_config_for_writing(checkout, monkeypatch):
    repo, switches, _ = checkout
    cfg_path = repo / "config" / "hosts.json"
    monkeypatch.setenv("JUNKROAN_HOSTS_CONFIG", str(cfg_path))
    monkeypatch.setenv("JUNKROAN_HOST_SWITCHES_FILE", str(switches))
    tracked = cfg_path.resolve()
    written = []
    real_write_text, real_write_bytes, real_open = Path.write_text, Path.write_bytes, Path.open

    def spy_text(self, *a, **k):
        written.append(self.resolve()); return real_write_text(self, *a, **k)

    def spy_bytes(self, *a, **k):
        written.append(self.resolve()); return real_write_bytes(self, *a, **k)

    def spy_open(self, mode="r", *a, **k):
        if any(c in mode for c in "wax+"):
            written.append(self.resolve())
        return real_open(self, mode, *a, **k)

    monkeypatch.setattr(Path, "write_text", spy_text)
    monkeypatch.setattr(Path, "write_bytes", spy_bytes)
    monkeypatch.setattr(Path, "open", spy_open)
    before = cfg_path.read_bytes()
    runs_hosts.set_fillers("laptop", False)
    assert switches.resolve() in written and tracked not in written
    assert cfg_path.read_bytes() == before
    with pytest.raises(runs_hosts.HostModeError):
        runs_hosts.set_fillers("mars", True)
