"""The filler switch and where a filler's exports go (issues #132, #517, #751).

A **Filler** is a PoB job no issue waits for (``GLOSSARY.md``). Which fillers a host starts, how many and
what they make is ``junkroan.runs.weekly_fillers`` plus ``Daemon.filler_pass``; this module keeps only:

* the per-host switch (``<host>.fillers`` in ``config/hosts.json``; ``runs.py fillers <host> on|off``);
* the folder the daemon moves a filler run's XML exports into.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

#: Where a filler's XML exports end up: the folder the RUN wrote is moved under
#: ``Documents\Path of Building\Builds\Junkroan\fillers\<run>``, apart from the folders the owner
#: reads. It is a move by the daemon, not a switch in the run: a run pinned to an older commit has no
#: such switch. See ``Daemon.sweep_filler_exports``.
EXPORT_DIR_NAME = "fillers"
#: The name ``scripts/benchmark.py`` gives a run's folder in the owner's PoB Builds folder:
#: ``benchmark <YYYY-MM-DD> <HHMM>-<tag>``.
EXPORT_RUN_GLOB = "benchmark ????-??-?? ????-{tag}"


def export_run_glob(tag: str) -> str:
    """The glob that matches the PoB Builds folder a run tagged ``tag`` wrote (and only that one)."""

    return EXPORT_RUN_GLOB.format(tag=tag)


def fillers_switch(host: str, *, flag: bool, hosts_reader: Callable[[], Mapping[str, Any]] | None = None) -> Callable[[], bool]:
    """#517: True when ``flag`` (the daemon's --fillers) or hosts.json's ``<host>.fillers`` is true."""

    def check() -> bool:
        if flag:
            return True
        try:
            if hosts_reader is None:
                from junkroan.runs.hosts import effective_fillers
                return effective_fillers(host)
            return (hosts_reader().get(host) or {}).get("fillers") is True
        except Exception:
            return False

    return check


@dataclass(frozen=True, slots=True)
class FillerSwitch:
    """What a daemon holds as ``fillers``: ``enabled()`` is read at every filler decision (#751 rule 1)."""

    enabled: Callable[[], bool]


__all__ = [
    "EXPORT_DIR_NAME",
    "EXPORT_RUN_GLOB",
    "FillerSwitch",
    "export_run_glob",
    "fillers_switch",
]
