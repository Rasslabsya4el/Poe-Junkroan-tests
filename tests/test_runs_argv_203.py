"""#203: a job keeps its argv (quotes survive), locally and over the remote submit line. No PoB."""

from __future__ import annotations
from conftest import pc_only

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import runs  # noqa: E402
from junkroan.runs import hosts as runs_hosts  # noqa: E402
from junkroan.runs.daemon import ProcessLauncher  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402

TRICKY = ["python", "-c", "import sys; print(sys.argv[1:])", "a b", 'c"d', ""]
EXPECTED = "['a b', 'c\"d', '']"


def _run(launch_arg, tmp_path: Path) -> str:
    out = tmp_path / "job.out"
    child = ProcessLauncher().start(launch_arg, cwd=tmp_path, out=out, env=dict(os.environ))
    deadline = time.time() + 30
    while child.poll() is None and time.time() < deadline:
        time.sleep(0.05)
    assert child.poll() == 0
    child.close()
    return out.read_text(encoding="utf-8").strip()


@pc_only
def test_row1_submit_then_launch_keeps_the_quotes(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("JUNKROAN_RUNS_EVENTS", str(tmp_path / "events.jsonl"))
    store_path = tmp_path / "jobs.jsonl"
    rc = runs.main(["--store", str(store_path), "submit", "--issue", "1", "--host", "pc", "--priority", "P1",
                    "--again", "--", *TRICKY])
    assert rc == 0
    job = Store(store_path).get(capsys.readouterr().out.strip())
    # what the daemon hands its launcher: the argv list when the record has one, else the cmd line
    launch = list(job.argv) if getattr(job, "argv", None) else job.cmd
    assert _run(launch, tmp_path) == EXPECTED


def test_row3_old_record_with_only_cmd_runs_through_the_shell(tmp_path: Path) -> None:
    store_path = tmp_path / "jobs.jsonl"
    job = Store(store_path).submit(host="pc", priority="P1", tag="old203", cmd='python -c "print(1+1)"')
    job = Store(store_path).get(job.id)
    assert job.argv is None
    assert _run(job.cmd, tmp_path) == "2"


def _ps_tokens(line: str) -> list[str]:
    """Split a line of PowerShell single-quoted literals (the form `_quote_ps_arg` writes)."""
    toks, i = [], 0
    while i < len(line):
        if line[i] == "'":
            j, buf = i + 1, ""
            while True:
                if line[j] == "'" and line[j + 1:j + 2] == "'":
                    buf += "'"
                    j += 2
                elif line[j] == "'":
                    break
                else:
                    buf += line[j]
                    j += 1
            toks.append(buf)
            i = j + 1
        else:
            i += 1
    return toks


def test_row2_remote_line_round_trips_the_argv(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    monkeypatch.setenv("JUNKROAN_RUNS_EVENTS", str(tmp_path / "events.jsonl"))
    cfg = tmp_path / "hosts.json"
    cfg.write_text(json.dumps({"laptop": {"ssh_alias": "laptop", "repo_path": "C:\\x"}}), encoding="utf-8")
    monkeypatch.setenv("JUNKROAN_HOSTS_CONFIG", str(cfg))
    seen: list[str] = []

    class _R:
        returncode, stdout, stderr = 0, "j-fake\n", ""

    monkeypatch.setattr(runs_hosts, "run_on_host", lambda host_cfg, script: seen.append(script) or _R())
    local = tmp_path / "local.jsonl"
    rc = runs.main(["--store", str(local), "submit", "--issue", "1", "--host", "laptop", "--priority", "P1",
                    "--again", "--", *TRICKY])
    assert rc == 0 and len(seen) == 1
    # the laptop side: every token is a plain literal (no `"`, no empty string), so PowerShell 5.1
    # passes it to python unchanged, and the argv parses back to TRICKY
    tokens = _ps_tokens(seen[0].split("; ", 2)[2])
    print(tokens)
    assert all(t and '"' not in t for t in tokens)
    assert tokens[:3] == ["python", "scripts\\runs.py", "submit"]
    remote_store = tmp_path / "remote.jsonl"
    monkeypatch.setenv("JUNKROAN_HOST", "laptop")
    assert runs.main(["--store", str(remote_store), *tokens[2:]]) == 0
    jobs = Store(remote_store).jobs()
    assert len(jobs) == 1 and list(jobs[0].argv) == TRICKY
    assert not local.exists() or not Store(local).jobs()


@pc_only
def test_one_argument_after_the_dashes_stays_a_shell_line(tmp_path: Path, capsys, monkeypatch) -> None:
    """A whole shell line passed as one argument (`set X=... && python ...`, the form used before
    this fix) keeps running through the shell: no argv is stored for it."""
    monkeypatch.setenv("JUNKROAN_RUNS_EVENTS", str(tmp_path / "events.jsonl"))
    store_path = tmp_path / "jobs.jsonl"
    line = 'set "X203=one line" && python -c "import os; print(os.environ[\'X203\'])"'
    rc = runs.main(["--store", str(store_path), "submit", "--issue", "1", "--host", "pc", "--priority", "P1",
                    "--again", "--", line])
    assert rc == 0
    job = Store(store_path).get(capsys.readouterr().out.strip())
    assert job.argv is None and job.cmd == line
    assert _run(job.cmd, tmp_path) == "one line"
