"""#927 unit 1: the collector's `parked_on_run` flag and the wider label/blocker cuts, on a fixture (no network)."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect  # noqa: E402

MARK = "<!-- parked-on-run: P2-core-12.10 -->\nsecond line"


def node(n, state="OPEN", labels=(), comments=(), assignees=0, blockers=()):
    return {"number": n, "title": f"t{n}", "state": state, "stateReason": None,
            "updatedAt": "2026-10-12T00:00:00Z", "createdAt": "2026-10-01T00:00:00Z",
            "author": {"login": "x"}, "labels": {"nodes": [{"name": l} for l in labels]},
            "parent": None,
            "blockedBy": {"nodes": [{"number": b, "state": "OPEN"} for b in blockers]},
            "comments": {"nodes": [{"body": c} for c in comments]},
            "assignees": {"totalCount": assignees}}


def run(monkeypatch, nodes):
    out = json.dumps({"data": {"repository": {"issues": {"nodes": nodes}}}})
    monkeypatch.setattr(collect.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout=out, stderr=""))
    return collect.tickets()["issues"]


def parked(issues):
    return sorted(int(k) for k, v in issues.items() if v["parked_on_run"])


def test_five_marked_open_are_parked_closed_is_not_listed(monkeypatch):
    nodes = [node(n, comments=["hello", MARK]) for n in (101, 102, 103, 104, 105)]
    nodes.append(node(106, state="CLOSED", comments=[MARK]))
    iss = run(monkeypatch, nodes)
    assert parked(iss) == [101, 102, 103, 104, 105]
    assert "106" not in iss


def test_no_marker_zero_parked(monkeypatch):
    iss = run(monkeypatch, [node(n, comments=["plain", "<!-- other: x -->"]) for n in (837, 888, 923, 12, 70)])
    assert parked(iss) == []


def test_marker_only_first_line_counts(monkeypatch):
    iss = run(monkeypatch, [node(1, comments=["text\n<!-- parked-on-run: x -->"])])
    assert parked(iss) == []


def test_ready_again_false(monkeypatch):
    assert parked(run(monkeypatch, [node(1, labels=["ready-for-agent"], comments=[MARK])])) == []


def test_needs_info_false(monkeypatch):
    assert parked(run(monkeypatch, [node(1, labels=["needs-info"], comments=[MARK])])) == []


def test_assigned_false(monkeypatch):
    assert parked(run(monkeypatch, [node(1, assignees=1, comments=[MARK])])) == []


def test_marker_beyond_last_30_comments_window_false(monkeypatch):
    # the query asks comments(last: 30); the 31st from the end is not returned, so the fixture holds 30 without it
    iss = run(monkeypatch, [node(1, comments=[f"c{i}" for i in range(30)])])
    assert parked(iss) == []
    assert "comments(last: 30)" in collect.QUERY_OPEN


def test_eleven_labels_and_eleven_blockers_kept(monkeypatch):
    labels = [f"l{i}" for i in range(10)] + ["needs-triage"]
    blockers = list(range(500, 511))
    iss = run(monkeypatch, [node(1, labels=labels, blockers=blockers)])
    assert "needs-triage" in iss["1"]["labels"] and len(iss["1"]["labels"]) == 11
    for query in (collect.QUERY_OPEN, collect.QUERY_CLOSED):
        assert "labels(first: 50)" in query and "blockedBy(first: 50)" in query


def test_eleventh_blocker_present(monkeypatch):
    nodes = [node(1, blockers=list(range(2, 13)))] + [node(n) for n in range(2, 13)]
    iss = run(monkeypatch, nodes)
    assert iss["1"]["blockers"] == list(range(2, 13)) and 12 in iss["1"]["blockers"]
