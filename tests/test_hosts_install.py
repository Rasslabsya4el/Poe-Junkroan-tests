"""Every Task Scheduler job `tools/hosts/install.ps1` names has its script file in the repo (#75).

Parses the ``TaskName = '...'; Script = '...'`` pairs out of the PowerShell literal (no PowerShell
runtime needed to run this test) and checks each ``Script`` exists under ``tools/hosts/<host>/``.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INSTALL_PS1 = PROJECT_ROOT / "tools" / "hosts" / "install.ps1"

# One `<host> = @( ... )` block per known host, each holding `[pscustomobject]@{ ... }` entries
# with `TaskName = '...'` and `Script = '...'` (single-quoted PowerShell string literals).
_KNOWN_HOSTS = ("laptop", "pc")
_ENTRY_RE = re.compile(
    r"TaskName\s*=\s*'(?P<task>[^']+)'.*?Script\s*=\s*'(?P<script>[^']+)'",
    re.DOTALL,
)


def _parse_task_defs(text: str) -> dict[str, list[tuple[str, str]]]:
    """{"laptop": [(task_name, script), ...], "pc": [...]} from the ``$taskDefs`` hashtable."""

    start = text.index("$taskDefs = @{")
    end = text.index("\n}", start)
    body = text[start:end]

    # Split the hashtable body at each known host's own `<host>\s*=\s*@\(` marker, in the order
    # they appear, so each host's slice runs up to the next host's marker (or the end of the body).
    found = []
    for host in _KNOWN_HOSTS:
        marker = re.search(rf"\b{re.escape(host)}\s*=\s*@\(", body)
        if marker:
            found.append((marker.start(), host))
    markers = sorted(found)
    defs: dict[str, list[tuple[str, str]]] = {}
    for i, (pos, host) in enumerate(markers):
        end_pos = markers[i + 1][0] if i + 1 < len(markers) else len(body)
        slice_ = body[pos:end_pos]
        defs[host] = [
            (entry.group("task"), entry.group("script")) for entry in _ENTRY_RE.finditer(slice_)
        ]
    return defs


def test_install_ps1_exists():
    assert INSTALL_PS1.is_file(), INSTALL_PS1


def test_every_task_names_a_script_that_is_present_in_the_repo():
    text = INSTALL_PS1.read_text(encoding="utf-8")
    defs = _parse_task_defs(text)

    assert "laptop" in defs
    assert "pc" in defs
    assert len(defs["laptop"]) == 6, defs["laptop"]  # + the runs daemon watchdog (#353) + the Wi-Fi guard (#1188)

    for host, entries in defs.items():
        host_dir = PROJECT_ROOT / "tools" / "hosts" / host
        for task_name, script in entries:
            script_path = host_dir / script
            assert script_path.is_file(), (
                f"task {task_name!r} on host {host!r} names script {script!r}, "
                f"not found at {script_path}"
            )


def test_laptop_task_names_match_the_live_scheduler():
    """Sanity check against the names read off the laptop over SSH on 2026-09-26 (issue #75)."""

    text = INSTALL_PS1.read_text(encoding="utf-8")
    defs = _parse_task_defs(text)
    names = {task_name for task_name, _ in defs["laptop"]}
    assert names == {
        "junkroan telemetry",
        "junkroan power guard",
        "junkroan restore after movie",
        "junkroan close browsers",
        "junkroan runs daemon ensure",  # #353, not yet on the live scheduler until the keymaster installs it
        "junkroan wifi guard",          # #1188, every minute, re-enables the Wi-Fi adapter after 15 min without internet
    }


def test_wifi_guard_entry_runs_every_minute_as_system_and_never_touches_a_run():
    """#1188: the Wi-Fi guard is a SYSTEM task every 1 min (it needs the adapter rights) and stops no PoB run."""

    text = INSTALL_PS1.read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if "junkroan wifi guard" in ln)
    for part in ("Script = 'wifi-guard.ps1'", "Sc = 'MINUTE'", "Mo = '1'", "Hidden = $true", "System = $true",
                 "TouchesRun = $false"):
        assert part in line, part


def test_power_guard_entry_names_its_script_and_the_action_is_built_from_host_dir():
    """#367: the task runs the repo's own tools/hosts/laptop/power-guard.ps1, never a copy elsewhere."""

    text = INSTALL_PS1.read_text(encoding="utf-8")
    assert ("junkroan power guard", "power-guard.ps1") in _parse_task_defs(text)["laptop"]
    assert "$hostDir = Join-Path $PSScriptRoot $HostName" in text
    assert "$scriptPath = Join-Path $hostDir $def.Script" in text
    assert '-File `"$scriptPath`""' in text
    assert "laptop-baseline" not in text
    # a missing script throws
    assert re.search(r"if \(-not \(Test-Path \$scriptPath\)\) \{\s*throw ", text)


RUN_HIDDEN_VBS = PROJECT_ROOT / "tools" / "hosts" / "run-hidden.vbs"


def _user_task_count(text: str) -> int:
    """Number of task definitions with ``System = $false`` (both hosts)."""

    return len(re.findall(r"System\s*=\s*\$false", text))


def test_user_tasks_start_through_wscript_run_hidden_never_a_console_powershell():
    """#396: a task that runs as the interactive user must not start powershell.exe directly (its console
    flashes on the desktop). The installer builds the action in two branches on ``$def.System``."""

    text = INSTALL_PS1.read_text(encoding="utf-8")
    assert _user_task_count(text) >= 2  # the runs daemon watchdog on laptop and pc

    # the user branch is the `else` of `if ($def.System)`; no powershell action may sit there
    m = re.search(r"if \(\$def\.System\) \{(?P<system>.*?)\n    \}\s*else \{(?P<user>.*?)\n    \}", text, re.DOTALL)
    assert m, "action is not split on $def.System"
    assert "powershell.exe -NoProfile" in m.group("system")
    assert "wscript.exe" in m.group("user") and "run-hidden.vbs" in m.group("user")
    assert "powershell.exe -NoProfile" not in m.group("user")


def test_run_hidden_vbs_runs_hidden_waits_and_passes_the_exit_code():
    text = RUN_HIDDEN_VBS.read_text(encoding="utf-8")
    assert re.search(r"\.Run\(.*,\s*0\s*,\s*True\)", text)
    assert "WScript.Quit" in text
    assert "powershell.exe -NoProfile -ExecutionPolicy Bypass -File" in text


def test_ensure_script_installs_pytest_before_the_watchdog_line():
    # #463: the laptop daemon's python must have pytest; the check sits before the watchdog start.
    text = (INSTALL_PS1.parent / "laptop" / "runs-daemon-ensure.ps1").read_text(encoding="utf-8")
    check = text.index("-m pytest --version")
    install = text.index("-m pip install --user --quiet pytest")
    watchdog = text.index("-m junkroan.runs.watchdog")
    assert check < install < watchdog
    assert "install --user" in INSTALL_PS1.read_text(encoding="utf-8")


def test_wifi_power_script_is_called_for_the_laptop_and_carries_the_three_settings():
    """#382: install.ps1 -Host laptop applies tools/hosts/laptop/wifi-power.ps1; the script turns off the adapter's
    AllowComputerToTurnOffDevice, USB selective suspend on AC and DC, and the driver's power-saving property."""

    install = INSTALL_PS1.read_text(encoding="utf-8")
    assert "'wifi-power.ps1'" in install
    assert re.search(r"if \(\$HostName -eq 'laptop'\) \{\s*\$wifiPower", install)
    assert "-WhatIf" in install.split("wifi-power.ps1", 1)[1].split("}", 1)[0]

    text = (INSTALL_PS1.parent / "laptop" / "wifi-power.ps1").read_text(encoding="utf-8")
    assert "SupportsShouldProcess" in text
    assert "MSPower_DeviceEnable" in text and "$i.Enable = $false" in text
    assert "48e6b7a6-50f5-4782-a5d4-53bb8f07e226" in text
    assert "/set${kind}valueindex" in text and "@('ac', 'dc')" in text
    assert "powercfg /setactive SCHEME_CURRENT" in text
    assert "Set-NetAdapterAdvancedProperty" in text


def test_wifi_vht_script_is_called_for_the_laptop_and_arms_the_guard_first():
    """#522: install.ps1 -Host laptop calls wifi-vht.ps1 (with -WhatIf); the script registers the guard task
    before the apply task, as SYSTEM, logs to wifi-guard.log and unregisters both tasks."""

    install = INSTALL_PS1.read_text(encoding="utf-8")
    assert re.search(r"if \(\$HostName -eq 'laptop'\) \{.*'wifi-vht\.ps1'", install, re.DOTALL)
    assert "-WhatIf" in install.split("wifi-vht.ps1", 1)[1].split("}", 1)[0]

    text = (INSTALL_PS1.parent / "laptop" / "wifi-vht.ps1").read_text(encoding="utf-8")
    for needle in (
        "SupportsShouldProcess",
        "'VHT 2.4G IOT'",
        "'Disable'",
        "junkroan wifi-vht guard",
        "junkroan wifi-vht apply",
        "Register-ScheduledTask",
        "SYSTEM",
        "wifi-guard.log",
        "Unregister-ScheduledTask",
    ):
        assert needle in text, needle
    assert re.search(r"Id\s*=\s*8001", text)
    default_mode = text.split("# default mode", 1)[1]
    guard = default_mode.index("Register-ScheduledTask -TaskName $guardTask")
    apply = default_mode.index("Register-ScheduledTask -TaskName $applyTask")
    assert guard < apply


def test_wifi_vht_script_parses_without_errors():
    powershell = shutil.which("powershell")
    if powershell is None:
        pytest.skip("powershell not on PATH")
    script = INSTALL_PS1.parent / "laptop" / "wifi-vht.ps1"
    cmd = (
        "$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile("
        f"'{script}', [ref]$null, [ref]$e); $e.Count"
    )
    out = subprocess.run([powershell, "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "0", out.stdout + out.stderr


def test_wifi_mode_script_is_called_after_wifi_vht_and_arms_the_guard_first():
    """#522 (d): install.ps1 -Host laptop calls wifi-mode.ps1 (with -WhatIf) right after wifi-vht.ps1; the script
    records the previous value, registers the guard task before the apply task, as SYSTEM, and logs to wifi-guard.log."""

    install = INSTALL_PS1.read_text(encoding="utf-8")
    assert install.index("'wifi-vht.ps1'") < install.index("'wifi-mode.ps1'")
    assert "-WhatIf" in install.split("wifi-mode.ps1", 1)[1].split("}", 1)[0]

    text = (INSTALL_PS1.parent / "laptop" / "wifi-mode.ps1").read_text(encoding="utf-8")
    for needle in (
        "SupportsShouldProcess",
        "'Wireless Mode'",
        "'IEEE 802.11b/g/n'",
        "junkroan wifi-mode guard",
        "junkroan wifi-mode apply",
        "wifi-mode-state.json",
        "Register-ScheduledTask",
        "SYSTEM",
        "wifi-guard.log",
        "Unregister-ScheduledTask",
    ):
        assert needle in text, needle
    assert re.search(r"Id\s*=\s*8001", text)
    default_mode = text.split("# default mode", 1)[1]
    guard = default_mode.index("Register-ScheduledTask -TaskName $guardTask")
    apply = default_mode.index("Register-ScheduledTask -TaskName $applyTask")
    assert guard < apply


def test_wifi_mode_script_parses_without_errors():
    powershell = shutil.which("powershell")
    if powershell is None:
        pytest.skip("powershell not on PATH")
    script = INSTALL_PS1.parent / "laptop" / "wifi-mode.ps1"
    cmd = (
        "$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile("
        f"'{script}', [ref]$null, [ref]$e); $e.Count"
    )
    out = subprocess.run([powershell, "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "0", out.stdout + out.stderr


# -- #887: install.ps1 -Check (read-only, one source of the action string) ---------------------------------

import json

HOSTS_DIR = INSTALL_PS1.parent
ENSURE = "junkroan runs daemon ensure"


def _expected_action(host: str, script: str, *, system: bool, hidden: bool) -> str:
    path = HOSTS_DIR / host / script
    if system:
        style = "-WindowStyle Hidden " if hidden else ""
        return f'powershell.exe -NoProfile {style}-ExecutionPolicy Bypass -File "{path}"'
    return f'wscript.exe //B //Nologo "{HOSTS_DIR / "run-hidden.vbs"}" "{path}"'


def _laptop_actions() -> dict[str, str]:
    return {
        "junkroan telemetry": _expected_action("laptop", "laptop-telemetry.ps1", system=True, hidden=True),
        "junkroan power guard": _expected_action("laptop", "power-guard.ps1", system=True, hidden=True),
        "junkroan restore after movie": _expected_action("laptop", "restore-after-movie.ps1", system=True, hidden=False),
        "junkroan close browsers": _expected_action("laptop", "close-browsers.ps1", system=True, hidden=True),
        ENSURE: _expected_action("laptop", "runs-daemon-ensure.ps1", system=False, hidden=True),
        "junkroan wifi guard": _expected_action("laptop", "wifi-guard.ps1", system=True, hidden=True),
    }


def _run_check(tmp_path: Path, host: str, actions: dict[str, str]):
    powershell = shutil.which("powershell")
    if powershell is None:
        pytest.skip("powershell not on PATH")
    reg = tmp_path / "registered.json"
    reg.write_text(json.dumps([{"TaskName": k, "Action": v} for k, v in actions.items()]), encoding="utf-8")
    out = subprocess.run(
        [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(INSTALL_PS1),
         "-HostName", host, "-Check", "-RegisteredJson", str(reg)],
        capture_output=True, text=True, timeout=120,
    )
    return out.returncode, out.stdout


def test_check_pc_correct_action_is_same(tmp_path):
    action = _expected_action("pc", "runs-daemon-ensure.ps1", system=False, hidden=True)
    code, out = _run_check(tmp_path, "pc", {ENSURE: action})
    assert code == 0, out
    assert f"{ENSURE}: same" in out
    assert "check: 1 same, 0 differs, 0 missing" in out


def test_check_pc_old_powershell_action_differs(tmp_path):
    old = f'powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{HOSTS_DIR / "pc" / "runs-daemon-ensure.ps1"}"'
    code, out = _run_check(tmp_path, "pc", {ENSURE: old})
    assert code != 0, out
    assert out.count(": differs") == 1, out
    assert "check: 0 same, 1 differs, 0 missing" in out


def test_check_laptop_partial_json_reports_missing(tmp_path):
    actions = _laptop_actions()
    partial = {k: actions[k] for k in ("junkroan telemetry", ENSURE)}
    code, out = _run_check(tmp_path, "laptop", partial)
    assert code != 0, out
    assert out.count(": missing") == 3, out  # power guard, close browsers, wifi guard
    assert "junkroan telemetry: same" in out
    assert "junkroan restore after movie: absent (one-shot)" in out
    assert "check: 2 same, 0 differs, 3 missing" in out


def test_check_laptop_all_tasks_correct(tmp_path):
    code, out = _run_check(tmp_path, "laptop", _laptop_actions())
    assert code == 0, out
    assert out.count(": same") == 6, out
    assert "check: 6 same, 0 differs, 0 missing" in out


# -- #888: -Only and the one-shot in -Check -------------------------------------------------------------

ONE_SHOT = "junkroan restore after movie"


def _run_ps(args: list[str]):
    powershell = shutil.which("powershell")
    if powershell is None:
        pytest.skip("powershell not on PATH")
    out = subprocess.run(
        [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(INSTALL_PS1), *args],
        capture_output=True, text=True, timeout=120,
    )
    return out.returncode, out.stdout + out.stderr


def test_only_whatif_lists_exactly_the_named_task():
    code, out = _run_ps(["-HostName", "laptop", "-Only", "junkroan telemetry", "-WhatIf"])
    assert code == 0, out
    assert out.count("WhatIf: schtasks") == 1, out
    assert "/TN junkroan telemetry" in out
    assert "power guard" not in out and "wifi" not in out.lower()


def test_only_two_names_whatif_registers_two_of_five():
    code, out = _run_ps(["-HostName", "laptop", "-Only", "junkroan telemetry,junkroan close browsers", "-WhatIf"])
    assert code == 0, out
    assert out.count("WhatIf: schtasks") == 2, out


def test_only_wifi_guard_whatif_allows_start_and_keeps_running_on_battery():
    # #1188: the guard must run on battery too; the -WhatIf run names the settings call it would make
    code, out = _run_ps(["-HostName", "laptop", "-Only", "junkroan wifi guard", "-WhatIf"])
    assert code == 0, out
    assert "WhatIf: Set-ScheduledTask" in out, out
    assert "AllowStartIfOnBatteries" in out, out
    assert "DontStopIfGoingOnBatteries" in out, out


def test_only_unknown_name_is_an_error():
    code, out = _run_ps(["-HostName", "laptop", "-Only", "junkroan nope", "-WhatIf"])
    assert code != 0, out
    assert "unknown" in out
    assert "WhatIf: schtasks" not in out


def test_only_with_check_checks_only_that_task(tmp_path):
    reg = tmp_path / "r.json"
    reg.write_text(json.dumps([{"TaskName": "junkroan telemetry", "Action": _laptop_actions()["junkroan telemetry"]}]), encoding="utf-8")
    code, out = _run_ps(["-HostName", "laptop", "-Only", "junkroan telemetry", "-Check", "-RegisteredJson", str(reg)])
    assert code == 0, out
    assert "check: 1 same, 0 differs, 0 missing" in out


def test_check_one_shot_not_registered_is_absent_not_missing(tmp_path):
    actions = _laptop_actions()
    del actions[ONE_SHOT]
    code, out = _run_check(tmp_path, "laptop", actions)
    assert code == 0, out
    assert f"{ONE_SHOT}: absent (one-shot)" in out
    assert "check: 5 same, 0 differs, 0 missing" in out


@pytest.mark.parametrize("gone", ["junkroan runs daemon ensure", "junkroan telemetry"])
def test_check_missing_recurring_task_still_missing(tmp_path, gone):
    actions = _laptop_actions()
    del actions[ONE_SHOT]
    del actions[gone]
    code, out = _run_check(tmp_path, "laptop", actions)
    assert code != 0, out
    assert f"{gone}: missing" in out
    assert "check: 4 same, 0 differs, 1 missing" in out


def test_check_one_shot_registered_but_different_still_differs(tmp_path):
    actions = _laptop_actions()
    actions[ONE_SHOT] = "powershell.exe -File C:/elsewhere/restore-after-movie.ps1"
    code, out = _run_check(tmp_path, "laptop", actions)
    assert code != 0, out
    assert f"{ONE_SHOT}: differs" in out


# -- #888: a live run is left alone when -Only names only tasks that do not touch a run ---------------------

import os
import sys


def _run_with_fake_live_run(tmp_path: Path, args: list[str]):
    """install.ps1 with a dummy interpreter process the live-run check matches (command line holds `spawn_main`)
    and a fake schtasks.cmd first on PATH that logs its first argument; returns (code, output, [create calls], pid)."""
    powershell = shutil.which("powershell")
    if powershell is None:
        pytest.skip("powershell not on PATH")
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    log = tmp_path / "schtasks.log"
    (bin_dir / "schtasks.cmd").write_text(f'@echo off\r\n>>"{log}" echo %1\r\n', encoding="ascii")
    env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    dummy = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)", "spawn_main"],
        creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        out = subprocess.run(
            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(INSTALL_PS1), *args],
            capture_output=True, text=True, timeout=120, env=env, creationflags=flags,
        )
    finally:
        dummy.kill()
        dummy.wait()
    calls = log.read_text(encoding="ascii").split() if log.exists() else []
    return out.returncode, out.stdout + out.stderr, [c for c in calls if c.lower() == "/create"], dummy.pid


def test_only_non_touching_tasks_with_live_run_register_and_say_left_alone(tmp_path):
    code, out, creates, pid = _run_with_fake_live_run(
        tmp_path, ["-HostName", "laptop", "-Only", "junkroan telemetry,junkroan runs daemon ensure"])
    assert code == 0, out
    assert len(creates) == 2, out
    left = [line for line in out.splitlines() if line.startswith("left alone: live run pid(s)")]
    assert len(left) == 1, out
    assert str(pid) in re.findall(r"\d+", left[0]), out


def test_only_touching_task_with_live_run_still_refuses(tmp_path):
    code, out, creates, _ = _run_with_fake_live_run(
        tmp_path, ["-HostName", "laptop", "-Only", "junkroan close browsers"])
    assert code != 0, out
    assert "Refusing" in out
    assert creates == []


def test_no_only_with_live_run_still_refuses(tmp_path):
    code, out, creates, _ = _run_with_fake_live_run(tmp_path, ["-HostName", "laptop"])
    assert code != 0, out
    assert "Refusing" in out
    assert creates == []
