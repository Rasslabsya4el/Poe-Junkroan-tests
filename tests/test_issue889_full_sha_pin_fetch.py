"""#889: a FULL 40-hex pin absent from the object store is fetched, not mistaken for present (PoB-free)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import run_queue  # noqa: E402
from junkroan.runs import pin_ref  # noqa: E402
from test_issue756_pin_travels import g, point_queue_at, world  # noqa: E402
from timing_bound import bound  # noqa: E402


def test_full_sha_pin_travels(tmp_path, monkeypatch):
    monkeypatch.setattr(pin_ref, "TIMEOUT", bound(pin_ref.TIMEOUT, 1500.0))
    origin, pc, laptop, pin = world(tmp_path)
    assert len(pin) == 40
    ok, _ = pin_ref.push_pin(pc, pin)
    assert ok
    point_queue_at(monkeypatch, laptop, tmp_path)
    made = run_queue.make_snapshot("job-full", pin)
    assert made is not None, run_queue.LAST_SNAPSHOT_FAILURE
    assert g(made[0], "rev-parse", "HEAD") == pin


def test_short_pin_travels(tmp_path, monkeypatch):
    monkeypatch.setattr(pin_ref, "TIMEOUT", bound(pin_ref.TIMEOUT, 1500.0))
    origin, pc, laptop, pin = world(tmp_path)
    assert pin_ref.push_pin(pc, pin)[0]
    point_queue_at(monkeypatch, laptop, tmp_path)
    made = run_queue.make_snapshot("job-short", pin[:7])
    assert made is not None
    assert g(made[0], "rev-parse", "HEAD") == pin


def test_present_pin_needs_no_fetch(tmp_path, monkeypatch):
    origin, pc, laptop, pin = world(tmp_path)
    main_sha = g(laptop, "rev-parse", "HEAD")
    point_queue_at(monkeypatch, laptop, tmp_path)

    def boom(*a, **k):
        raise AssertionError("fetch_pin called for a pin that is present")

    monkeypatch.setattr(pin_ref, "fetch_pin", boom)
    made = run_queue.make_snapshot("job-present", main_sha)
    assert made is not None
    assert g(made[0], "rev-parse", "HEAD") == main_sha


def test_full_sha_nowhere_fails_with_message(tmp_path, monkeypatch):
    monkeypatch.setattr(pin_ref, "TIMEOUT", bound(pin_ref.TIMEOUT, 1500.0))
    origin, pc, laptop, pin = world(tmp_path)      # nothing pushed
    point_queue_at(monkeypatch, laptop, tmp_path)
    assert run_queue.make_snapshot("job-none", pin) is None
    assert run_queue.LAST_SNAPSHOT_FAILURE == f"pin {pin} is not on this host"
