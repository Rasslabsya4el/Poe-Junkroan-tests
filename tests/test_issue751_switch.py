"""#751 unit 3: `runs.py fillers <host> on|off` writes only `<host>.fillers` in the hosts file."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from junkroan.runs import hosts as runs_hosts

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "config" / "hosts.json"


def _run(cfg: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, JUNKROAN_HOSTS_CONFIG=str(cfg), JUNKROAN_HOST_SWITCHES_FILE=str(cfg.with_name("host_switches.json")))
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "runs.py"), "fillers", *args],
        capture_output=True, text=True, env=env, timeout=60, cwd=str(ROOT),
    )


@pytest.fixture
def cfg(tmp_path):
    path = tmp_path / "hosts.json"
    path.write_bytes(REAL.read_bytes())
    return path


def _switches(cfg: Path):
    return json.loads(cfg.with_name("host_switches.json").read_text(encoding="utf-8"))


# #861: the contract moved: the switch lands in the untracked switches file, the hosts file stays byte-identical.
def test_round_trip_writes_only_the_switches_file(cfg):
    before_bytes = REAL.read_bytes()
    assert _run(cfg, "pc", "on").stdout.strip() == "pc fillers on"
    assert _switches(cfg) == {"pc": {"fillers": True}}
    assert _run(cfg, "pc", "off").stdout.strip() == "pc fillers off"
    assert _switches(cfg) == {"pc": {"fillers": False}}
    assert cfg.read_bytes() == before_bytes == REAL.read_bytes()


def test_current_prints_without_writing(cfg):
    runs_hosts.set_fillers("laptop", True, cfg.with_name("host_switches.json"))
    raw = cfg.read_bytes()
    one = _run(cfg, "laptop", "--current")
    assert one.returncode == 0 and one.stdout.strip() == "laptop fillers on"
    both = _run(cfg, "--current")
    assert both.stdout.splitlines()[:2] == ["pc fillers off", "laptop fillers on"]
    assert cfg.read_bytes() == raw


def test_unknown_host_exits_nonzero(cfg):
    raw = cfg.read_bytes()
    assert _run(cfg, "mars", "on").returncode != 0
    assert _run(cfg, "mars", "--current").returncode != 0
    assert cfg.read_bytes() == raw
    assert not cfg.with_name("host_switches.json").exists()


def test_real_config_has_both_hosts_off():
    doc = json.loads(REAL.read_text(encoding="utf-8"))
    assert all(e.get("fillers") is not True for e in doc.values())
