"""Which host runs a merge's test suite (#685): the laptop when it would give more workers than the PC.

Pure decision (`choose_suite_host`), a bounded never-raising reading of the laptop (`read_laptop`) and
the caps from `config/hosts.json` (`caps_from_config`). No wiring into merge.py here.
"""

from __future__ import annotations

import json
import re
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT / "src", _ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from junkroan.pob.slot_budget import SUITE_PER_WORKER_GB, suite_workers_from_readings  # noqa: E402


@dataclass(frozen=True)
class SuiteHostChoice:
    host: str  # "pc" | "laptop"
    pc_workers: int
    laptop_workers: int | None
    line: str


def _workers(readings: dict, cap: int, reserve_gb: float, floor_gb: float | None = None) -> tuple[int, str]:
    """#966: ``floor_gb`` = the host's run-queue free-RAM floor (``min_free_ram_gb``); free RAM under it -> 1 worker."""
    return suite_workers_from_readings(
        int(readings["logical_cores"]), readings.get("cpu_percent"), readings.get("free_ram_gb"),
        reserve_gb, SUITE_PER_WORKER_GB, cap, pob_cpu_percent=readings.get("pob_cpu_percent"),
        full_run_cpu_percent=readings.get("full_run_cpu_percent"), floor_gb=floor_gb)


def choose_suite_host(pc: dict, laptop: dict | None, *, laptop_failure: str | None, pc_cap: int,
                      laptop_cap: int, pc_reserve_gb: float, laptop_reserve_gb: float,
                      laptop_factor: float, pc_floor_gb: float | None = None,
                      laptop_floor_gb: float | None = None) -> SuiteHostChoice:
    """Laptop only when ``laptop_workers / laptop_factor > pc_workers`` (strictly); a missing or failed
    laptop reading means the PC, and the line says why. #966: a host whose free RAM is under its
    ``*_floor_gb`` (None = no floor) counts one worker."""

    pc_n, pc_line = _workers(pc, pc_cap, pc_reserve_gb, pc_floor_gb)
    if laptop is None or laptop_failure:
        why = laptop_failure or "no reading"
        return SuiteHostChoice("pc", pc_n, None, f"host pc: workers {pc_n} ({pc_line}); laptop: {why}")
    lap_n, lap_line = _workers(laptop, laptop_cap, laptop_reserve_gb, laptop_floor_gb)
    if lap_n / laptop_factor > pc_n:
        return SuiteHostChoice("laptop", pc_n, lap_n,
                               f"host laptop: workers {lap_n} ({lap_line}); pc would give {pc_n}")
    return SuiteHostChoice("pc", pc_n, lap_n, f"host pc: workers {pc_n} ({pc_line}); laptop: workers {lap_n}")


def read_laptop(timeout_s: float = 10.0, reader: Callable[[str], dict] | None = None
                ) -> tuple[dict | None, str | None]:
    """The laptop's readings, bounded by ``timeout_s``; any failure returns ``(None, reason)``, never raises."""

    box: dict[str, Any] = {}

    def work() -> None:
        try:
            fn = reader
            if fn is None:
                from suite_on_host import read_readings as fn  # scripts/ is on sys.path
            box["ok"] = fn("laptop")
        except BaseException as exc:  # noqa: BLE001 - the contract is "never raises"
            box["err"] = str(exc) or type(exc).__name__

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    thread.join(timeout_s)
    if thread.is_alive():
        return None, f"readings timed out after {timeout_s:g} s"
    if "err" in box:
        return None, box["err"]
    data = box.get("ok")
    if not isinstance(data, dict) or "logical_cores" not in data:
        return None, "readings: unreadable answer"
    return data, None


def caps_from_config(config: dict | None = None) -> dict[str, Any]:
    """Keyword arguments of `choose_suite_host` that come from config/hosts.json (normal mode, day budget)."""

    if config is None:
        config = json.loads((_ROOT / "config" / "hosts.json").read_text(encoding="utf-8"))
    pc, laptop = config["pc"], config["laptop"]
    from junkroan.runs import hosts as runs_hosts  # #839: the PC cap follows the period (3 by day, 6 by night)
    pc_entry = pc["modes"]["normal"]
    pc_day = pc_entry.get(runs_hosts.current_period(pc_entry)) or pc_entry["day"]
    lap_day = laptop["modes"]["normal"]["day"]
    return {
        "pc_cap": int(pc_day["merge_suite"]), "laptop_cap": int(lap_day["merge_suite"]),
        "pc_reserve_gb": float(pc_day["merge_suite_reserve_gb"]),
        "laptop_reserve_gb": float(lap_day["merge_suite_reserve_gb"]),
        "laptop_factor": float(laptop.get("loop_seconds_factor", 1.0)),
        # #966: the run queue's floor, the same key the runs daemon reads (never a second number)
        "pc_floor_gb": float(pc_day["min_free_ram_gb"]),
        "laptop_floor_gb": float(lap_day["min_free_ram_gb"]),
    }


_SKIPPED_RE = re.compile(r"(\d+) skipped")


def parse_skipped(text: str) -> int | None:
    """The skipped count of the LAST pytest summary line naming one ("... 88 skipped ..."); None when none."""
    found = None
    for line in text.splitlines():
        m = _SKIPPED_RE.search(line)
        if m and (" passed" in line or " failed" in line or line.lstrip().startswith("=")):
            found = int(m.group(1))
    return found


def pc_last_skipped(root: Path | None = None) -> int | None:
    """``skipped`` of the PC's last full suite on main (``var/agentops/test_map/meta.json``, written by full_run)."""
    from .test_select import map_dir, read_meta
    meta = read_meta(map_dir(root or _ROOT)) or {}
    v = meta.get("skipped")
    return v if isinstance(v, int) else None


def skipped_note(laptop_text: str, root: Path | None = None) -> str:
    """The merge-line text of a laptop suite: ``skipped N (pc last M)`` or ``(pc last unknown)``; "" without a count."""
    n = parse_skipped(laptop_text)
    if n is None:
        return ""
    m = pc_last_skipped(root)
    return f"skipped {n} (pc last {m if m is not None else 'unknown'})"
