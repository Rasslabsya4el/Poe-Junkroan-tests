"""#958 unit 4b: the allow-list close wired into the daemon's end of "sleep", and `owner <host> close-preview`.

Fake clock, the rows 33-37e snapshot of test_issue958_close_set, a recording pid killer: no real process is
read, closed or killed."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import runs  # noqa: E402
from junkroan.runs import close_set as cs  # noqa: E402
from junkroan.runs import hosts as runs_hosts  # noqa: E402
from junkroan.runs import owner_commands as oc  # noqa: E402
from tests import test_issue958_close_set as rows  # noqa: E402
from tests.test_runs_daemon_owner_preset_958 import (  # noqa: E402,F401
    CONFIG as OLD_CONFIG, FIVE, T0, SimpleRig, _reading, rig,
)

SLEEP_ALLOW = {**OLD_CONFIG["laptop"]["owner_presets"]["sleep"], "close_mode": "allow-list", "keep": ["foo.exe"]}
CONFIG = {"laptop": {"ssh": "laptop", "daemon_repo_path": "C:\\daemon", "owner_presets": {
    "film": OLD_CONFIG["laptop"]["owner_presets"]["film"], "sleep": SLEEP_ALLOW}}}
THREE_PIDS = [2001, 2002, 2003]  # rows 33-35: chrome, Telegram, wmplayer


def planner_over(snapshot):
    """A planner over a fixed snapshot with the close_set test's machine facts."""

    def plan(keep):
        return cs.plan_close("pc", keep, reader=lambda: snapshot, console=lambda: rows.CONSOLE,
                             user=rows.USER, system_root=rows.ROOT, daemon=rows.DAEMON, self_pid=rows.DAEMON)

    return plan


def wire_allow_list(rig, snapshot=None, calls=None):
    calls = [] if calls is None else calls
    rig.daemon._close_planner = planner_over(rows.all_rows() if snapshot is None else snapshot)
    rig.daemon._pid_killer = lambda pids: calls.append(list(pids)) or runs_hosts.KillResult(
        found=len(pids), killed=len(pids))
    return calls


def start_allow_list(rig, name="sleep", duration_text=None):
    return oc.start_preset("pc", name, config={"pc": CONFIG["laptop"]}, modes_file=rig.modes,
                           reader=_reading, now=rig.clock["now"], duration_text=duration_text)


def test_row_a_the_end_of_sleep_calls_the_pid_killer_once_with_exactly_rows_33_to_35(rig):
    calls = wire_allow_list(rig)
    start_allow_list(rig)
    rig.ticks()
    assert calls == [] and rig.total == 8
    rig.at(121)
    rig.ticks(3)
    assert len(calls) == 1 and sorted(calls[0]) == THREE_PIDS
    assert rig.killed == []  # the five-name killer is never used in this mode
    assert runs_hosts.owner_record_raw("pc", modes_file=rig.modes) is None and rig.total == 10
    line = [x for x in rig.logs if "outside the allow-list" in x]
    assert len(line) == 1
    assert "sleep ended: found 3, killed 3, denied 0 process(es) outside the allow-list: " in line[0]
    for name in ("chrome.exe", "Telegram.exe", "wmplayer.exe"):
        assert name in line[0]


def test_the_record_carries_the_mode_and_the_keep_list_and_no_five_names(rig):
    lines = start_allow_list(rig)
    record = runs_hosts.owner_record_raw("pc", modes_file=rig.modes)
    assert record["close_mode"] == "allow-list" and record["keep"] == ["foo.exe"]
    assert record["on_end"] == "close-browsers" and "close" not in record
    assert any("outside the allow-list" in line for line in lines)


def test_row_a_film_closes_nothing_at_its_end_and_back_closes_nothing(rig):
    calls = wire_allow_list(rig)
    start_allow_list(rig, "film", "120m")
    rig.at(121)
    rig.ticks(3)
    assert calls == [] and rig.killed == []
    rig.at(0)
    start_allow_list(rig)
    rig.at(30)
    oc.end_preset("pc", modes_file=rig.modes)
    rig.ticks()
    rig.at(121)
    rig.ticks(3)
    assert calls == [] and rig.killed == []


def test_row_a_a_snapshot_that_cannot_be_read_kills_nothing_and_logs_one_line(rig):
    calls = wire_allow_list(rig)
    rig.daemon._close_planner = lambda keep: cs.plan_close(
        "pc", keep, reader=lambda: None, console=lambda: rows.CONSOLE, user=rows.USER,
        system_root=rows.ROOT, daemon=rows.DAEMON, self_pid=rows.DAEMON)
    start_allow_list(rig)
    rig.at(121)
    rig.ticks(3)
    assert calls == [] and rig.killed == []
    lines = [x for x in rig.logs if "snapshot could not be read" in x]
    assert len(lines) == 1
    assert runs_hosts.owner_record_raw("pc", modes_file=rig.modes) is None  # the record is dropped anyway


def test_a_killer_that_raises_closes_nothing_logs_once_and_drops_the_record(rig):
    wire_allow_list(rig)

    def boom(pids):
        raise PermissionError("access denied")

    rig.daemon._pid_killer = boom
    start_allow_list(rig)
    rig.at(121)
    rig.ticks(3)
    failures = [x for x in rig.logs if "failed" in x and "access denied" in x]
    assert len(failures) == 1
    assert runs_hosts.owner_record_raw("pc", modes_file=rig.modes) is None and rig.total == 10


def test_the_keep_list_of_the_record_reaches_the_rule(rig):
    calls = wire_allow_list(rig)
    start_allow_list(rig)
    doc = json.loads(rig.modes.read_text(encoding="utf-8"))
    assert doc["pc"]["keep"] == ["foo.exe"]
    doc["pc"]["keep"] = []  # foo.exe no longer kept -> it closes too
    rig.modes.write_text(json.dumps(doc), encoding="utf-8")
    rig.at(121)
    rig.ticks(3)
    assert len(calls) == 1 and sorted(calls[0]) == sorted(THREE_PIDS + [6001])


def test_allow_list_off_the_five_name_path_is_as_before(rig):
    calls = wire_allow_list(rig)
    rig.start("sleep")  # the old CONFIG: no close_mode
    rig.at(121)
    rig.ticks(3)
    assert rig.killed == [FIVE] and calls == []
    assert any(x.startswith("sleep ended: found 5, killed 5, denied 0 process(es) of chrome, msedge")
               for x in rig.logs)


def test_an_explicit_close_override_wins_over_the_allow_list(rig):
    calls = wire_allow_list(rig)
    oc.start_preset("pc", "sleep", config={"pc": CONFIG["laptop"]}, modes_file=rig.modes, reader=_reading,
                    now=T0, close=["dummy_probe"])
    rig.at(121)
    rig.ticks()
    assert rig.killed == [["dummy_probe"]] and calls == []


def test_status_names_the_allow_list(rig):
    start_allow_list(rig)
    text = "\n".join(oc.status_lines("pc", reader=_reading, modes_file=rig.modes, now=T0))
    assert "every program outside the allow-list" in text and "foo.exe" in text


def test_plan_close_returns_none_without_a_console_session_or_system_root():
    base = dict(reader=lambda: rows.all_rows(), user=rows.USER, daemon=rows.DAEMON, self_pid=rows.DAEMON)
    assert cs.plan_close("pc", [], console=lambda: None, system_root=rows.ROOT, **base) is None
    assert cs.plan_close("pc", [], console=lambda: rows.CONSOLE, system_root="", **base) is None
    closed, _ = cs.plan_close("pc", [], console=lambda: rows.CONSOLE, system_root=rows.ROOT, **base)
    assert sorted(p.pid for p in closed) == sorted(THREE_PIDS + [6001])


# -- close-preview ----------------------------------------------------------------------------------

@pytest.fixture()
def cli(tmp_path, monkeypatch):
    cfg = tmp_path / "hosts.json"
    cfg.write_text(json.dumps({"pc": {"ssh": None, "modes": {}}, **CONFIG}), encoding="utf-8")
    monkeypatch.setenv("JUNKROAN_HOSTS_CONFIG", str(cfg))
    monkeypatch.setenv("JUNKROAN_MODES_FILE", str(tmp_path / "modes.json"))
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    return tmp_path


def _main(tmp_path, argv):
    return runs.main(["--store", str(tmp_path / "jobs.jsonl")] + argv)


def _fake_machine(monkeypatch, snapshot, killer_calls):
    monkeypatch.setattr(cs, "read_snapshot", lambda: snapshot)
    monkeypatch.setattr(cs, "console_session_id", lambda: rows.CONSOLE)
    monkeypatch.setattr(cs, "daemon_pid", lambda host: rows.DAEMON)
    monkeypatch.setattr("os.getpid", lambda: rows.DAEMON)
    monkeypatch.setenv("SystemRoot", rows.ROOT)
    monkeypatch.setattr("getpass.getuser", lambda: rows.USER)
    monkeypatch.setattr(runs_hosts, "kill_processes_by_pid", lambda pids: killer_calls.append(list(pids)))
    monkeypatch.setattr(runs_hosts, "kill_processes_by_name", lambda names: killer_calls.append(list(names)))


def test_row_b_close_preview_local_prints_both_lists_and_kills_nothing(cli, monkeypatch, capsys):
    killer = []
    _fake_machine(monkeypatch, rows.all_rows(), killer)
    monkeypatch.setattr(runs_hosts, "run_on_host", lambda *a: pytest.fail("no ssh with --local"))
    assert _main(cli, ["owner", "laptop", "close-preview", "--local"]) == 0
    out = capsys.readouterr().out
    closed_part, kept_part = out.split("KEPT (")
    for name, pid in (("chrome.exe", 2001), ("Telegram.exe", 2002), ("wmplayer.exe", 2003)):
        assert f"{name} pid {pid}" in closed_part
    # foo.exe is in the preset's keep list: on the KEPT side, with the rule
    assert "foo.exe pid 6001: rule 5: in the keep list" in kept_part and "foo.exe" not in closed_part
    assert "CLOSED (3)" in closed_part
    assert "explorer.exe pid 2004: rule 3: under %SystemRoot%" in kept_part and "explorer.exe" not in closed_part
    assert "rule 4" in kept_part and "rule 1" in kept_part
    assert killer == []
    assert not (cli / "modes.json").exists()


def test_row_b_an_unreadable_snapshot_is_a_non_zero_exit_and_a_plain_line(cli, monkeypatch, capsys):
    killer = []
    _fake_machine(monkeypatch, None, killer)
    assert _main(cli, ["owner", "laptop", "close-preview", "--local"]) == 1
    captured = capsys.readouterr()
    assert "snapshot could not be read" in captured.err and captured.out == "" and killer == []


def test_row_b_from_the_pc_close_preview_is_one_ssh_command_carrying_local(cli, monkeypatch, capsys):
    sent = []
    monkeypatch.setattr(runs_hosts, "run_on_host", lambda cfg, script: sent.append(script) or SimpleNamespace(
        returncode=0, stdout="CLOSED (0): x\nKEPT (0):\nnothing was closed\n", stderr=""))
    monkeypatch.setattr(cs, "read_snapshot", lambda: pytest.fail("the PC reads no snapshot of its own"))
    assert _main(cli, ["owner", "laptop", "close-preview"]) == 0
    assert len(sent) == 1 and "'owner' 'laptop' 'close-preview' '--local'" in sent[0]
    assert "nothing was closed" in capsys.readouterr().out
