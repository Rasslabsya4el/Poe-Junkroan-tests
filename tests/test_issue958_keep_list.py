"""#958 row 38 finding: the laptop's `sleep` keep list holds the names the live close-preview of 2026-10-14 would
have closed although the weekly core run or the link needs them (python.exe, tailscale-ipn.exe, ...)."""

from __future__ import annotations

import json
from pathlib import Path

from junkroan.runs.close_set import Proc, close_set

from tests import test_issue958_close_set as rows

ROOT = Path(__file__).resolve().parents[1]
LIVE_CLOSED = [  # the 11 CLOSED lines of `owner laptop close-preview`, 14.10 10:0x
    "DefenderSessionHelper.exe", "python.exe", "python.exe", "python.exe", "python.exe", "python.exe",
    "RAVBg64.exe", "RAVBg64.exe", "RtkNGUI64.exe", "tailscale-ipn.exe", "ThrottleStop.exe",
]


def _sleep_preset():
    return json.loads((ROOT / "config" / "hosts.json").read_text(encoding="utf-8"))["laptop"]["owner_presets"]["sleep"]


def test_every_live_closed_name_is_in_the_keep_list():
    preset = _sleep_preset()
    assert preset["close_mode"] == "allow-list"
    keep = {k.lower() for k in preset["keep"]}
    assert {n.lower() for n in LIVE_CLOSED} <= keep


def test_the_live_snapshot_with_the_keep_list_closes_none_of_them_but_still_closes_chrome():
    preset = _sleep_preset()
    live = [Proc(7000 + i, 1, name, f"C:\Program Files\X\{name}", rows.CONSOLE, rows.USER)
            for i, name in enumerate(LIVE_CLOSED)]
    procs = [rows.row33_chrome(), *live]
    closed, _kept = close_set(procs, console_session=rows.CONSOLE, user=rows.USER, system_root=rows.ROOT,
                              protected_pids={rows.DAEMON}, keep=preset["keep"], self_pid=rows.SELF)
    assert [p.name for p in closed] == ["chrome.exe"]
