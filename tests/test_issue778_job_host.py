"""#778: the daemon names its own host to every job it starts."""
from __future__ import annotations

from pathlib import Path

import pytest

from test_runs_daemon import FakeLauncher, make_daemon


@pytest.mark.parametrize("host, inherited", [("laptop", None), ("pc", "laptop")])
def test_job_env_names_the_daemons_host(tmp_path: Path, monkeypatch, host: str, inherited: str | None) -> None:
    if inherited is None:
        monkeypatch.delenv("JUNKROAN_HOST", raising=False)
    else:
        monkeypatch.setenv("JUNKROAN_HOST", inherited)
    launcher = FakeLauncher()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, host=host)
    job = store.submit(host=host, priority="P2", tag="h", cmd="echo h", workers=1)
    assert daemon.tick().started == [job.id]
    assert launcher.started[-1]["env"]["JUNKROAN_HOST"] == host
