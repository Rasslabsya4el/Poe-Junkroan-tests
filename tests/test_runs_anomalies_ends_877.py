"""#877 rules 1-2: a keymaster ends `done` after ONE ticket comment; old `done` ends are not re-queued after a
restart; `waiting` ends go before `done` ends in the one FIFO end worker. No PoB, no claude.exe."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from junkroan.runs import anomalies as an  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402
from test_runs_anomalies import FakeKeymasterCli, make_guard  # noqa: E402


def _failed_job(tmp_path: Path):
    store = Store(tmp_path / "jobs.jsonl")
    job = store.submit(host="pc", priority="P1", tag="t", cmd="python x.py", issue=865)
    out = tmp_path / "o.out"
    out.write_text("error: cannot fix\n", encoding="utf-8")
    store.start(job.id, out=str(out), pid=1)
    return store.end(job.id, rc=2, out=str(out))


def test_row2_prompt_makes_one_ticket_comment_mandatory_and_forbids_blocked(tmp_path: Path) -> None:
    anomaly = an.detect_job_failed(_failed_job(tmp_path))
    prompt = an.build_prompt(anomaly)
    assert "ONE comment on the job's ticket" in prompt
    assert "Never end `blocked`" in prompt and "`needs`" in prompt
    assert "end `done`" in prompt


def test_protocol_pages_say_the_same() -> None:
    root = Path(__file__).resolve().parents[1]
    for rel in ("docs/agents/keymaster.md", ".claude/agents/keymaster.md"):
        text = " ".join((root / rel).read_text(encoding="utf-8").split())
        assert "ONE comment on the job's ticket" in text and "never `blocked`" in text.lower()


def _done_rows(n: int) -> list[dict]:
    return [{"name": f"keymaster: job_failed j-{i}", "id": f"old-{i}", "state": "done"} for i in range(n)]


def test_restart_requeues_no_old_done_end(tmp_path: Path) -> None:
    guard, cli = make_guard(tmp_path)
    cli._sessions = _done_rows(5)
    guard.check()
    guard.drain_ends()
    assert len(cli.ended) == 5
    # a restart: a second guard over the same store sees the same (still listed) sessions
    cli2 = FakeKeymasterCli()
    cli2._sessions = _done_rows(5)
    guard2 = an.AnomalyGuard(path=tmp_path / "anomalies.json", launcher=cli2, log=lambda m: None,
                             probe_interval=0.0)
    guard2.check()
    guard2.drain_ends()
    assert cli2.ended == []


def test_waiting_end_goes_before_queued_done_ends(tmp_path: Path) -> None:
    guard, _ = make_guard(tmp_path)
    order: list[str] = []
    guard._end_thread = None
    with guard._end_cond:  # hold the worker off while queueing
        guard._end_queue.append(("done", "d1", {}, 0.0, lambda r: True))
        guard._end_queue.append(("done", "d2", {}, 0.0, lambda r: True))
    # queue directly, no thread yet: insert a waiting end and read the order
    guard._end_thread = type("T", (), {"is_alive": lambda self: True})()
    guard._enqueue_end("waiting", "w1", {}, 700.0, lambda r: True)
    order = [e[1] for e in guard._end_queue]
    assert order == ["w1", "d1", "d2"]


def test_row7_laptop_origin_session_name_is_a_keymaster_and_ends_done(tmp_path: Path) -> None:
    """The name `build_command` writes for a laptop job (`keymaster: job_stuck laptop j-...`, three words after
    the colon) must be recognised: it was not, so those sessions stayed idle for ever (read 2026-10-11 22:2x)."""
    anomaly = replace(an.detect_job_failed(_failed_job(tmp_path)), origin="laptop")
    name = an.build_command(anomaly)[an.build_command(anomaly).index("--name") + 1]
    assert name.count(" ") == 3  # keymaster: <kind> laptop <job>
    assert an._is_keymaster({"name": name})
    assert an._keymaster_live({"name": name, "state": "idle"})
    assert not an._keymaster_live({"name": name, "state": "done"})
    assert an._is_keymaster({"name": "keymaster: job_failed j-1"})
    assert not an._is_keymaster({"name": "orch Poe-Junkroan #1"})
