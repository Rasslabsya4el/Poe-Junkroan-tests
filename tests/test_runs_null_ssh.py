"""#364: a host with ``"ssh": null`` is never ssh-ed to; ``build_ssh_argv`` refuses a null alias."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from junkroan.runs.ssh_transport import build_ssh_argv  # noqa: E402
from test_runs_fillers import make_daemon  # noqa: E402


def test_null_ssh_host_is_skipped_and_the_other_is_read(tmp_path):
    seen = []

    def reader(cfg):
        seen.append(cfg.get("ssh"))
        return []

    daemon, _ = make_daemon(
        tmp_path,
        hosts_config={"pc": {}, "nohost": {"ssh": None}, "missing": {}, "laptop": {"ssh": "laptop"}},
        remote_store_reader=reader,
    )
    daemon.remote_handback_pass()
    assert seen == ["laptop"]


def test_build_ssh_argv_null_alias_raises():
    with pytest.raises(ValueError):
        build_ssh_argv({"ssh": None}, "echo 1")
    with pytest.raises(ValueError):
        build_ssh_argv({}, "echo 1")
    assert build_ssh_argv({"ssh": "laptop"}, "echo 1")[1] == "laptop"
