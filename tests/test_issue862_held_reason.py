"""#862 rule 2: a follower of a failed predecessor shows `held: predecessor <job> failed`, never a slot reason."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import runs  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402


def _chain(tmp_path: Path, *, fail: bool):
    path = tmp_path / "jobs.jsonl"
    store = Store(path)
    first = store.submit(host="pc", priority="P2", tag="a", cmd="echo a")
    f1 = store.submit(host="pc", priority="P2", tag="b", cmd="echo b", after=[first.id])
    f2 = store.submit(host="pc", priority="P2", tag="c", cmd="echo c", after=[first.id])
    store.start(first.id)
    if fail:
        store.end(first.id, rc=2)
    return path, first, (f1, f2)


def _status(path: Path, capsys, *extra: str) -> str:
    assert runs.main(["--store", str(path), "status", *extra]) == 0
    return capsys.readouterr().out


def test_862_failed_predecessor_two_followers_held_reason(tmp_path: Path, capsys) -> None:
    path, first, followers = _chain(tmp_path, fail=True)
    want = f"held: predecessor {first.id} failed"

    text = _status(path, capsys)
    assert sum(f"{f.id} {want}" in text for f in followers) == 2
    assert not [ln for ln in text.splitlines() if any(f.id in ln for f in followers) and "slot" in ln.lower()]

    rows = {r["id"]: r for r in json.loads(_status(path, capsys, "--json"))}
    assert [rows[f.id]["reason"] for f in followers] == [want, want]
    assert all(rows[f.id]["state"] == "queued" for f in followers)
    assert all(not rows[f.id]["estimate"] for f in followers)
    assert sum("slot" in str(rows[f.id]["reason"]).lower() for f in followers) == 0


def test_862_follower_of_a_running_predecessor_is_unchanged(tmp_path: Path, capsys) -> None:
    path, first, followers = _chain(tmp_path, fail=False)
    text = _status(path, capsys)
    assert f"{followers[0].id} waiting: --after {first.id} (running)" in text
    assert "held: predecessor" not in text
    rows = {r["id"]: r for r in json.loads(_status(path, capsys, "--json"))}
    assert all(not rows[f.id]["reason"] and "estimate" not in rows[f.id] for f in followers)
