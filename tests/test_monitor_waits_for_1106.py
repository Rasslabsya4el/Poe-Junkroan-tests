"""#1106: a queued job whose `--after` predecessor still runs or waits reads «ждёт <that tag>» in the monitor.

`addon.runs()` gets a `waits_for = {"tag": ...}` on every queued row whose predecessor (the first one in `after` order
that is queued or running) has not ended; a `held_by` (failed predecessor, #863) wins and no `waits_for` is set. The
field does not depend on the host the job was submitted to (a laptop row reads the same). Fixture: a store file in a
tmp folder; no PoB, no ssh, no daemon.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "mods" / "pob-slots"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(MOD / "bin"))

import collect  # noqa: E402,F401  (the add-on imports its helpers from the generic collector)
from junkroan.pob import slot_budget  # noqa: E402
from junkroan.runs import store as store_mod  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402

_spec = importlib.util.spec_from_file_location("monitor_addon_1106", MOD / "addon" / "addon.py")
addon = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(addon)


@pytest.fixture
def store(tmp_path, monkeypatch) -> Store:
    """A job log in tmp_path; the add-on reads it through `store.DEFAULT_LOG`, the slots and the daemon are empty."""
    log = tmp_path / "jobs.jsonl"
    monkeypatch.setattr(store_mod, "DEFAULT_LOG", log)
    monkeypatch.setattr(addon, "EST_CACHE", tmp_path / "estimates.json")
    monkeypatch.setattr(addon, "estimate", lambda *a, **k: (None, None))
    monkeypatch.setattr(addon, "daemon_waits", lambda host: {})
    monkeypatch.setattr(slot_budget, "load_budget",
                        lambda *a, **k: SimpleNamespace(period="day", total=5, others=0, limit_for=lambda role: 5))
    monkeypatch.setattr(slot_budget, "busy_slots", lambda *a, **k: [])
    monkeypatch.setattr(slot_budget, "waiting", lambda *a, **k: [])
    monkeypatch.setattr(slot_budget, "slot_dir", lambda *a, **k: tmp_path / "slots")
    monkeypatch.setattr(slot_budget, "current_host", lambda *a, **k: "pc")
    return Store(log)


def _four(store: Store, host: str):
    """A running P2-core (A); B queued --after A; C queued --after A B; D queued with no `after`."""
    a = store.submit(host=host, priority="P2", tag="P2-core", cmd="echo a")
    store.start(a.id)
    b = store.submit(host=host, priority="P1", tag="P1-#406", cmd="echo b", after=[a.id])
    c = store.submit(host=host, priority="P1", tag="P1-#406-2", cmd="echo c", after=[a.id, b.id])
    d = store.submit(host=host, priority="P2", tag="P2-free", cmd="echo d")
    return a, b, c, d


def _queued(out: dict) -> dict:
    return {q["tag"]: q for q in out["queued"]}


@pytest.mark.parametrize("host", ["pc", "laptop"])
def test_queued_job_behind_a_running_predecessor_names_its_tag(store: Store, host: str) -> None:
    a, b, c, d = _four(store, host)
    rows = _queued(addon.runs(history=False))
    assert rows["P1-#406"]["waits_for"] == {"tag": "P2-core"}           # row 1
    assert rows["P1-#406-2"]["waits_for"] == {"tag": "P2-core"}         # row 2, A first in `after` order
    assert "waits_for" not in rows["P2-free"]                           # row 3: no predecessor, slot-only wait
    assert "j-" not in rows["P1-#406"]["waits_for"]["tag"]              # a tag, never a job id
    print({t: q.get("waits_for") for t, q in rows.items()})


@pytest.mark.parametrize("host", ["pc", "laptop"])
def test_next_predecessor_is_named_once_the_first_one_ended_rc0(store: Store, host: str) -> None:
    a, b, c, d = _four(store, host)
    store.end(a.id, rc=0)                                               # A done: C now waits for B
    rows = _queued(addon.runs(history=False))
    assert rows["P1-#406-2"]["waits_for"] == {"tag": "P1-#406"}         # row 2, second step
    assert "waits_for" not in rows["P1-#406"]                           # B's only predecessor is done
    print({t: q.get("waits_for") for t, q in rows.items()})


def test_failed_predecessor_keeps_held_by_and_gets_no_waits_for(store: Store) -> None:
    a, b, c, d = _four(store, "pc")
    store.end(a.id, rc=3)                                               # A failed: #863's hold, not a wait
    rows = _queued(addon.runs(history=False))
    assert rows["P1-#406"]["held_by"] == {"id": a.id, "tag": "P2-core"}
    assert "waits_for" not in rows["P1-#406"]
    assert rows["P1-#406-2"]["held_by"] == {"id": a.id, "tag": "P2-core"}
    assert "waits_for" not in rows["P1-#406-2"]
