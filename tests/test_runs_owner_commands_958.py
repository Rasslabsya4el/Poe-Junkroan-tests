"""#958 unit 3b: `runs.py owner <host> film|sleep|back|status` and the owner record it writes.

Fake clock, fake machine readings, ssh mocked: no real ssh, no real kill, no PobSession, no laptop."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import runs  # noqa: E402
from junkroan.pob import slot_budget  # noqa: E402
from junkroan.runs import hosts as runs_hosts  # noqa: E402
from junkroan.runs import owner_commands as oc  # noqa: E402

T0 = datetime(2026, 10, 13, 22, 0, 0)
FIVE = ["chrome", "msedge", "firefox", "opera", "brave"]

CONFIG = {
    "pc": {"ssh": None, "modes": {}},
    "laptop": {
        "ssh": "laptop", "daemon_repo_path": "C:\\daemon",
        "owner_presets": {
            "film": {"need_cpu_cores": 1.5, "need_ram_mb": 2500},
            "sleep": {"need_cpu_cores": 1.5, "need_ram_mb": 2500, "for": "2h",
                      "on_end": "close-browsers", "close": FIVE},
        },
    },
}
SLOT_CONFIG = {
    "laptop": {"ssh": "laptop", "owner_presets": {
        "film": {"slots": 1},
        "sleep": {"slots": 1, "for": "2h", "on_end": "close-browsers", "close": FIVE}}},
}


def row16_reading() -> oc.Reading:
    return oc.Reading(idle_cores=0.2, free_ram_mb=800, workers=[oc.Worker(1.0, 900)] * 3)


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture()
def modes(tmp_path):
    return tmp_path / "modes.json"


def _start(modes, name, config=CONFIG, **kw):
    kw.setdefault("reader", row16_reading)
    kw.setdefault("now", T0)
    return oc.start_preset("laptop", name, config=config, modes_file=modes, **kw)


def _total(modes, now, tmp_path):
    doc = tmp_path / "budget.json"
    doc.write_text(json.dumps({"day": {"hours": [0, 24], "total": 3, "others": 0, "min_free_ram_gb": 0}}),
                   encoding="utf-8")
    return slot_budget.load_budget(now=now, path=doc, host="laptop", modes_file=modes).total


def test_row21_film_writes_reserved_2_until_t0_plus_120_and_prints_the_readings(modes, tmp_path):
    lines = _start(modes, "film", duration_text="120m", jobs_reader=lambda: {"jobA": 3})
    record = _read(modes)["laptop"]
    assert record["reserved"] == 2 and record["reserved_until"] == "2026-10-14T00:00:00"
    assert record["preset"] == "film" and "on_end" not in record and "close" not in record
    assert _total(modes, T0 + timedelta(minutes=1), tmp_path) == 1
    text = "\n".join(lines)
    assert "workers giving way: 2 of 3" in text and "jobA 2 of 3" in text
    assert "free RAM now: 800 MB" in text and "idle cores now: 0.2" in text
    assert "need: 1.5 cores and 2,500 MB" in text
    assert "short by" not in text
    assert "until 00:00 (for 2 h 00 min)" in text


def test_short_lines_when_even_everyone_giving_way_does_not_cover(modes):
    reading = oc.Reading(idle_cores=0.2, free_ram_mb=300, workers=[oc.Worker(1.0, 600)] * 3)
    lines = _start(modes, "film", duration_text="60m", reader=lambda: reading)
    assert _read(modes)["laptop"]["reserved"] == 3
    assert "short by 400 MB" in lines


def test_no_live_worker_is_a_record_with_zero_and_the_short_lines(modes):
    reading = oc.Reading(idle_cores=0.2, free_ram_mb=800, workers=[])
    lines = _start(modes, "sleep", reader=lambda: reading)
    record = _read(modes)["laptop"]
    assert record["reserved"] == 0 and record["on_end"] == "close-browsers"  # still there for the end
    assert "short by 1,700 MB" in lines and "short by 1.3 cores" in lines
    assert runs_hosts.owner_reservation("laptop", T0, modes_file=modes) is None  # gives nothing way


def test_row23_sleep_defaults_to_two_hours_and_carries_on_end_and_the_close_list(modes):
    lines = _start(modes, "sleep")
    record = _read(modes)["laptop"]
    assert record["reserved_until"] == "2026-10-14T00:00:00"
    assert record["on_end"] == "close-browsers" and record["preset"] == "sleep"
    assert record["close"] == FIVE
    assert record["need_cpu_cores"] == 1.5 and record["need_ram_mb"] == 2500
    assert any("closes: chrome, msedge, firefox, opera, brave" in line for line in lines)


def test_close_override_replaces_the_list_for_this_call(modes):
    _start(modes, "sleep", close=["dummy_probe"])
    assert _read(modes)["laptop"]["close"] == ["dummy_probe"]


def test_row26_film_then_sleep_is_one_record_the_second_replaced_the_first(modes):
    _start(modes, "film", duration_text="60m")
    assert "on_end" not in _read(modes)["laptop"]
    _start(modes, "sleep")
    record = _read(modes)["laptop"]
    assert record["preset"] == "sleep" and record["on_end"] == "close-browsers"
    assert list(_read(modes)) == ["laptop"]
    _start(modes, "film", duration_text="60m")  # and back: film after sleep keeps no on_end
    assert "on_end" not in _read(modes)["laptop"] and "close" not in _read(modes)["laptop"]


def test_a_plain_reserve_replaces_a_preset_whole(modes):
    _start(modes, "sleep")
    runs_hosts.set_owner_reservation("laptop", 1, 30, modes_file=modes, now=T0)
    assert _read(modes)["laptop"] == {"reserved": 1, "reserved_until": "2026-10-13T22:30:00"}


def test_row20_slot_preset_gives_exactly_its_slots_and_prints_the_slot_need(modes):
    lines = _start(modes, "film", config=SLOT_CONFIG, duration_text="30m")
    assert _read(modes)["laptop"]["reserved"] == 1
    assert "need: 1 slot(s) (no measured need yet)" in lines
    assert not any(line.startswith("short by") for line in lines)


def test_slot_preset_still_works_when_the_machine_cannot_be_read(modes):
    def broken():
        raise OSError("no psutil")

    lines = _start(modes, "film", config=SLOT_CONFIG, duration_text="30m", reader=broken)
    assert _read(modes)["laptop"]["reserved"] == 0  # no live worker known, nothing to give way
    assert not any("free RAM" in line for line in lines)


def test_film_without_for_is_refused_and_sleep_takes_the_preset_default(modes):
    with pytest.raises(oc.HostModeError):
        _start(modes, "film")
    _start(modes, "sleep")  # no raise: "for" 2h from the preset


def test_row25_back_ends_either_preset_at_once_and_says_it_closes_nothing(modes):
    _start(modes, "sleep")
    lines = oc.end_preset("laptop", modes_file=modes)
    assert _read(modes) == {}
    assert any("sleep ended at once" in line for line in lines)
    assert any("browsers stay open" in line for line in lines)
    assert oc.end_preset("laptop", modes_file=modes) == ["laptop: no owner preset or reservation is active"]


def test_back_keeps_the_mode_keys(modes):
    modes.write_text(json.dumps({"laptop": {"mode": "browser", "until": None}}), encoding="utf-8")
    _start(modes, "film", duration_text="30m")
    oc.end_preset("laptop", modes_file=modes)
    assert _read(modes) == {"laptop": {"mode": "browser", "until": None}}


def test_row31_status_room_yes_with_3100_mb_and_1_8_cores_and_no_with_2000(modes):
    _start(modes, "film", duration_text="120m")
    live = [oc.Worker(1.0, 900)]

    def reader(free):
        return lambda: oc.Reading(idle_cores=1.8, free_ram_mb=free, workers=live)

    now = T0 + timedelta(minutes=5)
    yes = oc.status_lines("laptop", reader=reader(3100), modes_file=modes, now=now)
    text = "\n".join(yes)
    assert "film until 00:00 (in 1 h 55 min)" in text
    assert "live PoB workers: 1" in text
    assert "free RAM now: 3,100 MB, idle cores now: 1.8" in text
    assert yes[-1] == "room: yes"
    no = oc.status_lines("laptop", reader=reader(2000), modes_file=modes, now=now)
    assert no[-1] == "room: no"


def test_status_without_a_record_has_no_room_line(modes):
    lines = oc.status_lines("laptop", reader=row16_reading, modes_file=modes, now=T0)
    assert lines[0] == "laptop: no owner preset or reservation is active"
    assert not any(line.startswith("room:") for line in lines)


def test_status_of_a_slot_preset_room_follows_the_workers_that_were_to_give_way(modes):
    _start(modes, "film", config=SLOT_CONFIG, duration_text="30m")  # 3 live, 1 gives way
    two = oc.Reading(idle_cores=1.0, free_ram_mb=2000, workers=[oc.Worker(1.0, 900)] * 2)
    three = oc.Reading(idle_cores=1.0, free_ram_mb=2000, workers=[oc.Worker(1.0, 900)] * 3)
    assert oc.status_lines("laptop", reader=lambda: two, modes_file=modes, now=T0)[-1] == "room: yes"
    assert oc.status_lines("laptop", reader=lambda: three, modes_file=modes, now=T0)[-1] == "room: no"


# -- the CLI: one ssh command from the PC ---------------------------------------------------------

def _main(argv):
    """`runs.main` with an empty job store of its own (never the worktree's linked artifacts/)."""
    return runs.main(["--store", str(_STORE["path"])] + argv)


_STORE: dict = {}

@pytest.fixture()
def cli(tmp_path, monkeypatch):
    cfg = tmp_path / "hosts.json"
    cfg.write_text(json.dumps(CONFIG), encoding="utf-8")
    monkeypatch.setenv("JUNKROAN_HOSTS_CONFIG", str(cfg))
    monkeypatch.setenv("JUNKROAN_MODES_FILE", str(tmp_path / "modes.json"))
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    monkeypatch.setattr(oc, "read_machine", row16_reading)
    _STORE["path"] = tmp_path / "jobs.jsonl"
    return tmp_path


def test_row29_from_the_pc_sleep_is_exactly_one_ssh_command_carrying_local(cli, monkeypatch, capsys):
    sent = []

    def fake_run_on_host(host_cfg, script):
        sent.append((host_cfg, script))
        return SimpleNamespace(returncode=0, stdout="sleep on laptop until 00:00 (for 2 h 00 min)\n", stderr="")

    monkeypatch.setattr(runs_hosts, "run_on_host", fake_run_on_host)
    assert _main(["owner", "laptop", "sleep"]) == 0
    assert len(sent) == 1
    script = sent[0][1]
    assert "'owner' 'laptop' 'sleep' '--local'" in script and "cd 'C:\\daemon'" in script
    assert not (cli / "modes.json").exists()  # nothing written on the PC
    assert capsys.readouterr().out.strip() == "sleep on laptop until 00:00 (for 2 h 00 min)"


def test_row29_with_ssh_failing_the_exit_is_non_zero_and_the_line_says_the_laptop_did_not_take_it(
        cli, monkeypatch, capsys):
    monkeypatch.setattr(runs_hosts, "run_on_host",
                        lambda cfg, script: SimpleNamespace(returncode=255, stdout="", stderr="ssh: timed out"))
    assert _main(["owner", "laptop", "film", "--for", "2h"]) == 1
    err = capsys.readouterr().err
    assert "the laptop did not take the command" in err and "timed out" in err

    def boom(cfg, script):
        raise OSError("no route")

    monkeypatch.setattr(runs_hosts, "run_on_host", boom)
    assert _main(["owner", "laptop", "back"]) == 1
    assert "the laptop did not take the command" in capsys.readouterr().err


def test_the_close_override_and_for_travel_in_the_one_ssh_command(cli, monkeypatch):
    sent = []
    monkeypatch.setattr(runs_hosts, "run_on_host",
                        lambda cfg, script: sent.append(script) or SimpleNamespace(returncode=0, stdout="", stderr=""))
    assert _main(["owner", "laptop", "sleep", "--for", "6m", "--close", "dummy"]) == 0
    assert len(sent) == 1 and "'--for' '6m' '--close' 'dummy'" in sent[0]


def test_row30_owner_pc_film_is_refused_with_a_plain_line(cli, monkeypatch, capsys):
    monkeypatch.setattr(runs_hosts, "run_on_host", lambda *a: pytest.fail("no ssh for a refused command"))
    assert _main(["owner", "pc", "film", "--for", "1h"]) == 1
    assert "the presets are the laptop's" in capsys.readouterr().err
    assert not (cli / "modes.json").exists()


def test_film_without_for_on_the_command_line_is_a_usage_error(cli, capsys):
    assert _main(["owner", "laptop", "film", "--local"]) == 2


def test_local_film_then_status_then_back_through_the_cli(cli, capsys):
    modes = cli / "modes.json"
    assert _main(["owner", "laptop", "film", "--for", "90m", "--local"]) == 0
    out = capsys.readouterr().out
    assert "workers giving way: 2 of 3" in out and "need: 1.5 cores and 2,500 MB" in out
    assert _read(modes)["laptop"]["reserved"] == 2
    assert _main(["owner", "laptop", "status", "--local"]) == 0
    assert "room: no" in capsys.readouterr().out  # 800 MB free, 0.2 idle cores: nothing was freed yet
    assert _main(["owner", "laptop", "back", "--local"]) == 0
    assert _read(modes) == {}
