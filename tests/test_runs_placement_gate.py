"""#642 unit 5: `submit --host auto` keeps a gate-reading command off a host without the newest gate (no PoB, no ssh)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from junkroan.runs import placement

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("runs_cli_642_u5", ROOT / "scripts" / "runs.py")
runs = importlib.util.module_from_spec(_spec)
sys.modules["runs_cli_642_u5"] = runs
_spec.loader.exec_module(runs)

NEWEST = "20261005-1220-gate-20261005"
OLDER = "20260928-1000-gate-20260928"
PROBE = "python scripts/probe_issue632_rage.py"
STATES = {"pc": 1, "laptop": 6}


def place(cmd, newest, present_map):
    states, dropped = placement.gate_filter(STATES, cmd, newest, lambda h: set(present_map.get(h, ())))
    return placement.pick_host(1, states), dropped


def test_laptop_without_gate_is_dropped():
    assert place(PROBE, NEWEST, {}) == ("pc", ["laptop"])


def test_laptop_with_newest_gate_wins():
    assert place(PROBE, NEWEST, {"laptop": [NEWEST]}) == ("laptop", [])


def test_laptop_with_only_older_gate_is_dropped():
    assert place(PROBE, NEWEST, {"laptop": [OLDER]}) == ("pc", ["laptop"])


def test_no_newest_gate_means_pc():
    assert place(PROBE, None, {"laptop": [NEWEST]}) == ("pc", ["laptop"])


@pytest.mark.parametrize("present", [{}, {"laptop": [NEWEST]}])
def test_command_without_gate_is_unchanged(present):
    assert place("python scripts/benchmark.py --set smoke", NEWEST, present) == ("laptop", [])


def _submit(tmp_path, monkeypatch, newest, present, capsys, cmd=("echo", "scripts/probe_x.py")):
    calls = []
    monkeypatch.setattr(runs.runs_placement, "gather_states", lambda **kw: dict(STATES))
    monkeypatch.setattr(runs.runs_gates, "newest_gate", lambda d: newest)
    monkeypatch.setattr(runs.runs_gates, "gates_present", lambda h: set(present.get(h, ())))
    monkeypatch.setattr(runs, "_submit_remote", lambda host, f, c: calls.append((host, f)) or 0)
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    runs.main(["--store", str(tmp_path / "jobs.jsonl"), "submit", "--issue", "1", "--priority", "P1",
               "--again", "--", *cmd])
    return calls, capsys.readouterr().err


def test_submit_wiring_message_and_flags(tmp_path, monkeypatch, capsys):
    calls, err = _submit(tmp_path, monkeypatch, NEWEST, {}, capsys)
    assert f"submit: placed on pc; laptop lacks gate {NEWEST}" in err
    assert calls == [] or calls[0][0] != "laptop"
    _, err = _submit(tmp_path, monkeypatch, None, {}, capsys)
    assert "submit: placed on pc; laptop lacks gate none" in err


def test_submit_wiring_laptop_with_gate(tmp_path, monkeypatch, capsys):
    calls, err = _submit(tmp_path, monkeypatch, NEWEST, {"laptop": [NEWEST]}, capsys)
    assert calls[0][0] == "laptop" and "--host-auto-placed" in calls[0][1] and "lacks" not in err
