"""`src/junkroan/runs/hosts.py`: host modes and reservations (issue #41).

No real PoB, no real SSH: `run_on_host` is monkeypatched wherever a laptop test needs the
transport, and every filesystem path is under `tmp_path`.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from junkroan.runs import hosts as runs_hosts

HOSTS_CONFIG = {
    "pc": {
        "ssh": None,
        "repo_path": "C:\\Coding\\poe-junkroan-v2",
        "loop_seconds_factor": 1.0,
        "modes": {
            "normal": {
                "day": {"hours": [8, 25], "total": 7, "others": 2, "min_free_ram_gb": 8},
                "night": {"hours": [1, 8], "total": 10, "others": 5, "min_free_ram_gb": 3},
                "pob_priority": "Normal",
                "strict_reserve": False,
            },
            "play": {
                "day": {"hours": [0, 24], "total": 5, "others": 2, "min_free_ram_gb": 8},
                "pob_priority": "Idle",
                "strict_reserve": True,
            },
        },
    },
    "laptop": {
        "ssh": "laptop",
        "repo_path": "C:\\Coding\\poe-junkroan-v2",
        "loop_seconds_factor": 1.18,
        "modes": {
            "normal": {
                "day": {"hours": [0, 24], "total": 3, "others": 0, "min_free_ram_gb": 1},
                "pob_priority": "Normal",
                "strict_reserve": True,
            },
            "browser": {
                "day": {"hours": [0, 24], "total": 2, "others": 0, "min_free_ram_gb": 1},
                "pob_priority": "Normal",
                "strict_reserve": True,
            },
        },
    },
}


def test_the_committed_hosts_config_loads_and_matches_the_laptop_doc():
    """`config/hosts.json` itself: loadable, and the laptop numbers match `docs/machines/laptop.md`."""

    config = runs_hosts.load_hosts_config()
    assert set(config) == {"pc", "laptop"}
    assert config["pc"]["ssh"] is None
    assert config["laptop"]["ssh"] == "laptop"
    # #120: the laptop's own runs daemon runs from a separate checkout (docs/STATE.md's "Laptop"
    # line), not this same `repo_path` -- `daemon_repo_path` is the override that points there.
    assert config["laptop"]["daemon_repo_path"] == "C:\\Coding\\poe-junkroan-v2-daemon"
    assert "daemon_repo_path" not in config["pc"]
    laptop_normal = config["laptop"]["modes"]["normal"]["day"]
    # #41 send-back: others is 0 (not 3) on the laptop, so the strict reserve (below) does not
    # stall it at limit 0 the moment this code reaches its hand-written machine_budget.json.
    assert (laptop_normal["total"], laptop_normal["others"], laptop_normal["min_free_ram_gb"]) == (3, 0, 1)
    assert config["laptop"]["modes"]["browser"]["day"]["total"] == 2
    assert config["laptop"]["modes"]["browser"]["day"]["others"] == 0
    assert config["pc"]["modes"]["play"]["pob_priority"] == "Idle"
    # pc play keeps the quick-call reserve (owner rule: quick PoB calls never wait): total 5, others 2.
    assert (config["pc"]["modes"]["play"]["day"]["total"], config["pc"]["modes"]["play"]["day"]["others"]) == (5, 2)
    assert config["pc"]["modes"]["play"]["day"]["total"] - config["pc"]["modes"]["play"]["day"]["others"] == 3

    # #126: the PC's `normal` mode declines the strict reserve (the owner's "no" on 2026-09-26);
    # every other mode still opts in.
    expected_strict_reserve = {
        ("pc", "normal"): False,
        ("pc", "play"): True,
        ("pc", "pause"): True,  # #413: queue 0, agents keep 2
        ("pc", "off"): True,  # 967e3e2: the owner's "полностью освободи мой ПК", total 0
        ("laptop", "normal"): True,
        ("laptop", "browser"): True,
        ("laptop", "off"): True,  # bfdc6f0: the laptop's own 'off' mode, mirroring the PC's
    }
    for host, host_cfg in config.items():
        for mode in host_cfg["modes"]:
            assert runs_hosts.mode_budget(host_cfg, host, mode)["strict_reserve"] is expected_strict_reserve[(host, mode)], (host, mode)

    # the laptop's queue limit (strict_reserve on, others == 0) is the full total on both modes.
    from junkroan.pob import slot_budget as _slot_budget

    laptop_normal_budget = _slot_budget.Budget(
        period="day", hours=(0, 24), total=3, others=0, min_free_ram_gb=1, strict_reserve=True
    )
    laptop_browser_budget = _slot_budget.Budget(
        period="day", hours=(0, 24), total=2, others=0, min_free_ram_gb=1, strict_reserve=True
    )
    assert laptop_normal_budget.limit_for(_slot_budget.ROLE_QUEUE) == 3
    assert laptop_browser_budget.limit_for(_slot_budget.ROLE_QUEUE) == 2


def test_queue_limits_on_the_committed_hosts_config():
    """#126 acceptance table: the queue limit `mode_budget()`/`apply_mode()` produce, per host/mode/window."""

    from junkroan.pob import slot_budget as _slot_budget

    config = runs_hosts.load_hosts_config()

    pc_normal = runs_hosts.mode_budget(config["pc"], "pc", "normal")
    day = _slot_budget.Budget(period="day", strict_reserve=pc_normal["strict_reserve"], **pc_normal["day"])
    night = _slot_budget.Budget(period="night", strict_reserve=pc_normal["strict_reserve"], **pc_normal["night"])
    assert day.limit_for(_slot_budget.ROLE_QUEUE) == 7, "pc, normal, day"
    assert night.limit_for(_slot_budget.ROLE_QUEUE) == 10, "pc, normal, night"

    pc_play = runs_hosts.mode_budget(config["pc"], "pc", "play")
    play = _slot_budget.Budget(period="day", strict_reserve=pc_play["strict_reserve"], **pc_play["day"])
    assert play.limit_for(_slot_budget.ROLE_QUEUE) == 3, "pc, play"

    # a revert from play to normal at night: the queue limit is the host total again (strict off).
    back_to_normal_at_night = _slot_budget.Budget(
        period="night", strict_reserve=pc_normal["strict_reserve"], **pc_normal["night"]
    )
    assert back_to_normal_at_night.limit_for(_slot_budget.ROLE_QUEUE) == 10, "pc, play then normal, night"

    laptop_normal = runs_hosts.mode_budget(config["laptop"], "laptop", "normal")
    laptop_normal_budget = _slot_budget.Budget(
        period="day", strict_reserve=laptop_normal["strict_reserve"], **laptop_normal["day"]
    )
    assert laptop_normal_budget.limit_for(_slot_budget.ROLE_QUEUE) == 3, "laptop, normal"

    laptop_browser = runs_hosts.mode_budget(config["laptop"], "laptop", "browser")
    laptop_browser_budget = _slot_budget.Budget(
        period="day", strict_reserve=laptop_browser["strict_reserve"], **laptop_browser["day"]
    )
    assert laptop_browser_budget.limit_for(_slot_budget.ROLE_QUEUE) == 2, "laptop, browser"


def test_413_pause_gives_the_queue_0_and_agents_2_and_no_other_mode_changes():
    """#413 rows 1 and 4: `mode_budget(pc, pause)` -> queue 0 / other 2; every other mode's limits as before."""

    from junkroan.pob import slot_budget as _sb

    config = runs_hosts.load_hosts_config()

    def limits(host: str, mode: str, period: str = "day") -> tuple[int, int]:
        doc = runs_hosts.mode_budget(config[host], host, mode)
        budget = _sb.Budget(
            period=period, strict_reserve=doc["strict_reserve"], queue_slots=doc.get("queue_slots"), **doc[period]
        )
        return budget.limit_for(_sb.ROLE_QUEUE), budget.limit_for(_sb.ROLE_OTHER)

    assert runs_hosts.mode_budget(config["pc"], "pc", "pause")["queue_slots"] == 0
    assert limits("pc", "pause") == (0, 2)
    assert limits("pc", "normal") == (7, 2)
    assert limits("pc", "normal", "night") == (10, 5)
    assert limits("pc", "play") == (3, 2)
    assert limits("pc", "off") == (1, 0)  # today's floor of 1, untouched
    assert limits("laptop", "normal") == (3, 0)
    assert limits("laptop", "browser") == (2, 0)
    # only pause names the key
    for host, host_cfg in config.items():
        for mode in host_cfg["modes"]:
            assert ("queue_slots" in runs_hosts.mode_budget(host_cfg, host, mode)) == ((host, mode) == ("pc", "pause"))


def test_413_load_budget_reads_queue_slots_from_the_written_document(tmp_path, monkeypatch):
    monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", "day")  # #847: the pause budget is written for the day window
    from junkroan.pob import slot_budget as _sb

    config = runs_hosts.load_hosts_config()
    path = tmp_path / "machine_budget.json"
    path.write_text(json.dumps(runs_hosts.mode_budget(config["pc"], "pc", "pause")), encoding="utf-8")
    budget = _sb.load_budget(path=path)
    assert (budget.limit_for(_sb.ROLE_QUEUE), budget.limit_for(_sb.ROLE_OTHER)) == (0, 2)


def test_apply_mode_pc_revert_from_play_to_normal_restores_the_full_night_queue_limit(tmp_path, monkeypatch):
    """#126 requirement 3: a revert from `play` to `normal` writes a budget whose queue limit is the
    host total again (`strict_reserve` off on `normal`)."""

    monkeypatch.setattr(runs_hosts, "find_pob_pids", lambda: [])
    monkeypatch.setattr(runs_hosts, "set_priority_class", lambda pids, priority: [])

    from junkroan.pob import slot_budget as _slot_budget

    config = runs_hosts.load_hosts_config()
    budget_path = tmp_path / "machine_budget.json"
    events_file = tmp_path / "events.jsonl"

    runs_hosts.apply_mode("pc", "play", config=config, budget_path=budget_path, events_file=events_file)
    runs_hosts.apply_mode("pc", "normal", config=config, budget_path=budget_path, events_file=events_file)

    written = json.loads(budget_path.read_bytes().decode("utf-8"))
    assert written["strict_reserve"] is False
    night = _slot_budget.Budget(period="night", strict_reserve=written["strict_reserve"], **written["night"])
    assert night.limit_for(_slot_budget.ROLE_QUEUE) == 10


def test_daemon_repo_path_falls_back_to_repo_path_when_unset():
    assert runs_hosts.daemon_repo_path({"repo_path": "C:\\Coding\\poe-junkroan-v2"}) == "C:\\Coding\\poe-junkroan-v2"


def test_daemon_repo_path_prefers_the_override():
    host_cfg = {"repo_path": "C:\\Coding\\poe-junkroan-v2",
                "daemon_repo_path": "C:\\Coding\\poe-junkroan-v2-daemon"}
    assert runs_hosts.daemon_repo_path(host_cfg) == "C:\\Coding\\poe-junkroan-v2-daemon"


# -- issue #118: `mark_posted_on_host` runs `runs.py mark-posted` in the daemon's own checkout ----

def test_mark_posted_on_host_runs_in_the_daemon_repo_path_and_returns_true(monkeypatch):
    host_cfg = {"ssh": "laptop", "repo_path": "C:\\Coding\\poe-junkroan-v2",
                "daemon_repo_path": "C:\\Coding\\poe-junkroan-v2-daemon"}
    calls = []

    def fake_run_on_host(cfg: dict, script: str) -> subprocess.CompletedProcess:
        calls.append((cfg, script))
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="OK", stderr="")

    monkeypatch.setattr(runs_hosts, "run_on_host", fake_run_on_host)
    ok = runs_hosts.mark_posted_on_host(host_cfg, "laptop", "j-20260927-1000-abcd")

    assert ok is True
    assert len(calls) == 1
    cfg, script = calls[0]
    assert cfg is host_cfg
    # It lands in the DAEMON's own checkout, not the plain `repo_path`.
    assert "C:\\Coding\\poe-junkroan-v2-daemon" in script
    assert "mark-posted" in script and "j-20260927-1000-abcd" in script


def test_mark_posted_on_host_returns_false_on_a_nonzero_exit(monkeypatch):
    monkeypatch.setattr(
        runs_hosts, "run_on_host",
        lambda cfg, script: subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom"),
    )
    assert runs_hosts.mark_posted_on_host({"repo_path": "x"}, "laptop", "j-1") is False


def test_mark_posted_on_host_returns_false_when_the_transport_raises(monkeypatch):
    def failing(cfg, script):
        raise RuntimeError("ssh unreachable")

    monkeypatch.setattr(runs_hosts, "run_on_host", failing)
    assert runs_hosts.mark_posted_on_host({"repo_path": "x"}, "laptop", "j-1") is False


def test_mode_budget_strips_the_priority_key():
    budget = runs_hosts.mode_budget(HOSTS_CONFIG["pc"], "pc", "normal")
    assert "pob_priority" not in budget
    assert budget["day"]["total"] == 7
    assert budget["strict_reserve"] is False, "re-attached as a top-level sibling of the period keys"
    assert runs_hosts.mode_priority(HOSTS_CONFIG["pc"], "pc", "normal") == "Normal"
    assert runs_hosts.mode_priority(HOSTS_CONFIG["pc"], "pc", "play") == "Idle"


# -- writing the budget file, BOM-free, verified -------------------------------------------------

def test_write_budget_bom_free_round_trips(tmp_path):
    target = tmp_path / "machine_budget.json"
    budget = {"day": {"hours": [8, 25], "total": 3, "others": 0, "min_free_ram_gb": 8}}
    parsed = runs_hosts.write_budget_bom_free(target, budget)
    assert parsed == budget
    raw = target.read_bytes()
    assert raw[:3] != b"\xef\xbb\xbf"
    assert json.loads(raw.decode("utf-8")) == budget


def test_a_bom_on_read_back_raises(monkeypatch, tmp_path):
    """Simulate PowerShell's `Set-Content -Encoding utf8` BOM slipping in; the check must catch it."""

    target = tmp_path / "machine_budget.json"
    budget = {"day": {"total": 3, "others": 0}}

    real_read_bytes = Path.read_bytes

    def bom_read_bytes(self: Path) -> bytes:
        if self == target:
            return b"\xef\xbb\xbf" + real_read_bytes(self)
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", bom_read_bytes)
    with pytest.raises(runs_hosts.HostModeError, match="BOM"):
        runs_hosts.write_budget_bom_free(target, budget)


# -- applying a mode -------------------------------------------------------------------------------

def test_apply_mode_pc_writes_locally_and_logs_one_event(tmp_path, monkeypatch):
    monkeypatch.setattr(runs_hosts, "find_pob_pids", lambda: [])
    monkeypatch.setattr(runs_hosts, "set_priority_class", lambda pids, priority: [])

    budget_path = tmp_path / "machine_budget.json"
    events_file = tmp_path / "events.jsonl"
    result = runs_hosts.apply_mode(
        "pc", "play", config=HOSTS_CONFIG, budget_path=budget_path, events_file=events_file,
        now=datetime(2026, 9, 26, 12, 0),
    )
    assert result["transport"] == "local"
    assert result["priority"] == "Idle"
    written = json.loads(budget_path.read_bytes().decode("utf-8"))
    assert written == runs_hosts.mode_budget(HOSTS_CONFIG["pc"], "pc", "play")

    lines = events_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event == {"ts": "2026-09-26T12:00:00", "kind": "mode", "host": "pc", "mode": "play"}


# -- run_on_host's own transport (#87: -EncodedCommand, not -Command) ---------------------------

def test_run_on_host_sends_encoded_command_and_a_variable_survives_the_round_trip(monkeypatch):
    """#87: `-Command "<script>"` let a shell along the way eat a `$variable` in the script (the
    laptop mode switch's own `$path`/`$bytes`/`$check`). `run_on_host` must send the script through
    `-EncodedCommand` (the same helper `remote_store.default_remote_transport` uses, #81 follow-up),
    so decoding the argv it builds gets back the exact script, `$variable`s included."""

    import base64

    captured: dict = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, 0, stdout="OK", stderr="")

    monkeypatch.setattr(runs_hosts, "run_bounded", fake_run)  # #521: run_on_host goes through the tree-killing runner

    script = "$path = 'C:\\Coding\\poe-junkroan-v2\\var\\machine_budget.json'; \"wrote $path\""
    result = runs_hosts.run_on_host({"ssh": "laptop"}, script)

    assert result.stdout == "OK"
    argv = captured["argv"]
    assert argv[:2] == ["ssh", "laptop"]
    assert argv[2:6] == ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand"]
    decoded = base64.b64decode(argv[6]).decode("utf-16-le")
    assert decoded == script
    assert captured["kwargs"]["timeout"] == 45


def test_apply_mode_laptop_sends_one_script_through_run_on_host_and_logs_one_event(tmp_path, monkeypatch):
    calls: list[tuple[dict, str]] = []

    def fake_run_on_host(host_cfg: dict, script: str) -> subprocess.CompletedProcess:
        calls.append((host_cfg, script))
        return subprocess.CompletedProcess(args=["ssh"], returncode=0, stdout="OK", stderr="")

    monkeypatch.setattr(runs_hosts, "run_on_host", fake_run_on_host)
    events_file = tmp_path / "events.jsonl"
    result = runs_hosts.apply_mode(
        "laptop", "browser", config=HOSTS_CONFIG, events_file=events_file, now=datetime(2026, 9, 26, 12, 0),
    )
    assert result["transport"] == "ssh"
    assert len(calls) == 1, "exactly one script sent through the transport"
    host_cfg, script = calls[0]
    assert host_cfg["ssh"] == "laptop"
    assert "WriteAllBytes" in script  # BOM-free write on the remote side
    assert "headless_runtime_worker" in script  # sets PoB process priority remotely

    lines = events_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event == {"ts": "2026-09-26T12:00:00", "kind": "mode", "host": "laptop", "mode": "browser"}


def test_apply_mode_local_writes_the_budget_here_and_makes_no_ssh_call(tmp_path, monkeypatch):
    """`local=True` must not ssh, even though the laptop's entry carries an alias (#364).

    The alias says how OTHER machines reach that host. Without this, the laptop's own
    restore-after-browser task ssh-ed from the laptop into the laptop, and the nested session died
    with no stdout, no stderr and no exit code -- so the restore would silently never happen.
    """

    def explode(host_cfg: dict, script: str) -> subprocess.CompletedProcess:
        raise AssertionError("apply_mode(local=True) must make no ssh call")

    monkeypatch.setattr(runs_hosts, "run_on_host", explode)
    budget_path = tmp_path / "machine_budget.json"
    monkeypatch.setattr(runs_hosts, "find_pob_pids", lambda: [])
    result = runs_hosts.apply_mode(
        "laptop", "normal", config=HOSTS_CONFIG, budget_path=budget_path,
        events_file=tmp_path / "events.jsonl", local=True,
    )
    assert result["transport"] == "local"
    written = json.loads(budget_path.read_text(encoding="utf-8"))
    assert written == runs_hosts.mode_budget(HOSTS_CONFIG["laptop"], "laptop", "normal")
    assert budget_path.read_bytes()[:1] != b"\xef", "a BOM here stalled the laptop for 1 h 30 min once"


def test_apply_mode_raises_on_unknown_host_or_mode():
    with pytest.raises(runs_hosts.HostModeError):
        runs_hosts.apply_mode("mars", "normal", config=HOSTS_CONFIG)
    with pytest.raises(runs_hosts.HostModeError):
        runs_hosts.apply_mode("pc", "sleep", config=HOSTS_CONFIG)


def test_apply_mode_laptop_raises_when_the_remote_script_fails(monkeypatch):
    def failing(host_cfg: dict, script: str) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args=["ssh"], returncode=1, stdout="", stderr="BOM written")

    monkeypatch.setattr(runs_hosts, "run_on_host", failing)
    with pytest.raises(runs_hosts.HostModeError, match="BOM written"):
        runs_hosts.apply_mode("laptop", "normal", config=HOSTS_CONFIG)


# -- reservations -----------------------------------------------------------------------------------

def test_parse_duration():
    assert runs_hosts.parse_duration("45m") == 2700
    assert runs_hosts.parse_duration("2h") == 7200
    assert runs_hosts.parse_duration("90s") == 90
    assert runs_hosts.parse_duration("1d") == 86400
    with pytest.raises(runs_hosts.HostModeError):
        runs_hosts.parse_duration("nonsense")


def test_reserve_and_release(tmp_path):
    path = tmp_path / "reservations.json"
    now = datetime(2026, 9, 26, 12, 0)
    entry = runs_hosts.reserve_slots("pc", 2, "45m", 12, path=path, now=now)
    assert entry["id"] == 1
    assert entry["host"] == "pc"
    assert entry["slots"] == 2
    assert entry["expires"] == "2026-09-26T12:45:00"

    stored = json.loads(path.read_bytes().decode("utf-8"))
    assert stored == [entry]

    second = runs_hosts.reserve_slots("laptop", 1, "1h", None, path=path, now=now)
    assert second["id"] == 2

    assert runs_hosts.release_reservation(1, path=path, now=now) is True
    remaining = json.loads(path.read_bytes().decode("utf-8"))
    assert [entry["id"] for entry in remaining] == [2]
    assert runs_hosts.release_reservation(999, path=path, now=now) is False


def test_reserve_prunes_expired_entries_on_write(tmp_path):
    path = tmp_path / "reservations.json"
    now = datetime(2026, 9, 26, 12, 0)
    runs_hosts.reserve_slots("pc", 1, "1s", 1, path=path, now=now)  # expires almost immediately
    later = now + timedelta(hours=1)
    runs_hosts.reserve_slots("pc", 1, "1h", 2, path=path, now=later)
    stored = json.loads(path.read_bytes().decode("utf-8"))
    assert [entry["issue"] for entry in stored] == [2], "the expired entry is dropped on the next write"


# -- var/modes.json: the monitor's optional timer (#54) -------------------------------------------


def test_apply_timed_mode_pc_records_until_and_logs_one_event(tmp_path, monkeypatch):
    monkeypatch.setattr(runs_hosts, "find_pob_pids", lambda: [])
    monkeypatch.setattr(runs_hosts, "set_priority_class", lambda pids, priority: [])

    budget_path = tmp_path / "machine_budget.json"
    events_file = tmp_path / "events.jsonl"
    modes_file = tmp_path / "modes.json"
    now = datetime(2026, 9, 26, 12, 0)

    result = runs_hosts.apply_timed_mode(
        "pc", "play", 60, config=HOSTS_CONFIG, budget_path=budget_path, events_file=events_file,
        modes_file=modes_file, now=now,
    )
    assert result["until"] == "2026-09-26T13:00:00"
    written = json.loads(budget_path.read_bytes().decode("utf-8"))
    assert written == runs_hosts.mode_budget(HOSTS_CONFIG["pc"], "pc", "play")

    modes = json.loads(modes_file.read_bytes().decode("utf-8"))
    assert modes == {"pc": {"mode": "play", "until": "2026-09-26T13:00:00"}}
    raw = modes_file.read_bytes()
    assert raw[:3] != b"\xef\xbb\xbf"

    lines = events_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1, "one event, not two"
    event = json.loads(lines[0])
    assert event == {
        "ts": "2026-09-26T12:00:00", "kind": "mode", "host": "pc", "mode": "play",
        "until": "2026-09-26T13:00:00", "by": "monitor",
    }


def test_apply_timed_mode_no_timer_records_until_none(tmp_path, monkeypatch):
    monkeypatch.setattr(runs_hosts, "find_pob_pids", lambda: [])
    monkeypatch.setattr(runs_hosts, "set_priority_class", lambda pids, priority: [])

    modes_file = tmp_path / "modes.json"
    result = runs_hosts.apply_timed_mode(
        "pc", "play", None, config=HOSTS_CONFIG, budget_path=tmp_path / "b.json",
        events_file=tmp_path / "e.jsonl", modes_file=modes_file, now=datetime(2026, 9, 26, 12, 0),
    )
    assert result["until"] is None
    modes = json.loads(modes_file.read_bytes().decode("utf-8"))
    assert modes == {"pc": {"mode": "play", "until": None}}


def test_apply_timed_mode_laptop_goes_through_run_on_host(tmp_path, monkeypatch):
    calls: list[tuple[dict, str]] = []

    def fake_run_on_host(host_cfg: dict, script: str) -> subprocess.CompletedProcess:
        calls.append((host_cfg, script))
        return subprocess.CompletedProcess(args=["ssh"], returncode=0, stdout="OK", stderr="")

    monkeypatch.setattr(runs_hosts, "run_on_host", fake_run_on_host)
    modes_file = tmp_path / "modes.json"
    result = runs_hosts.apply_timed_mode(
        "laptop", "browser", 30, config=HOSTS_CONFIG, events_file=tmp_path / "e.jsonl",
        modes_file=modes_file, now=datetime(2026, 9, 26, 12, 0),
    )
    assert len(calls) == 1
    assert result["until"] == "2026-09-26T12:30:00"
    modes = json.loads(modes_file.read_bytes().decode("utf-8"))
    assert modes == {"laptop": {"mode": "browser", "until": "2026-09-26T12:30:00"}}


def test_apply_timed_mode_back_to_normal_drops_the_host_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(runs_hosts, "find_pob_pids", lambda: [])
    monkeypatch.setattr(runs_hosts, "set_priority_class", lambda pids, priority: [])

    modes_file = tmp_path / "modes.json"
    modes_file.write_text(json.dumps({"pc": {"mode": "play", "until": "2026-09-26T13:00:00"}}), encoding="utf-8")
    runs_hosts.apply_timed_mode(
        "pc", "normal", None, config=HOSTS_CONFIG, budget_path=tmp_path / "b.json",
        events_file=tmp_path / "e.jsonl", modes_file=modes_file, now=datetime(2026, 9, 26, 12, 30),
    )
    modes = json.loads(modes_file.read_bytes().decode("utf-8"))
    assert modes == {}


def test_apply_timed_mode_failure_leaves_modes_file_unchanged(tmp_path):
    modes_file = tmp_path / "modes.json"
    modes_file.write_text(json.dumps({"laptop": {"mode": "normal", "until": None}}), encoding="utf-8")
    before = modes_file.read_bytes()

    def failing(host_cfg: dict, script: str) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args=["ssh"], returncode=1, stdout="", stderr="boom")

    import pytest as _pytest

    with _pytest.MonkeyPatch.context() as mp:
        mp.setattr(runs_hosts, "run_on_host", failing)
        with _pytest.raises(runs_hosts.HostModeError):
            runs_hosts.apply_timed_mode(
                "laptop", "browser", 30, config=HOSTS_CONFIG, events_file=tmp_path / "e.jsonl",
                modes_file=modes_file, now=datetime(2026, 9, 26, 12, 0),
            )
    assert modes_file.read_bytes() == before


def test_revert_expired_modes_switches_back_once_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(runs_hosts, "find_pob_pids", lambda: [])
    monkeypatch.setattr(runs_hosts, "set_priority_class", lambda pids, priority: [])

    budget_path = tmp_path / "machine_budget.json"
    events_file = tmp_path / "events.jsonl"
    modes_file = tmp_path / "modes.json"
    now = datetime(2026, 9, 26, 12, 0)

    runs_hosts.apply_timed_mode(
        "pc", "play", 60, config=HOSTS_CONFIG, budget_path=budget_path, events_file=events_file,
        modes_file=modes_file, now=now,
    )

    past_expiry = now + timedelta(hours=1, minutes=1)
    reverted = runs_hosts.revert_expired_modes(
        past_expiry, config=HOSTS_CONFIG, budget_path=budget_path, events_file=events_file,
        modes_file=modes_file,
    )
    assert reverted == ["pc"]
    written = json.loads(budget_path.read_bytes().decode("utf-8"))
    assert written == runs_hosts.mode_budget(HOSTS_CONFIG["pc"], "pc", "normal")
    modes = json.loads(modes_file.read_bytes().decode("utf-8"))
    assert modes == {}

    lines = events_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2  # the original "play" event, then the timer's "normal" revert
    last_event = json.loads(lines[-1])
    assert last_event == {
        "ts": past_expiry.isoformat(timespec="seconds"), "kind": "mode", "host": "pc", "mode": "normal",
        "until": None, "by": "timer",
    }

    # a second call finds nothing left to revert: no new event, no change to modes.json.
    again = runs_hosts.revert_expired_modes(
        past_expiry, config=HOSTS_CONFIG, budget_path=budget_path, events_file=events_file,
        modes_file=modes_file,
    )
    assert again == []
    lines_after = events_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines_after) == 2


def test_revert_expired_modes_leaves_unexpired_hosts_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(runs_hosts, "find_pob_pids", lambda: [])
    monkeypatch.setattr(runs_hosts, "set_priority_class", lambda pids, priority: [])

    modes_file = tmp_path / "modes.json"
    now = datetime(2026, 9, 26, 12, 0)
    runs_hosts.apply_timed_mode(
        "pc", "play", 60, config=HOSTS_CONFIG, budget_path=tmp_path / "b.json",
        events_file=tmp_path / "e.jsonl", modes_file=modes_file, now=now,
    )
    reverted = runs_hosts.revert_expired_modes(
        now + timedelta(minutes=30), config=HOSTS_CONFIG, budget_path=tmp_path / "b.json",
        events_file=tmp_path / "e.jsonl", modes_file=modes_file,
    )
    assert reverted == []
    modes = json.loads(modes_file.read_bytes().decode("utf-8"))
    assert modes == {"pc": {"mode": "play", "until": "2026-09-26T13:00:00"}}


def test_read_modes_tolerates_missing_and_empty_file(tmp_path):
    assert runs_hosts.read_modes(tmp_path / "missing.json") == {}
    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")
    assert runs_hosts.read_modes(empty) == {}


# -- describe_ssh_failure (#382) ---------------------------------------------------------------------

def _result(rc, stderr=""):
    return subprocess.CompletedProcess(["ssh"], rc, stdout="", stderr=stderr)


@pytest.mark.parametrize("failure, elapsed, expected", [
    (subprocess.TimeoutExpired(["ssh", "laptop", "AAAABBBB=="], 10.0), 3.0, "timeout after 10 s"),
    (_result(255, "ssh: connect to host laptop port 22: Connection refused"), 2.0, "connection refused after 2 s"),
    (_result(255, "ssh: connect to host laptop port 22: Connection timed out"), 21.0, "timeout after 21 s"),
    (_result(255, "ssh: connect to host laptop: No route to host"), 1.0, "host unreachable / no route after 1 s"),
    (_result(1, "boom"), 1.0, "rc 1 after 1 s"),
    (ConnectionResetError("x" * 50), 4.0, "ConnectionResetError after 4 s"),
])
def test_describe_ssh_failure(failure, elapsed, expected):
    text = runs_hosts.describe_ssh_failure(failure, elapsed)
    assert text == expected
    assert "==" not in text and "-EncodedCommand" not in text


def test_remote_pass_log_line_has_the_new_shape(tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_runs_daemon import make_daemon

    def reader(host_cfg):
        raise subprocess.TimeoutExpired(["ssh", "laptop", "-EncodedCommand", "QQBBAEEA" * 40], 10.0)

    daemon, _, _ = make_daemon(tmp_path, host="pc", hosts_config={"laptop": {"ssh": "laptop"}},
                               remote_store_reader=reader, remote_pass_seconds=0.0)
    logged = []
    daemon.log = logged.append
    daemon.remote_handback_pass()
    assert logged == ["remote handback: laptop unreachable (timeout after 10 s); skipping this pass"]
