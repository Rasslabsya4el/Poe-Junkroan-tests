"""#1124 unit 6/6: the gate path of a red line, counted by the trace, PoB-free.

The one real day-1 path of a red line into a rare gear candidate is an incumbent weapon's crafted line (a red implicit):
`improvement_loop._weapon_base_move` reads it back as `extra_lines`, `craft_rare` prints it as an `unsupported_lines`
entry (the worker lists every explicit line PoB does not read, `headless_runtime_worker.py:1084`), and
`red_lines_blocking` decides at the call site whether the other base is still a candidate. This drives that call site
for real (not `forced`, which skips the path): the move, the gate, `TRACE.count_candidates` at the candidate and
`TRACE.count_trial` where the fake stands in for `PobSession.trial_stats` (`session.py:1039`). The counter is the
probe's own `probe-affix:` class (`scripts/probe_1124_marks.py`, row `affix_gate`), the one that reads 0 / 0 on the stands.

Marked line: generated > 0 and evaluated > 0. The same line with its mark removed (no record, a zero record, no marks
file): the candidate is dropped at the gate, generated = 0 and evaluated = 0.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import probe_1124_marks as probe  # noqa: E402

from junkroan.optimizer.objective import Objective  # noqa: E402
from junkroan.optimizer.red_line_marks import ENV_PATH  # noqa: E402
from junkroan.optimizer.trace import TRACE  # noqa: E402

import test_weapon_base_move as wbm  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "red_line_marks_fixture.json"
BOTH = "10% chance to Recover 10% of Mana when you use a Skill"  # marked on boss and optimistic
OPTIMISTIC_ONLY = "10% chance to create a Smoke Cloud on Kill"  # marked on the optimistic lane only
ZERO = "Can Allocate Passives from the Duelist's starting point"  # a record with both lanes empty
UNKNOWN = "Some Line With No Record At All"
CLASS = "probe-affix:"


class _RedPob(wbm._Pob):
    """The weapon-base move's fake PoB, with the incumbent carrying a crafted red line.

    `craft_rare` does what the worker does with `extra_lines`: the line goes into the raw and, being a line PoB does not
    read, into `unsupported_lines`. `trial_stats` counts each trial evaluated the way `PobSession.trial_stats` does."""

    def __init__(self, red_line: str) -> None:
        super().__init__()
        self.red_line = red_line

    def craft_rare(self, base, **kw):
        out = super().craft_rare(base, **kw)
        if not out["raw"]:
            return out
        lines = [ln for ln in kw.get("extra_lines") or () if ln.removeprefix("{crafted}") == self.red_line]
        return {**out, "raw": out["raw"] + "".join(f"{ln}\n" for ln in lines), "unsupported_lines": [ln.removeprefix("{crafted}") for ln in lines]}

    def trial_stats(self, trials, keys, mode="fast"):
        for trial in trials:
            TRACE.count_trial(trial)
        return super().trial_stats(trials, keys, mode)


@pytest.fixture(autouse=True)
def _marks(monkeypatch):
    monkeypatch.setenv(ENV_PATH, str(FIXTURE))


@pytest.fixture(autouse=True)
def _counter():
    TRACE.reset()
    fn = probe.register_item_classes(probe.ItemLines(affix={BOTH, OPTIMISTIC_ONLY, ZERO, UNKNOWN}))
    yield
    probe.unregister_item_classes(fn)
    TRACE.reset()


def _run(monkeypatch, red_line: str):
    """The weapon-base move over an incumbent whose crafted implicit is `red_line`; returns (kept, result, counters)."""

    pob = _RedPob(red_line)
    pipeline, pob, loot, skeleton, result = wbm._setup(monkeypatch, pob=pob)
    raw = wbm.RAW.replace("{crafted}Adds 1 to 2 Physical Damage", f"{{crafted}}{red_line}")
    pob.equipped["Weapon 1"] = loot.current_raw["Weapon 1"] = raw
    with TRACE.move("weapon base"):
        kept, _note = pipeline.weapon_base_move(
            result, skeleton, loot, "Weapon 1", current_score=Objective(maximize="CombinedDPS").score({"CombinedDPS": 100.0}),
            min_gain=0.005, move_state=wbm._state(pob, loot, skeleton), snapshot_fresh=True, t0=0.0,
            judge=wbm._judge(pipeline, pob, result, loot, skeleton),
            restore_move=lambda state, **kw: wbm._restore(pob, loot, skeleton, state, **kw), last_rejected={},
        )
    assert pob.crafts[0][6] == (f"{{crafted}}{red_line}",)  # the red line reached craft_rare as `extra_lines`
    return kept, result, probe.counter(TRACE.considered(), CLASS + red_line)


@pytest.mark.parametrize("line", [BOTH, OPTIMISTIC_ONLY])
def test_marked_red_line_on_the_incumbent_is_generated_and_evaluated(monkeypatch, line):
    kept, result, (generated, evaluated) = _run(monkeypatch, line)
    assert generated > 0 and evaluated > 0
    assert (generated, evaluated) == (1, 1)  # High Base; the Illegal Base is dropped by `problems`
    assert result.weapon_base_skipped == {"One Handed Sword": 1}
    assert kept  # the base the red line rode on was the winner


@pytest.mark.parametrize("line", [ZERO, UNKNOWN])
def test_unmarked_red_line_stays_blocked(monkeypatch, line):
    kept, result, (generated, evaluated) = _run(monkeypatch, line)
    assert (generated, evaluated) == (0, 0)
    assert result.weapon_base_skipped == {"One Handed Sword": 2}  # both other bases dropped at the gate
    assert not kept


def test_the_same_line_with_its_mark_removed_is_blocked(monkeypatch, tmp_path):
    kept, _result, counts = _run(monkeypatch, BOTH)
    assert counts == (1, 1) and kept
    TRACE.reset()
    monkeypatch.setenv(ENV_PATH, str(tmp_path / "missing.json"))  # no marks at all: every red line blocks again
    kept, result, counts = _run(monkeypatch, BOTH)
    assert counts == (0, 0) and not kept
    assert result.weapon_base_skipped == {"One Handed Sword": 2}
