"""tools/hosts/laptop/wifi-guard.ps1 (#1188): one run (one tick) of the laptop Wi-Fi guard.

Runs the real script with -Tick, a tmp -Repo and a fake -ProbeJson (a JSON array: one element per probe, the last
element repeats). -ProbeJson also makes the toggle fake (no Disable-NetAdapter), so no network and no adapter are
touched. The decision itself is tests/test_wifi_guard_decision.py; here the seams are the journal and the state file.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "hosts" / "laptop" / "wifi-guard.ps1"
POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")

pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="powershell.exe is not on PATH (Windows-only script)")

JOURNAL_FIELDS = [
    "time", "kind", "ssid", "signal_pct", "bssid", "band", "channel", "ipv4", "link_local", "gateway",
    "dns_servers", "gateway_reach", "outside_reach", "dns_result", "ncsi", "adapter_power_mgmt", "events",
    "wlan_raw",
]


def probe(ncsi="LocalNetwork", gateway="192.168.1.1", gateway_reach=False, outside_reach=False, dns_result=None, **env):
    """One fake probe: the network checks plus the environment fields the journal reads from the fake."""
    return {"ncsi": ncsi, "gateway": gateway, "gateway_reach": gateway_reach, "outside_reach": outside_reach,
            "dns_result": dns_result, **env}


FAIL = probe()
OK = probe(ncsi="Internet", gateway_reach=True, outside_reach=True, dns_result="104.18.0.1")


class Rig:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.var = tmp / "var" / "wifi-guard"
        self.runs = 0

    def tick(self, now: str, probes, *extra: str):
        self.runs += 1
        pf = self.tmp / f"probe{self.runs}.json"
        pf.write_text(json.dumps(probes if isinstance(probes, list) else [probes]), encoding="utf-8")
        r = subprocess.run(
            [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), "-Tick",
             "-Repo", str(self.tmp), "-Now", now, "-ProbeJson", str(pf), *extra],
            capture_output=True, text=True, timeout=180,
        )
        assert r.returncode == 0, r.stdout + r.stderr
        return r

    def journal(self) -> list[dict]:
        f = self.var / "journal.jsonl"
        if not f.exists():
            return []
        return [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]

    def kinds(self) -> list[str]:
        return [e["kind"] for e in self.journal()]

    def state(self) -> dict:
        return json.loads((self.var / "state.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "ncsi, gateway_reach, outside_reach, dns_result, internet",
    [
        ("Internet", False, False, None, True),          # Windows says Internet: gateway down does not matter
        ("LocalNetwork", False, False, None, False),     # NCSI not Internet and every reach fails: no internet
        ("LocalNetwork", False, True, None, True),       # NCSI not Internet but 1.1.1.1 answers: internet
        ("LocalNetwork", False, False, "1.2.3.4", True), # NCSI not Internet but DNS answers: internet
        ("LocalNetwork", True, False, None, False),      # gateway answers, outside and DNS do not: no internet (gateway is journalled only)
        (None, False, False, None, False),               # NCSI unreadable and every reach fails: no internet
    ],
    ids=["ncsi-internet", "all-fail", "outside-ok", "dns-ok", "gateway-only", "ncsi-unknown"],
)
def test_no_internet_truth_table(tmp_path, ncsi, gateway_reach, outside_reach, dns_result, internet):
    rig = Rig(tmp_path)
    rig.tick("2026-10-01 10:00:00", probe(ncsi=ncsi, gateway_reach=gateway_reach,
                                          outside_reach=outside_reach, dns_result=dns_result))
    (line,) = rig.journal()
    assert line["internet_ok"] is internet


def test_fourteen_minutes_wait_and_the_fifteenth_toggles_twice_in_the_same_run(tmp_path):
    rig = Rig(tmp_path)
    for minute in range(15):  # 10:00 .. 10:14, one tick a minute
        rig.tick(f"2026-10-01 10:{minute:02d}:00", FAIL)
    assert "toggle-off" not in rig.kinds()
    assert [e["action"] for e in rig.journal()] == ["wait"] * 15

    # 10:15: the drop has lasted 15 min -> toggle; the probe after the toggle still fails -> toggle again;
    # the third probe has internet -> done.
    rig.tick("2026-10-01 10:15:00", [FAIL, FAIL, OK])
    new = rig.journal()[15:]
    assert [e["kind"] for e in new] == [
        "check", "toggle-off", "toggle-on", "check", "toggle-off", "toggle-on", "check", "back",
    ]
    assert [e["action"] for e in new if e["kind"] == "check"] == ["toggle", "toggle", "done"]
    assert new[-1]["drop_minutes"] == 15


def test_internet_back_writes_back_with_drop_minutes_and_resets_the_state(tmp_path):
    rig = Rig(tmp_path)
    rig.tick("2026-10-01 10:00:00", FAIL)
    rig.tick("2026-10-01 10:04:00", FAIL)  # 4 min apart: inside the 5 min gap rule, the drop is continuous
    rig.tick("2026-10-01 10:08:00", OK)
    last = rig.journal()[-1]
    assert last["kind"] == "back"
    assert last["drop_minutes"] == 8
    assert not any(k.startswith("toggle") for k in rig.kinds())
    state = rig.state()
    assert state["NoInternetSince"] is None
    assert state["Toggles"] == 0


def test_gap_of_twenty_minutes_resets_the_drop_and_does_not_toggle(tmp_path):
    rig = Rig(tmp_path)
    rig.tick("2026-10-01 10:00:00", FAIL)
    rig.tick("2026-10-01 10:20:00", FAIL)  # the laptop slept or the task did not run for 20 min
    assert "toggle-off" not in rig.kinds()
    last = rig.journal()[-1]
    assert last["action"] == "wait"
    assert last["gap_reset"] is True
    assert rig.state()["NoInternetSince"] == "2026-10-01 10:20:00"


def test_journal_line_carries_every_field_and_flags_169_254(tmp_path):
    rig = Rig(tmp_path)
    rig.tick("2026-10-01 10:00:00", probe(
        ssid="HomeWifi", signal_pct=62, bssid="aa:bb:cc:dd:ee:ff", band="5 GHz", channel=36,
        ipv4="169.254.23.7", dns_servers=["192.168.1.1"], adapter_power_mgmt="Enabled",
        events=[{"id": 11006, "time": "10:03:11", "log": "wlan"}, {"id": 8003, "time": "10:04:02", "log": "wlan"}],
    ))
    line = rig.journal()[0]
    for field in JOURNAL_FIELDS:
        assert field in line, field
    assert line["link_local"] is True
    assert line["ssid"] == "HomeWifi"
    assert line["signal_pct"] == 62
    assert line["ipv4"] == "169.254.23.7"
    ids = [e["id"] for e in line["events"]]
    assert 11006 in ids and 8003 in ids


def test_second_instance_with_a_live_lock_exits_without_a_journal_line(tmp_path):
    rig = Rig(tmp_path)
    rig.var.mkdir(parents=True)
    lock = rig.var / "guard.lock"
    lock.write_text(str(os.getpid()), encoding="ascii")  # this test process is alive
    rig.tick("2026-10-01 10:00:00", FAIL)
    assert rig.journal() == []
    assert not (rig.var / "state.json").exists()
    assert lock.read_text(encoding="ascii").strip() == str(os.getpid())


def test_a_lock_left_by_a_dead_process_is_taken_over(tmp_path):
    rig = Rig(tmp_path)
    rig.var.mkdir(parents=True)
    (rig.var / "guard.lock").write_text("999996", encoding="ascii")  # no such process
    rig.tick("2026-10-01 10:00:00", FAIL)
    assert rig.kinds() == ["check"]


def test_lock_eleven_minutes_old_with_a_live_pid_is_taken_over(tmp_path):
    rig = Rig(tmp_path)
    rig.var.mkdir(parents=True)
    lock = rig.var / "guard.lock"
    lock.write_text(str(os.getpid()), encoding="ascii")  # this test process is alive
    old = time.time() - 11 * 60
    os.utime(lock, (old, old))  # last refresh 11 min ago: stale
    rig.tick("2026-10-01 10:00:00", FAIL)
    assert rig.kinds() == ["check"]
    assert not lock.exists()  # the run took the lock over and deleted it at the end


def test_drop_minutes_follow_the_clock_through_the_toggle_cycles(tmp_path):
    rig = Rig(tmp_path)
    for minute in range(15):  # 10:00 .. 10:14: the drop starts at 10:00
        rig.tick(f"2026-10-01 10:{minute:02d}:00", FAIL)
    # 10:15 toggle (+70 s) -> 10:16:10 toggle (+70 s) -> 10:17:20 probe OK: done after 17.3 min
    rig.tick("2026-10-01 10:15:00", [FAIL, FAIL, OK], "-ToggleCostSeconds", "70")
    back = rig.journal()[-1]
    assert back["kind"] == "back"
    assert back["drop_minutes"] >= 17


def test_a_bad_now_writes_an_error_line_and_still_saves_the_state(tmp_path):
    rig = Rig(tmp_path)
    rig.tick("not a time", FAIL)
    assert rig.kinds() == ["error"]
    assert rig.journal()[0]["error"]
    assert rig.state()["LastCheck"] is not None


def test_empty_events_are_an_empty_array_and_a_failed_read_is_null(tmp_path):
    rig = Rig(tmp_path)
    rig.tick("2026-10-01 10:00:00", probe(events=[]))
    rig.tick("2026-10-01 10:01:00", probe())  # no events key: the read failed
    empty, failed = rig.journal()
    assert empty["events"] == []
    assert failed["events"] is None


def test_dns_servers_are_always_an_array(tmp_path):
    rig = Rig(tmp_path)
    rig.tick("2026-10-01 10:00:00", probe(dns_servers="192.168.1.1"))  # one server, JSON string
    rig.tick("2026-10-01 10:01:00", probe(dns_servers=[]))
    one, none = rig.journal()
    assert one["dns_servers"] == ["192.168.1.1"]
    assert none["dns_servers"] == []


def test_netsh_text_gives_the_first_percent_as_signal_and_the_labels_as_fields(tmp_path):
    rig = Rig(tmp_path)
    text = (
        "    Name                   : Wi-Fi 2\n"
        "    SSID                   : HomeWifi\n"
        "    Signal                 : 74%\n"
        "    Channel                : 36\n"
        "    Receive rate (Mbps)    : 866\n"
    )
    rig.tick("2026-10-01 10:00:00", probe(wlan_raw=text))
    line = rig.journal()[0]
    assert line["signal_pct"] == 74
    assert line["ssid"] == "HomeWifi"
    assert line["channel"] == 36
    assert line["band"] == "5 GHz"
    assert line["wlan_raw"] == text


def test_wlan_raw_is_cut_to_1500_chars(tmp_path):
    rig = Rig(tmp_path)
    rig.tick("2026-10-01 10:00:00", probe(wlan_raw="x" * 3000))
    assert len(rig.journal()[0]["wlan_raw"]) == 1500


def test_gateway_answering_does_not_stop_the_drop_and_the_fifteenth_minute_toggles(tmp_path):
    # the owner's case: connected, 4-5 bars, no internet; the router still answers the gateway ping
    rig = Rig(tmp_path)
    gw_only = probe(ncsi="LocalNetwork", gateway_reach=True, outside_reach=False, dns_result=None)
    for minute in range(15):  # 10:00 .. 10:14: waits, the gateway answer does not reset the drop
        rig.tick(f"2026-10-01 10:{minute:02d}:00", gw_only)
    assert "toggle-off" not in rig.kinds()
    assert [e["action"] for e in rig.journal()] == ["wait"] * 15
    rig.tick("2026-10-01 10:15:00", [gw_only, OK])
    new = rig.journal()[15:]
    assert [e["kind"] for e in new] == ["check", "toggle-off", "toggle-on", "check", "back"]
    assert new[0]["gateway_reach"] is True  # still journalled
    assert new[-1]["drop_minutes"] == 15


def test_explicit_fake_toggle_flag_cycles_the_adapter_without_touching_it(tmp_path):
    rig = Rig(tmp_path)
    for minute in range(15):
        rig.tick(f"2026-10-01 10:{minute:02d}:00", FAIL)
    rig.tick("2026-10-01 10:15:00", [FAIL, OK], "-FakeToggle")
    new = rig.journal()[15:]
    assert [e["kind"] for e in new] == ["check", "toggle-off", "toggle-on", "check", "back"]
    assert new[2]["error"] is None
