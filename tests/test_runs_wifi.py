"""#382: laptop wifi check, fakes only (no real netsh/ping)."""

import json
from datetime import datetime

from junkroan.runs import watchdog, wifi

ROUTE = """===========================================================================
IPv4 Route Table
===========================================================================
Active Routes:
Network Destination        Netmask          Gateway       Interface  Metric
          0.0.0.0          0.0.0.0      192.168.1.254     192.168.1.50     55
          0.0.0.0          0.0.0.0      192.168.1.1      192.168.1.50     25
        127.0.0.0        255.0.0.0         On-link         127.0.0.1    331
"""

WLAN_UP = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    Description            : Intel(R) Wi-Fi 6 AX201 160MHz
    State                  : connected
    SSID                   : HomeNet
    BSSID                  : aa:bb:cc:dd:ee:ff
    Network type           : Infrastructure
    Signal                 : 87%
    Profile                : HomeNet
"""

WLAN_DOWN = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    Description            : Intel(R) Wi-Fi 6 AX201 160MHz
    State                  : disconnected
"""

NOW = datetime(2026, 10, 1, 9, 5, 7)


class Fake:
    def __init__(self, wlan, ping_rc=0, connect_rc=0):
        self.wlan, self.ping_rc, self.connect_rc, self.calls = wlan, ping_rc, connect_rc, []

    def __call__(self, cmd):
        self.calls.append(cmd)
        if cmd[0] == "route":
            return 0, ROUTE
        if cmd[0] == "ping":
            return self.ping_rc, ""
        if cmd[:3] == ["netsh", "wlan", "show"]:
            return 0, self.wlan
        if cmd[:3] == ["netsh", "wlan", "connect"]:
            return self.connect_rc, "The requested operation failed.\nmore" if self.connect_rc else "ok\n"
        raise AssertionError(cmd)

    def connects(self):
        return [c for c in self.calls if c[:3] == ["netsh", "wlan", "connect"]]


def _check(fake, tmp_path):
    return wifi.check(run=fake, now=lambda: NOW, log_path=tmp_path / "w.log", state_path=tmp_path / "w.json")


def _log(tmp_path):
    p = tmp_path / "w.log"
    return p.read_text().splitlines() if p.exists() else []


def test_gateway_parser_takes_lowest_metric():
    assert wifi.parse_gateway(ROUTE) == "192.168.1.1"
    assert wifi.parse_gateway("nothing") is None


def test_row_3a_ok_saves_profile_no_log(tmp_path):
    fake = Fake(WLAN_UP)
    assert _check(fake, tmp_path) == "ok"
    assert fake.connects() == [] and _log(tmp_path) == []
    assert json.loads((tmp_path / "w.json").read_text())["profile"] == "HomeNet"
    assert ["ping", "-n", "1", "-w", "2000", "192.168.1.1"] in fake.calls


def test_row_3b_disconnected_connects_once(tmp_path):
    (tmp_path / "w.json").write_text(json.dumps({"profile": "HomeNet", "seen": "x"}))
    fake = Fake(WLAN_DOWN, ping_rc=1)
    _check(fake, tmp_path)
    assert fake.connects() == [["netsh", "wlan", "connect", "name=HomeNet"]]
    assert _log(tmp_path) == [
        "2026-10-01 09:05:07 gateway 192.168.1.1 unreachable; wlan State=disconnected SSID=none Signal=none",
        "2026-10-01 09:05:07 connect name=HomeNet -> rc 0: ok",
    ]


def test_row_3c_failed_connect_one_per_tick(tmp_path):
    (tmp_path / "w.json").write_text(json.dumps({"profile": "HomeNet", "seen": "x"}))
    fake = Fake(WLAN_DOWN, ping_rc=1, connect_rc=1)
    _check(fake, tmp_path)
    assert len(fake.connects()) == 1
    assert "connect name=HomeNet -> rc 1: The requested operation failed." in _log(tmp_path)[-1]
    _check(fake, tmp_path)
    assert len(fake.connects()) == 2


def test_row_1_failure_line_has_time_state_ssid_signal(tmp_path):
    fake = Fake(WLAN_UP, ping_rc=1)
    _check(fake, tmp_path)
    assert _log(tmp_path) == [
        "2026-10-01 09:05:07 gateway 192.168.1.1 unreachable; wlan State=connected SSID=HomeNet Signal=87%"]
    assert fake.connects() == []


def test_no_saved_profile(tmp_path):
    fake = Fake(WLAN_DOWN, ping_rc=1)
    _check(fake, tmp_path)
    assert fake.connects() == []
    assert _log(tmp_path)[-1].endswith("disconnected, no known profile; no action")


def test_never_raises(tmp_path):
    def boom(cmd):
        raise OSError("x")

    _check(boom, tmp_path)
    assert any("failed" in ln for ln in _log(tmp_path))


def test_watchdog_main_calls_wifi_for_laptop_only(monkeypatch):
    seen = []
    monkeypatch.setattr(wifi, "check", lambda **kw: seen.append(kw))
    monkeypatch.setattr(watchdog, "ensure", lambda host, **_kw: 0)  # #521: main passes out=
    watchdog.main(["--host", "laptop"])
    assert len(seen) == 1 and seen[0]["log_path"].name == "wifi-laptop.log"
    watchdog.main(["--host", "pc"])
    assert len(seen) == 1
