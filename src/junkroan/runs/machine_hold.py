"""This repo's side of the machine hold (#779): the runs daemon names its running jobs' pids for the core's keeper
(`tools.agentops.hold`), which suspends their trees while the machine mode is `play`. The daemon loop itself is
listed in `config/hold_protected.json` and is never suspended."""
from __future__ import annotations

from pathlib import Path

from tools.agentops import hold

NAME = "daemon_jobs"


def write_daemon_job_pids(root: Path, pids: list[int]) -> None:
    hold.write_root_pids(root, NAME, pids)
