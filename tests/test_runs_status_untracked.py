"""`runs.py status` rows for untracked PoB process trees (issue #365, no PoB)."""

from __future__ import annotations

import subprocess
import sys
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import runs  # noqa: E402
from junkroan.runs import hosts as runs_hosts  # noqa: E402
from junkroan.runs.untracked import UntrackedTree  # noqa: E402

TREE = UntrackedTree(pid=12260, started=time.time() - 3600, cmd_head="python scripts/run_queue.py",
                     tag="new18-tpl-main3-s4-lap", slots=3)


def _status(tmp_path: Path, capsys, *extra: str) -> tuple[int, list[str]]:
    rc = runs.main(["--store", str(tmp_path / "jobs.jsonl"), "status", *extra])
    return rc, [l for l in capsys.readouterr().out.splitlines() if l.startswith("untracked")]


def test_one_untracked_tree_row(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    monkeypatch.setattr(runs, "collect_local", lambda store: [TREE])
    rc, rows = _status(tmp_path, capsys, "--host", "pc")
    assert rc == 0 and len(rows) == 1
    assert "12260" in rows[0] and "slots 3" in rows[0] and "new18-tpl-main3-s4-lap" in rows[0]
    # TREE's start is fixed at import; a long suite ages it, so read only that an age is shown
    assert re.search(r"started \d{4}-\d\d-\d\d \d\d:\d\d \(\d+ (h|min)", rows[0])


def test_no_untracked_no_row(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    monkeypatch.setattr(runs, "collect_local", lambda store: [])
    rc, rows = _status(tmp_path, capsys)
    assert rc == 0 and rows == []


def test_remote_host_failure_is_one_unreachable_line(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    monkeypatch.setattr(runs, "collect_local", lambda store: [TREE])

    def boom(cfg, script):
        raise subprocess.TimeoutExpired("ssh", 1)

    monkeypatch.setattr(runs_hosts, "run_on_host", boom)
    rc, rows = _status(tmp_path, capsys, "--host", "laptop")
    assert rc == 0 and len(rows) == 1 and rows[0].startswith("untracked: laptop unreachable (")


def test_remote_host_json_reply(tmp_path, capsys, monkeypatch) -> None:
    import json
    from dataclasses import asdict

    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    seen = []

    def fake(cfg, script):
        seen.append(script)
        return subprocess.CompletedProcess([], 0, stdout=json.dumps([asdict(TREE)]) + "\n", stderr="")

    monkeypatch.setattr(runs_hosts, "run_on_host", fake)
    rc, rows = _status(tmp_path, capsys, "--host", "laptop")
    assert rc == 0 and len(rows) == 1 and "12260" in rows[0]
    assert "status --untracked-json" in seen[0] and "JUNKROAN_HOST = 'laptop'" in seen[0]
