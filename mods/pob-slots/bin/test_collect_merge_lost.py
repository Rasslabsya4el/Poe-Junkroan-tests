"""#1089 unit 1: the collector's `merge_lost` flag on a fixture (no network, no clock, no PoB)."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect  # noqa: E402

NOW = datetime(2026, 10, 15, 16, 10, 0, tzinfo=timezone.utc)
OLD = "2026-10-15T15:33:30Z"      # 36.5 min before NOW: older than 30 min
YOUNG = "2026-10-15T15:50:00Z"    # 20 min before NOW: younger than 30 min
RESULT = "20261015T173312-merge-o1074e.json"
PARK = (r"<!-- parked-on-merge -->\nparked on merge "
        r"C:\Coding\poe-junkroan-v2\var\agentops\results\20261015T173312-merge-o1074e.json (ORCH ddbebc8b)")
PARK_NO_PATH = "<!-- parked-on-merge -->\nparked on merge, no path named"
DONE = "<!-- merge result -->\nlanded"
NOT_THERE = lambda f: False  # noqa: E731


def c(body, created):
    return {"body": body, "createdAt": created}


def test_lost_when_old_missing_and_not_live():
    assert collect._merge_lost([c(PARK, OLD)], NOW, NOT_THERE, set()) is True


def test_result_file_exists_not_lost():
    assert collect._merge_lost([c(PARK, OLD)], NOW, lambda f: f == RESULT, set()) is False


def test_younger_than_30_min_not_lost():
    assert collect._merge_lost([c(PARK, YOUNG)], NOW, NOT_THERE, set()) is False


def test_branch_still_waiting_or_running_not_lost():
    assert collect._merge_lost([c(PARK, OLD)], NOW, NOT_THERE, {"o1074e"}) is False


def test_merge_result_comment_after_not_lost():
    assert collect._merge_lost([c(PARK, OLD), c(DONE, YOUNG)], NOW, NOT_THERE, set()) is False


def test_marker_without_path_not_lost():
    assert collect._merge_lost([c(PARK_NO_PATH, OLD)], NOW, NOT_THERE, set()) is False


def test_no_marker_not_lost():
    assert collect._merge_lost([c("plain", OLD)], NOW, NOT_THERE, set()) is False


def test_newest_marker_decides_not_the_older_one():
    # a parked-on-merge older than a merge result: the result is the newest marker, so not lost
    assert collect._merge_lost([c(PARK, OLD), c(DONE, "2026-10-15T15:40:00Z")], NOW, NOT_THERE, set()) is False


# ---- through tickets(): the row key, the open check, the merge-status fallback


def node(n, state="OPEN", comments=()):
    return {"number": n, "title": f"t{n}", "state": state, "stateReason": None,
            "updatedAt": "2026-10-15T00:00:00Z", "createdAt": "2026-10-01T00:00:00Z",
            "author": {"login": "x"}, "labels": {"nodes": []}, "parent": None,
            "blockedBy": {"nodes": []},
            "comments": {"nodes": [{"body": b, "createdAt": t} for b, t in comments]},
            "assignees": {"totalCount": 0}}


def fake_subprocess(nodes, merge_json=None):
    gql = json.dumps({"data": {"repository": {"issues": {"nodes": nodes}}}})
    ms = json.dumps(merge_json or {"at": "2026-10-15T16:10:00+00:00", "running": None, "waiting": [], "landed": []})

    def run(cmd, *a, **k):
        out = gql if "graphql" in cmd else ms
        return SimpleNamespace(returncode=0, stdout=out, stderr="")
    return run


# tickets() reads the real clock and the real results folder: its fixtures use a parked-on-merge comment far older
# than 30 min that names a file which cannot exist (the real o1074e result file does exist since 17:56 local)
ANCIENT = "2020-01-01T00:00:00Z"
PARK_ABSENT = PARK.replace("20261015T173312-merge-o1074e.json", "20991231T235959-merge-zz9.json")


def test_tickets_row_carries_merge_lost_true_for_open_lost(monkeypatch):
    monkeypatch.setattr(collect.subprocess, "run", fake_subprocess([node(101, comments=[(PARK_ABSENT, ANCIENT)])]))
    iss = collect.tickets()["issues"]
    assert iss["101"]["merge_lost"] is True


def test_tickets_every_row_has_merge_lost_key_default_false(monkeypatch):
    monkeypatch.setattr(collect.subprocess, "run", fake_subprocess([node(101, comments=[("plain", ANCIENT)])]))
    iss = collect.tickets()["issues"]
    assert iss["101"]["merge_lost"] is False


def test_closed_ticket_never_flagged(monkeypatch):
    monkeypatch.setattr(collect.subprocess, "run",
                        fake_subprocess([node(106, state="CLOSED", comments=[(PARK_ABSENT, ANCIENT)])]))
    iss = collect.tickets()["issues"]
    assert "106" not in iss or iss["106"]["merge_lost"] is False


def test_merge_status_exception_no_flag_no_raise(monkeypatch):
    def boom():
        raise RuntimeError("merge-status down")
    monkeypatch.setattr(collect, "merge_status", boom)
    monkeypatch.setattr(collect.subprocess, "run", fake_subprocess([node(101, comments=[(PARK_ABSENT, ANCIENT)])]))
    iss = collect.tickets()["issues"]
    assert iss["101"]["merge_lost"] is False
