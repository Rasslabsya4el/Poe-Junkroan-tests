"""tools/hosts/laptop/wifi-guard-decision.ps1 (#1188): the pure Wi-Fi guard decision.

Dot-sources the real script in Windows PowerShell and calls Get-WifiGuardAction with fixed datetimes.
No network, no adapter, no clock: the caller does those; the function only decides.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "hosts" / "laptop" / "wifi-guard-decision.ps1"
POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")

pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="powershell.exe is not on PATH (Windows-only script)")

SHOW = (
    "function Show($x) { [ordered]@{ Action = $x.Action; Toggles = $x.State.Toggles; "
    "Since = $(if ($x.State.NoInternetSince) { $x.State.NoInternetSince.ToString('yyyy-MM-dd HH:mm:ss') } else { $null }) } }"
)


def _at(minutes: int) -> str:
    return "([datetime]'2026-10-17 10:00:00').AddMinutes(" + str(minutes) + ")"


def _run(body: str) -> list[dict]:
    script = ". '" + str(SCRIPT) + "'; " + SHOW + "; $r = @(); " + body + "; ConvertTo-Json -InputObject @($r) -Compress -Depth 4"
    r = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


def test_script_is_ascii():
    SCRIPT.read_bytes().decode("ascii")


def test_dot_source_defines_the_function_and_prints_nothing():
    r = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
         ". '" + str(SCRIPT) + "'; (Get-Command Get-WifiGuardAction).CommandType"],
        capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip() == "Function"


def test_fresh_state_and_internet_ok_is_ok():
    [o] = _run("$a = Get-WifiGuardAction -State $null -InternetOk $true -Now " + _at(0) + "; $r += (Show $a)")
    assert o == {"Action": "ok", "Toggles": 0, "Since": None}


def test_first_failure_waits_and_sets_since():
    [o] = _run("$a = Get-WifiGuardAction -State $null -InternetOk $false -Now " + _at(0) + "; $r += (Show $a)")
    assert o == {"Action": "wait", "Toggles": 0, "Since": "2026-10-17 10:00:00"}


def test_fourteen_minutes_still_waits():
    [o] = _run(
        "$a = Get-WifiGuardAction -State $null -InternetOk $false -Now " + _at(0) + "; "
        "$b = Get-WifiGuardAction -State $a.State -InternetOk $false -Now " + _at(14) + "; $r += (Show $b)"
    )
    assert o == {"Action": "wait", "Toggles": 0, "Since": "2026-10-17 10:00:00"}


def test_exactly_fifteen_minutes_toggles():
    [o] = _run(
        "$a = Get-WifiGuardAction -State $null -InternetOk $false -Now " + _at(0) + "; "
        "$b = Get-WifiGuardAction -State $a.State -InternetOk $false -Now " + _at(15) + "; $r += (Show $b)"
    )
    assert o == {"Action": "toggle", "Toggles": 1, "Since": "2026-10-17 10:00:00"}


def test_still_failing_after_toggles_toggles_every_time_without_pause_or_cap():
    out = _run(
        "$a = Get-WifiGuardAction -State $null -InternetOk $false -Now " + _at(0) + "; $s = $a.State; "
        "$a = Get-WifiGuardAction -State $s -InternetOk $false -Now " + _at(15) + "; $s = $a.State; $r += (Show $a); "
        "for ($i = 1; $i -lt 100; $i++) { "
        "$a = Get-WifiGuardAction -State $s -InternetOk $false -Now ([datetime]'2026-10-17 10:00:00').AddMinutes(15 + $i); "
        "$s = $a.State; $r += (Show $a) }"
    )
    assert len(out) == 100
    assert all(o["Action"] == "toggle" for o in out)
    assert [o["Toggles"] for o in out] == list(range(1, 101))
    assert all(o["Since"] == "2026-10-17 10:00:00" for o in out)
    assert out[4]["Toggles"] == 5 and out[19]["Toggles"] == 20


def test_internet_back_after_toggles_is_done_and_resets_state():
    out = _run(
        "$a = Get-WifiGuardAction -State $null -InternetOk $false -Now " + _at(0) + "; $s = $a.State; "
        "$a = Get-WifiGuardAction -State $s -InternetOk $false -Now " + _at(15) + "; $s = $a.State; "
        "$a = Get-WifiGuardAction -State $s -InternetOk $false -Now " + _at(16) + "; $s = $a.State; "
        "$a = Get-WifiGuardAction -State $s -InternetOk $true -Now " + _at(17) + "; $r += (Show $a)"
    )
    assert out == [{"Action": "done", "Toggles": 0, "Since": None}]


def test_a_later_failure_starts_a_new_count_from_its_own_now():
    out = _run(
        "$a = Get-WifiGuardAction -State $null -InternetOk $false -Now " + _at(0) + "; $s = $a.State; "
        "$a = Get-WifiGuardAction -State $s -InternetOk $false -Now " + _at(15) + "; $s = $a.State; "
        "$a = Get-WifiGuardAction -State $s -InternetOk $true -Now " + _at(20) + "; $s = $a.State; "
        "$a = Get-WifiGuardAction -State $s -InternetOk $false -Now " + _at(30) + "; $s = $a.State; $r += (Show $a); "
        "$a = Get-WifiGuardAction -State $s -InternetOk $false -Now " + _at(44) + "; $s = $a.State; $r += (Show $a); "
        "$a = Get-WifiGuardAction -State $s -InternetOk $false -Now " + _at(45) + "; $s = $a.State; $r += (Show $a)"
    )
    assert out == [
        {"Action": "wait", "Toggles": 0, "Since": "2026-10-17 10:30:00"},
        {"Action": "wait", "Toggles": 0, "Since": "2026-10-17 10:30:00"},
        {"Action": "toggle", "Toggles": 1, "Since": "2026-10-17 10:30:00"},
    ]
