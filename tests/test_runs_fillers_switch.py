"""#517: fillers are off unless the owner turns them on (`--fillers` or hosts.json `<host>.fillers`). PoB-free."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import runs  # noqa: E402
from junkroan.runs import fillers as fillers_mod  # noqa: E402


def test_fillers_switch() -> None:
    sw = fillers_mod.fillers_switch
    assert sw("pc", flag=True, hosts_reader=lambda: {})() is True
    assert sw("pc", flag=False, hosts_reader=lambda: {"pc": {"repo_path": "x"}})() is False
    assert sw("pc", flag=False, hosts_reader=lambda: {"pc": {"fillers": True}})() is True
    assert sw("laptop", flag=False, hosts_reader=lambda: {"pc": {"fillers": True}})() is False

    def boom():
        raise OSError("no file")
    assert sw("pc", flag=False, hosts_reader=boom)() is False


def _run_cli(monkeypatch, tmp_path: Path, extra: list[str], hosts: dict) -> dict:
    seen: dict = {}

    class FakeDaemon:
        def __init__(self, store, **kwargs):
            seen.update(kwargs)

        def budget(self):
            class B:
                total, period = 1, "day"

                def limit_for(self, role):
                    return 1

                def window(self):
                    return "0-24"
            return B()

        def run(self, **kwargs):
            return 0

    monkeypatch.setattr(runs.runs_daemon, "Daemon", FakeDaemon)
    monkeypatch.setattr(runs.runs_hosts, "daemon_status_path", lambda host: tmp_path / "status.json")
    monkeypatch.setattr(runs.runs_hosts, "load_hosts_config", lambda *a, **k: hosts)
    monkeypatch.setattr(runs.self_restart, "wait_for_predecessor", lambda *a, **k: None)
    rc = runs.main(["--store", str(tmp_path / "jobs.jsonl"), "daemon", "--host", "pc", "--no-keymaster",
                    "--no-self-restart", "--ticks", "1", *extra])
    assert rc == 0
    return seen


def test_cli_default_is_off(monkeypatch, tmp_path: Path) -> None:
    seen = _run_cli(monkeypatch, tmp_path, [], {"pc": {}})
    assert seen["fillers"].enabled() is False


def test_cli_fillers_flag_and_hosts_key_turn_it_on(monkeypatch, tmp_path: Path) -> None:
    assert _run_cli(monkeypatch, tmp_path, ["--fillers"], {"pc": {}})["fillers"].enabled() is True
    assert _run_cli(monkeypatch, tmp_path, [], {"pc": {"fillers": True}})["fillers"].enabled() is True


def test_cli_no_fillers_still_parses_and_forces_off(monkeypatch, tmp_path: Path) -> None:
    assert _run_cli(monkeypatch, tmp_path, ["--no-fillers"], {"pc": {"fillers": True}})["fillers"] is None
