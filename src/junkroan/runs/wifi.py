"""Laptop wifi check (issue #382): called by the watchdog each tick, logs a lost wifi, reconnects once.

Each tick reads the default gateway (``route print -4 0.0.0.0``, lowest-metric row whose gateway is an
IP), pings it, and reads ``netsh wlan show interfaces``. While wlan is ``connected`` its Profile is saved
to the state file. When the gateway does not answer, one log line is written; if wlan State is also
``disconnected`` (or lists no interface), ``netsh wlan connect name=<profile>`` runs once. The next tick
tries again. No other netsh or network command is ever run. ``check`` never raises.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Callable

Runner = Callable[[list[str]], tuple[int, str]]
TIMEOUT = 10

_ROUTE_RE = re.compile(r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+(\d{1,3}(?:\.\d{1,3}){3})\s+\S+\s+(\d+)\s*$")


def default_run(cmd: list[str]) -> tuple[int, str]:
    kwargs = {}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT, **kwargs)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def parse_gateway(route_output: str) -> str | None:
    """The gateway of the lowest-metric default route in ``route print -4`` output, or None."""

    best: tuple[int, str] | None = None
    for line in route_output.splitlines():
        m = _ROUTE_RE.match(line)
        if m and (best is None or int(m.group(2)) < best[0]):
            best = (int(m.group(2)), m.group(1))
    return best[1] if best else None


def parse_wlan(output: str) -> dict[str, str]:
    """State/SSID/Signal/Profile of the connected interface (else the first one) from netsh output."""

    blocks: list[dict[str, str]] = []
    for line in output.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        if key == "Name":
            blocks.append({})
        if blocks and key in ("State", "SSID", "Signal", "Profile") and key not in blocks[-1]:
            blocks[-1][key] = value
    if not blocks:
        return {}
    for b in blocks:
        if b.get("State", "").lower() == "connected":
            return b
    return blocks[0]


def check(
    *,
    run: Runner = default_run,
    now: Callable[[], datetime] = datetime.now,
    log_path: Path,
    state_path: Path,
) -> str:
    """One tick. Returns "ok", "unreachable" or "error"; never raises."""

    def log(msg: str) -> None:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"{now().strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
        except Exception:
            pass

    try:
        gateway = None
        try:
            _rc, route = run(["route", "print", "-4", "0.0.0.0"])
            gateway = parse_gateway(route)
        except Exception as exc:
            log(f"gateway read failed: {exc!r}")
        ok = False
        if gateway:
            try:
                ok = run(["ping", "-n", "1", "-w", "2000", gateway])[0] == 0
            except Exception as exc:
                log(f"ping {gateway} failed: {exc!r}")
        wlan: dict[str, str] = {}
        try:
            wlan = parse_wlan(run(["netsh", "wlan", "show", "interfaces"])[1])
        except Exception as exc:
            log(f"netsh wlan show interfaces failed: {exc!r}")
        state = wlan.get("State", "")
        profile = wlan.get("Profile", "")
        if state.lower() == "connected" and profile:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps({"profile": profile, "seen": now().isoformat()}),
                                  encoding="utf-8")
        if ok:
            return "ok"
        log(f"gateway {gateway or 'none'} unreachable; wlan State={state or 'none'} "
            f"SSID={wlan.get('SSID', 'none')} Signal={wlan.get('Signal', 'none')}")
        if state.lower() not in ("disconnected", ""):
            return "unreachable"
        saved = ""
        try:
            saved = json.loads(state_path.read_text(encoding="utf-8")).get("profile", "")
        except Exception:
            pass
        if not saved:
            log("disconnected, no known profile; no action")
            return "unreachable"
        rc, out = run(["netsh", "wlan", "connect", f"name={saved}"])
        first = next((ln.strip() for ln in out.splitlines() if ln.strip()), "")
        log(f"connect name={saved} -> rc {rc}: {first}")
        return "unreachable"
    except Exception as exc:
        log(f"wifi check error: {exc!r}")
        return "error"
