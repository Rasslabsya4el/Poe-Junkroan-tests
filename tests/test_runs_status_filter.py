"""`runs.py status` table window: live jobs plus those ended in the last 24 h; `--all`; `--state` (#1070).

A store of 5 jobs written as raw JSONL with explicit timestamps relative to the real clock:
2 done 3 days ago, 1 done 1 h ago, 1 running, 1 queued. No PoB, no sleeping.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import runs  # noqa: E402

NOW = datetime.now(timezone.utc)


def _ts(delta: timedelta) -> str:
    return (NOW - delta).isoformat(timespec="microseconds")


def _submit(job: str, tag: str, at: timedelta) -> dict:
    return {"ts": _ts(at), "job": job, "op": "submit", "host": "pc", "priority": "P1", "issue": None,
            "submitter": "", "tag": tag, "pin": None, "cmd": "echo hi", "resumable": False,
            "workers": 1, "after": [], "class": "run"}


def _write_store(path: Path) -> None:
    recs = [
        # done 3 days ago
        _submit("j-old-1", "old1", timedelta(days=3, hours=1)),
        {"ts": _ts(timedelta(days=3)), "job": "j-old-1", "op": "start"},
        {"ts": _ts(timedelta(days=3, minutes=-30)), "job": "j-old-1", "op": "end", "rc": 0},
        _submit("j-old-2", "old2", timedelta(days=3, hours=2)),
        {"ts": _ts(timedelta(days=3, hours=1)), "job": "j-old-2", "op": "start"},
        {"ts": _ts(timedelta(days=3, minutes=-10)), "job": "j-old-2", "op": "end", "rc": 0},
        # done 1 h ago
        _submit("j-new-1", "new1", timedelta(hours=2)),
        {"ts": _ts(timedelta(hours=1, minutes=30)), "job": "j-new-1", "op": "start"},
        {"ts": _ts(timedelta(hours=1)), "job": "j-new-1", "op": "end", "rc": 0},
        # running
        _submit("j-run-1", "run1", timedelta(minutes=20)),
        {"ts": _ts(timedelta(minutes=10)), "job": "j-run-1", "op": "start"},
        # queued
        _submit("j-que-1", "que1", timedelta(minutes=5)),
    ]
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in recs), encoding="utf-8")


def _status(tmp_path: Path, capsys, monkeypatch, *extra: str) -> tuple[int, list[str], list[str]]:
    monkeypatch.setattr(runs, "collect_local", lambda store: [])
    monkeypatch.setattr(runs, "_slot_lines", lambda *a, **k: [])
    store_path = tmp_path / "jobs.jsonl"
    if not store_path.exists():
        _write_store(store_path)
    rc = runs.main(["--store", str(store_path), "status", *extra])
    out = capsys.readouterr().out.splitlines()
    # a table row: job id, then its host; the `held:` gate lines start with a job id too, so not those
    job_rows = [l for l in out if l.startswith("j-") and l.split()[1] in ("pc", "laptop", "any")]
    return rc, job_rows, out


def _ids(rows: list[str]) -> list[str]:
    return [r.split()[0] for r in rows]


def test_default_shows_live_and_last_24_h_and_names_the_hidden_two(tmp_path, capsys, monkeypatch) -> None:
    rc, rows, out = _status(tmp_path, capsys, monkeypatch)
    assert rc == 0
    assert sorted(_ids(rows)) == ["j-new-1", "j-que-1", "j-run-1"]
    assert "2 older jobs hidden (--all)" in out


def test_all_shows_every_job_and_no_hidden_line(tmp_path, capsys, monkeypatch) -> None:
    rc, rows, out = _status(tmp_path, capsys, monkeypatch, "--all")
    assert rc == 0
    assert len(rows) == 5
    assert not any("hidden" in l for l in out)


def test_state_done_prints_that_state_whatever_its_age(tmp_path, capsys, monkeypatch) -> None:
    rc, rows, out = _status(tmp_path, capsys, monkeypatch, "--state", "done")
    assert rc == 0
    assert len(rows) == 3
    assert sorted(_ids(rows)) == ["j-new-1", "j-old-1", "j-old-2"]
    assert not any("hidden" in l for l in out)


def test_json_keeps_printing_every_job(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(runs, "collect_local", lambda store: [])
    store_path = tmp_path / "jobs.jsonl"
    _write_store(store_path)
    rc = runs.main(["--store", str(store_path), "status", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 5
