"""The FullDPS shortcut in fast trial batches (speed audit 2026-09-18, off by default).

A fast trial that asks for FullDPS costs 2-4x one that does not: PoB rebuilds the whole
full-DPS roll-up (another env, another `calcs.perform`) per trial, for a number that in a
build we generate is one skill's own DPS times the gem's instance count. With
`PobSession.fulldps_shortcut` on, the ratio is measured once per batch with one real
roll-up and every trial reports `FullDPS = ratio x base`.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from junkroan.pob.session import PobSession, decode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")

KEYS = ("FullDPS", "Life")


class _FakeAdapter:
    """PoB replaced by arithmetic: the roll-up batch (FullDPS among the keys) answers the
    ratio probe, the batch without it answers per trial with a base that varies per trial."""

    def __init__(self, *, full: float = 2000.0, player_base: float = 1000.0, minion_base: float = 0.0, flagged: int = 1) -> None:
        self.payloads: list[dict[str, Any]] = []
        self.full, self.player_base, self.minion_base = full, player_base, minion_base
        self.flagged = flagged

    def read_state(self, handle: Any) -> dict[str, Any]:
        return {
            "skills_state": {
                "active_skill_set_id": "skills.main",
                "skill_sets": [
                    {
                        "skill_set_id": "skills.main",
                        "socket_groups": [{"enabled": True, "include_in_full_dps": i < self.flagged} for i in range(3)],
                    }
                ],
            }
        }

    def apply_skill_state(self, handle: Any, payload: dict[str, Any]) -> None:
        self.payloads.append({"apply_skill_state": True})

    def trial_stats(self, handle: Any, payload: dict[str, Any]) -> list[dict[str, Any]]:
        self.payloads.append(payload)
        if "FullDPS" in payload["keys"]:
            stats = {"FullDPS": self.full, "TotalDPS": self.player_base, "Minion.TotalDPS": self.minion_base}
            return [{"ok": True, "added_node_ids": [], "removed_node_ids": [], "stats": {k: v for k, v in stats.items() if v}}]
        return [
            {
                "ok": True,
                "added_node_ids": [],
                "removed_node_ids": list(trial["remove"]),
                "stats": {"TotalDPS": float(trial["remove"][0]), "Minion.TotalDPS": float(trial["remove"][0]) / 2.0, "Life": 4000.0},
            }
            for trial in payload["trials"]
        ]


def _session(adapter: _FakeAdapter, *, shortcut: bool) -> PobSession:
    pob = PobSession.__new__(PobSession)
    pob._adapter, pob._handle, pob._state_cache = adapter, object(), None
    pob.fulldps_shortcut = shortcut
    pob.fulldps_shortcut_batches = pob.fulldps_full_batches = pob.fulldps_shortcut_disabled = 0
    pob.fulldps_shortcut_unsafe = False
    pob._fulldps_last_ratio = None
    return pob


TRIALS = [{"remove": [10]}, {"remove": [20]}, {"remove": [30]}]


def test_the_ratio_is_measured_once_per_batch_and_applied_to_every_trial() -> None:
    adapter = _FakeAdapter(full=2000.0, player_base=1000.0)
    pob = _session(adapter, shortcut=True)

    results = pob.trial_stats(TRIALS, KEYS, mode="fast")

    assert len(adapter.payloads) == 2  # one roll-up for the ratio, one batch without it
    assert adapter.payloads[0]["keys"] == ["FullDPS", "TotalDPS", "Minion.TotalDPS"]
    assert adapter.payloads[0]["trials"] == [{"add": [], "remove": [], "mastery": {}, "item": None}]
    assert "FullDPS" not in adapter.payloads[1]["keys"] and "TotalDPS" in adapter.payloads[1]["keys"]
    assert len(adapter.payloads[1]["trials"]) == 3
    # ratio 2000/1000 = 2, base = the trial's own TotalDPS
    assert [r["stats"]["FullDPS"] for r in results] == [20.0, 40.0, 60.0]
    assert [r["stats"]["Life"] for r in results] == [4000.0] * 3
    assert "TotalDPS" not in results[0]["stats"]  # the base was not asked for, so it is not returned
    assert (pob.fulldps_shortcut_batches, pob.fulldps_full_batches) == (1, 0)

    pob.trial_stats(TRIALS, KEYS, mode="fast")  # every batch measures the ratio again
    assert len(adapter.payloads) == 4 and pob.fulldps_shortcut_batches == 2


def test_a_requested_base_stat_is_kept_and_a_minion_build_uses_the_minions_own_dps() -> None:
    adapter = _FakeAdapter(full=2000.0, player_base=1000.0)
    pob = _session(adapter, shortcut=True)
    results = pob.trial_stats(TRIALS, ("FullDPS", "TotalDPS"), mode="fast")
    assert results[0]["stats"]["TotalDPS"] == 10.0 and results[0]["stats"]["FullDPS"] == 20.0

    # a minion main skill: the player's own DPS is 0, PoB's FullDPS counts the minions
    adapter = _FakeAdapter(full=1000.0, player_base=0.0, minion_base=50.0)
    pob = _session(adapter, shortcut=True)
    results = pob.trial_stats(TRIALS, KEYS, mode="fast")
    assert adapter.payloads[1]["keys"] == ["Life", "Minion.TotalDPS"]
    assert [r["stats"]["FullDPS"] for r in results] == [100.0, 200.0, 300.0]  # 20 x the trial's minion DPS


def test_the_batch_runs_whole_when_the_flag_is_off_or_there_is_nothing_to_scale() -> None:
    adapter = _FakeAdapter()
    pob = _session(adapter, shortcut=False)
    pob.trial_stats(TRIALS, KEYS, mode="fast")
    assert len(adapter.payloads) == 1 and adapter.payloads[0]["keys"] == ["FullDPS", "Life"]
    assert (pob.fulldps_shortcut_batches, pob.fulldps_full_batches) == (0, 0)

    adapter = _FakeAdapter(full=0.0, player_base=1000.0)  # no socket group flagged: FullDPS is 0
    pob = _session(adapter, shortcut=True)
    pob.trial_stats(TRIALS, KEYS, mode="fast")
    assert len(adapter.payloads) == 2 and adapter.payloads[1]["keys"] == ["FullDPS", "Life"]
    assert (pob.fulldps_shortcut_batches, pob.fulldps_full_batches) == (0, 1)

    adapter = _FakeAdapter(full=2000.0, player_base=0.0, minion_base=0.0)  # no base to scale
    pob = _session(adapter, shortcut=True)
    pob.trial_stats(TRIALS, KEYS, mode="fast")
    assert adapter.payloads[1]["keys"] == ["FullDPS", "Life"] and pob.fulldps_full_batches == 1

    pob = _session(_FakeAdapter(), shortcut=True)  # full mode is never shortcut
    pob.trial_stats(TRIALS, KEYS, mode="full")
    assert pob.fulldps_shortcut_batches == 0


def test_a_build_flagging_several_groups_is_refused_up_front() -> None:
    """PoB's FullDPS then sums several skills and no single base tracks it (the authors' own
    absolution_minions is off by 56%): no probe is even run."""

    adapter = _FakeAdapter(flagged=2)
    pob = _session(adapter, shortcut=True)
    pob.trial_stats(TRIALS, KEYS, mode="fast")
    assert len(adapter.payloads) == 1 and adapter.payloads[0]["keys"] == ["FullDPS", "Life"]
    assert (pob.fulldps_shortcut_batches, pob.fulldps_full_batches) == (0, 1)
    assert pob.fulldps_shortcut_unsafe is False  # refused, not broken


def test_a_ratio_that_moves_between_batches_turns_the_shortcut_off_for_good() -> None:
    logged: list[str] = []
    adapter = _FakeAdapter(full=2000.0, player_base=1000.0)
    pob = _session(adapter, shortcut=True)
    pob.log = logged.append  # type: ignore[attr-defined]

    pob.trial_stats(TRIALS, KEYS, mode="fast")  # ratio 2.0
    adapter.full = 2020.0  # +1%: inside the band, the shortcut stands
    pob.trial_stats(TRIALS, KEYS, mode="fast")
    assert (pob.fulldps_shortcut_batches, pob.fulldps_shortcut_unsafe) == (2, False)

    adapter.full = 2500.0  # +24% against the remembered 2.02
    results = pob.trial_stats(TRIALS, KEYS, mode="fast")
    assert pob.fulldps_shortcut_unsafe is True and pob.fulldps_shortcut_disabled == 1
    assert len(logged) == 1 and "fulldps shortcut off" in logged[0] and "TotalDPS" in logged[0]
    assert adapter.payloads[-1]["keys"] == ["FullDPS", "Life"]  # that batch already ran whole
    assert results[0]["stats"]["FullDPS"] == 2500.0  # PoB's own number, not a scaled one

    before = len(adapter.payloads)
    pob.trial_stats(TRIALS, KEYS, mode="fast")  # every later batch runs whole, without a probe
    assert len(adapter.payloads) == before + 1 and pob.fulldps_full_batches == 2
    assert (pob.fulldps_shortcut_batches, pob.fulldps_shortcut_disabled) == (2, 1)


def test_a_new_skills_surface_forgets_the_previous_ratio() -> None:
    adapter = _FakeAdapter(full=2000.0, player_base=1000.0)
    pob = _session(adapter, shortcut=True)
    pob.trial_stats(TRIALS, KEYS, mode="fast")
    assert pob._fulldps_last_ratio == ("TotalDPS", 2.0)

    pob.set_skills(main_link=["Storm Brand"])  # the ratio is the skills surface's, and it changed
    assert pob._fulldps_last_ratio is None

    adapter.full = 4000.0  # a ratio of 4.0 against a forgotten 2.0 is not drift
    pob.trial_stats(TRIALS, KEYS, mode="fast")
    assert pob.fulldps_shortcut_unsafe is False and pob.fulldps_shortcut_batches == 2


@pytest.mark.pob
@needs_pob
@pytest.mark.parametrize("slug", ["stormbrand", "summon_raging_spirits"])
def test_the_shortcut_matches_pobs_own_fulldps_on_a_reference_build(slug: str, capsys: pytest.CaptureFixture[str]) -> None:
    """40 single-node removals on a reference: every trial's FullDPS within 0.5% of PoB's own,
    and the best candidate the same one."""

    with PobSession(run_id=f"test-fulldps-{slug}", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as pob:
        pob.load_xml(decode_import_code((FIXTURES / f"{slug}.pob.txt").read_text(encoding="utf-8").strip()))
        nodes = sorted(pob.tree_light()["user_allocated_node_ids"])[:40]
        trials = [{"remove": [node_id]} for node_id in nodes]

        pob.fulldps_shortcut = False
        t0 = time.perf_counter()
        exact = pob.trial_stats(trials, KEYS, mode="fast")
        exact_ms = (time.perf_counter() - t0) / len(trials) * 1000

        pob.fulldps_shortcut = True
        t0 = time.perf_counter()
        approx = pob.trial_stats(trials, KEYS, mode="fast")
        approx_ms = (time.perf_counter() - t0) / len(trials) * 1000

    assert pob.fulldps_shortcut_batches == 1 and pob.fulldps_full_batches == 0
    pairs = [(a["stats"]["FullDPS"], b["stats"]["FullDPS"]) for a, b in zip(exact, approx)]
    assert len(pairs) == len(trials) and all(x > 0 for x, _ in pairs)
    worst = max(abs(y - x) / x for x, y in pairs)
    assert worst <= 0.005, f"{slug}: FullDPS off by {worst:.4%}"
    assert max(range(len(pairs)), key=lambda i: pairs[i][0]) == max(range(len(pairs)), key=lambda i: pairs[i][1])
    with capsys.disabled():
        print(f"\n  {slug}: {exact_ms:.1f} ms/trial with PoB's roll-up, {approx_ms:.1f} ms/trial with the shortcut "
              f"(x{exact_ms / approx_ms:.2f}), worst FullDPS error {worst:.4%}")
