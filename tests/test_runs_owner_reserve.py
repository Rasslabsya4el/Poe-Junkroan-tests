"""The owner's reservation record in var/modes.json (#621 unit 1, no PoB, no real laptop)."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import runs  # noqa: E402
from junkroan.runs import hosts as runs_hosts  # noqa: E402

T0 = datetime(2026, 10, 7, 12, 0, 0)


@pytest.fixture()
def modes_file(tmp_path, monkeypatch):
    path = tmp_path / "modes.json"
    monkeypatch.setenv("JUNKROAN_MODES_FILE", str(path))
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    return path


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_reserve_writes_record_next_to_mode_and_a_second_call_replaces_it(modes_file):
    modes_file.write_text(json.dumps({"pc": {"mode": "play", "until": "2026-10-07T18:00:00"}}), encoding="utf-8")
    until = runs_hosts.set_owner_reservation("pc", 6, 30, now=T0)
    assert until == T0 + timedelta(minutes=30)
    assert _read(modes_file)["pc"] == {
        "mode": "play", "until": "2026-10-07T18:00:00", "reserved": 6, "reserved_until": "2026-10-07T12:30:00"}
    runs_hosts.set_owner_reservation("pc", 2, 10, now=T0)
    entry = _read(modes_file)["pc"]
    assert entry["reserved"] == 2 and entry["reserved_until"] == "2026-10-07T12:10:00" and entry["mode"] == "play"


def test_reserve_on_a_host_without_entry_creates_only_the_two_keys(modes_file):
    runs_hosts.set_owner_reservation("pc", 3, 5, now=T0)
    assert _read(modes_file) == {"pc": {"reserved": 3, "reserved_until": "2026-10-07T12:05:00"}}


def test_release_drops_record_and_keeps_mode(modes_file):
    modes_file.write_text(json.dumps({"pc": {"mode": "play", "until": None}}), encoding="utf-8")
    runs_hosts.set_owner_reservation("pc", 6, 30, now=T0)
    assert runs_hosts.release_owner_reservation("pc") is True
    assert _read(modes_file) == {"pc": {"mode": "play", "until": None}}
    assert runs_hosts.release_owner_reservation("pc") is False


def test_cli_reserve_and_release_print_one_line(modes_file, capsys):
    assert runs.main(["reserve", "--host", "pc", "--slots", "6", "--for", "30m", "--who", "owner"]) == 0
    out = capsys.readouterr().out.strip()
    assert re.fullmatch(r"reserved 6 slots on pc until \d\d:\d\d \(for 30 min\)", out), out
    assert _read(modes_file)["pc"]["reserved"] == 6
    assert runs.main(["reserve", "--host", "pc", "--release"]) == 0
    assert capsys.readouterr().out.strip() == "released the owner's reservation on pc"
    assert "pc" not in _read(modes_file)


def test_timed_mode_changes_keep_the_owner_record(modes_file, tmp_path):
    runs_hosts.set_owner_reservation("pc", 6, 30, now=T0)
    runs_hosts.record_mode("pc", "play")
    assert _read(modes_file)["pc"]["reserved"] == 6
    runs_hosts.record_mode("pc", "normal")
    assert _read(modes_file)["pc"] == {"reserved": 6, "reserved_until": "2026-10-07T12:30:00"}


def test_revert_expired_drops_the_record_without_touching_the_mode(modes_file, tmp_path):
    later = (T0 + timedelta(hours=5)).isoformat()
    modes_file.write_text(json.dumps({"pc": {"mode": "play", "until": later}}), encoding="utf-8")
    until = runs_hosts.set_owner_reservation("pc", 6, 30, now=T0)
    kw = {"events_file": tmp_path / "ev.jsonl", "budget_path": tmp_path / "b.json"}
    assert runs_hosts.revert_expired_modes(until - timedelta(seconds=1), **kw) == []
    assert _read(modes_file)["pc"]["reserved"] == 6
    assert runs_hosts.revert_expired_modes(until + timedelta(seconds=1), **kw) == []
    assert _read(modes_file)["pc"] == {"mode": "play", "until": later}


def test_revert_expired_removes_an_entry_that_only_held_the_record(modes_file, tmp_path):
    until = runs_hosts.set_owner_reservation("laptop", 1, 5, now=T0)
    runs_hosts.revert_expired_modes(until + timedelta(seconds=1), events_file=tmp_path / "ev.jsonl")
    assert _read(modes_file) == {}


def test_owner_reservation_reader(modes_file):
    until = runs_hosts.set_owner_reservation("pc", 6, 30, now=T0)
    assert runs_hosts.owner_reservation("pc", T0 + timedelta(minutes=1)) == (6, until)
    assert runs_hosts.owner_reservation("pc", until + timedelta(seconds=1)) is None
    assert runs_hosts.owner_reservation("laptop", T0) is None
    modes_file.write_text("{not json", encoding="utf-8")
    assert runs_hosts.owner_reservation("pc", T0) is None
    modes_file.write_text(json.dumps({"pc": {"reserved": "x", "reserved_until": "never"}}), encoding="utf-8")
    assert runs_hosts.owner_reservation("pc", T0) is None
    modes_file.write_text(json.dumps({"pc": "garbage"}), encoding="utf-8")
    assert runs_hosts.owner_reservation("pc", T0) is None


def test_laptop_reserve_from_the_pc_sends_one_command_that_writes_the_record(modes_file, monkeypatch, capsys):
    sent = []

    def fake_run_on_host(host_cfg, script):
        sent.append(script)
        return SimpleNamespace(returncode=0, stdout="reserved 1 slots on laptop until 13:00 (for 60 min)\n", stderr="")

    monkeypatch.setattr(runs_hosts, "run_on_host", fake_run_on_host)
    assert runs.main(["reserve", "--host", "laptop", "--slots", "1", "--for", "60m", "--who", "owner"]) == 0
    assert len(sent) == 1
    assert not modes_file.exists()  # nothing written on the PC's own modes.json
    tokens = re.findall(r"'((?:[^']|'')*)'", sent[0].split("& ", 1)[1])
    assert tokens[2:5] == ["reserve", "--host", "laptop"] and "--local" in tokens
    assert tokens[tokens.index("--slots") + 1] == "1" and tokens[tokens.index("--for") + 1] == "60m"
    # what the laptop does with that command: run it there (here: locally, into the temp modes file)
    monkeypatch.setenv("JUNKROAN_HOST", "laptop")
    assert runs.main(tokens[2:]) == 0
    assert _read(modes_file)["laptop"]["reserved"] == 1
