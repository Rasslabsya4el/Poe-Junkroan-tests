"""#642 unit 6b: `submit --host auto` places a command that names an artifacts folder (`replay_dirs`: `--builds`
under `artifacts/benchmark/<dir>`, `--against` under `artifacts/replay/<dir>`) on the laptop only when the laptop
holds each named folder; otherwise on pc, stderr `submit: placed on pc; laptop lacks <dir>`. No PoB, no ssh."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from junkroan.runs import placement

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("runs_cli_642_u6b", ROOT / "scripts" / "runs.py")
runs = importlib.util.module_from_spec(_spec)
sys.modules["runs_cli_642_u6b"] = runs
_spec.loader.exec_module(runs)

NEWEST = "20261005-1220-gate-20261005"  # the newest `-gate-` folder: the laptop holds it, the core folder below it does not
CORE = "20261013-0101-P2-core-3"
REPLAY = "20261012-2300-replay-7"
STATES = {"pc": 1, "laptop": 6}  # the laptop has the larger room
BUILDS_CMD = ("python", "scripts/replay_bench.py", "--builds", f"artifacts/benchmark/{CORE}/x.pob.txt")
AGAINST_CMD = ("python", "scripts/replay_bench.py", "--against", f"artifacts/replay/{REPLAY}")


def _submit(tmp_path, monkeypatch, capsys, cmd, present):
    calls = []
    monkeypatch.setattr(runs.runs_placement, "gather_states", lambda **kw: dict(STATES))
    monkeypatch.setattr(runs.runs_gates, "newest_gate", lambda d: NEWEST)
    monkeypatch.setattr(runs.runs_gates, "gates_present", lambda h: set(present.get(h, ())))
    monkeypatch.setattr(runs, "_submit_remote", lambda host, f, c: calls.append((host, f)) or 0)
    monkeypatch.setattr(runs.runs_gates, "ROOT", tmp_path)  # the folder of --against is looked up here
    (tmp_path / "artifacts" / "replay" / REPLAY).mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    runs.main(["--store", str(tmp_path / "jobs.jsonl"), "submit", "--issue", "1", "--priority", "P1",
               "--again", "--", *cmd])
    return calls, capsys.readouterr().err


# row 5: --builds under artifacts/benchmark/<dir>

def test_row5_builds_folder_absent_on_laptop_places_on_pc(tmp_path, monkeypatch, capsys):
    calls, err = _submit(tmp_path, monkeypatch, capsys, BUILDS_CMD, {"laptop": [NEWEST]})
    assert "submit: placed on pc; laptop lacks benchmark/20261013-0101-P2-core-3" in err
    assert calls == []


def test_row5_builds_folder_absent_and_no_gate_places_on_pc(tmp_path, monkeypatch, capsys):
    calls, err = _submit(tmp_path, monkeypatch, capsys, BUILDS_CMD, {})
    assert "submit: placed on pc; laptop lacks benchmark/20261013-0101-P2-core-3" in err
    assert calls == []


def test_row5_builds_folder_present_on_laptop_places_on_laptop(tmp_path, monkeypatch, capsys):
    calls, err = _submit(tmp_path, monkeypatch, capsys, BUILDS_CMD, {"laptop": [CORE]})
    assert calls[0][0] == "laptop" and "--host-auto-placed" in calls[0][1]
    assert "lacks" not in err


# row 6: --against under artifacts/replay/<dir>

def test_row6_against_folder_absent_on_laptop_places_on_pc(tmp_path, monkeypatch, capsys):
    calls, err = _submit(tmp_path, monkeypatch, capsys, AGAINST_CMD, {"laptop": [NEWEST]})
    assert f"submit: placed on pc; laptop lacks replay/{REPLAY}" in err
    assert calls == []


def test_row6_against_folder_present_on_laptop_places_on_laptop(tmp_path, monkeypatch, capsys):
    calls, err = _submit(tmp_path, monkeypatch, capsys, AGAINST_CMD, {"laptop": [f"replay/{REPLAY}"]})
    assert calls[0][0] == "laptop" and "--host-auto-placed" in calls[0][1]
    assert "lacks" not in err


# the pure rule: every named folder must be held

def test_gate_filter_keeps_laptop_only_with_every_named_folder():
    present = {"laptop": {CORE}}
    dirs = [f"benchmark/{CORE}", "replay/20261012-2300-replay-7"]
    states, dropped = placement.gate_filter(STATES, BUILDS_CMD, NEWEST, lambda h: present.get(h, set()), dirs=dirs)
    assert dropped == ["laptop"] and "laptop" not in states
    present["laptop"] = {CORE, f"replay/{REPLAY}"}
    states, dropped = placement.gate_filter(STATES, BUILDS_CMD, NEWEST, lambda h: present.get(h, set()), dirs=dirs)
    assert dropped == [] and "laptop" in states
