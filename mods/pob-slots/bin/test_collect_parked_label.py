"""#1075 unit 1: the collector's `parked` flag from the GitHub label `parked`, on a fixture (no network, no PoB)."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect  # noqa: E402


def node(n, state="OPEN", labels=(), parent=None):
    return {"number": n, "title": f"t{n}", "state": state, "stateReason": None,
            "updatedAt": "2026-10-12T00:00:00Z", "createdAt": "2026-10-01T00:00:00Z",
            "author": {"login": "x"}, "labels": {"nodes": [{"name": l} for l in labels]},
            "parent": {"number": parent} if parent else None,
            "blockedBy": {"nodes": []}, "comments": {"nodes": []}, "assignees": {"totalCount": 0}}


def run(monkeypatch, nodes):
    out = json.dumps({"data": {"repository": {"issues": {"nodes": nodes}}}})
    monkeypatch.setattr(collect.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout=out, stderr=""))
    return collect.tickets()["issues"]


def test_open_ticket_with_parked_label_is_parked_whatever_its_other_labels(monkeypatch):
    iss = run(monkeypatch, [node(101, labels=["parked", "enhancement", "ready-for-agent"])])
    assert iss["101"]["parked"] is True


def test_ticket_without_parked_label_is_not_parked(monkeypatch):
    iss = run(monkeypatch, [node(102, labels=["ready-for-agent", "enhancement"])])
    assert not iss["102"].get("parked", False)


def test_closed_ticket_with_parked_label_is_parked(monkeypatch):
    # a standalone closed ticket is not listed by tickets(); a closed sub-ticket of an open goal is
    iss = run(monkeypatch, [node(201), node(202, state="CLOSED", labels=["parked"], parent=201)])
    assert iss["202"]["state"] == "closed"
    assert iss["202"]["parked"] is True
