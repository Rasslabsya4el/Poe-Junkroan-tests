"""#555: every exit of the improvement loop hands `_finish` a build whose socket colours the loop has judged, PoB-free.

#547 made the loop judge the colour step before pass 1 and after a lanes move, but a kept kick (`kick joint` re-rolls
gear), a kept gear or picks move cut off by the time budget, and a pass whose lanes move raised all end with sockets
or gems the loop never judged: `_finish` ran a fresh colour step over them and `config (final lanes)` stood above the
loop's last pass. Each test drives one exit on #547's fake (a socket of the gem's own colour is worth a bonus) and
counts the colour step.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from junkroan.optimizer.improvement_loop import LoopPlan
from junkroan.pob.host_runtime import PoBHeadlessHostContractError
from junkroan.search.sockets import gem_colour

from loop_fakes import _Loot, _Tree, _finish_pipeline, _finish_skeleton, loop_over
from test_issue547_loop_colours import BODY, GEMS, ColourPob

NEW_BODY = "Rarity: Rare\nDoom Shell\nFull Plate\nSockets: G-G-G-G G\nImplicits: 0"  # no socket of any gem's colour
BONUS = {"Added Fire Damage": 70.0, "Spell Echo": 50.0, "Added Cold Damage": 90.0}  # DPS when the gem sits in a socket of its colour


class GemPob(ColourPob):
    """#547's fake with a gem list a picks move can change; snapshots carry the gems too."""

    def __init__(self, value: float) -> None:
        super().__init__(value)
        self.gems = list(GEMS)
        self.gem_snapshots: dict[str, list] = {}

    def stats(self, keys):
        letters = self.sockets()
        bonus = sum(BONUS.get(g, 0.0) for i, g in enumerate(self.gems) if i < len(letters) and letters[i] == gem_colour(g))
        return {k: 0 for k in keys} | {"CombinedDPS": self.value + bonus, "Life": self.life}

    def export_xml(self) -> str:
        token = super().export_xml()
        self.gem_snapshots[token] = list(self.gems)
        return token

    def load_xml(self, token: str) -> None:
        super().load_xml(token)
        self.gems = list(self.gem_snapshots[token])

    def read_state(self) -> dict:
        return {"skills_state": {"socket_groups": [{"slot": "Body Armour", "gems": [{"gem_name": g, "enabled": True} for g in self.gems]}]}}


class RerollLoot(_Loot):
    """A slot re-roll that equips the item it returns (the real filler does) and may spend the loop's time."""

    def __init__(self, pob, script, clock=None) -> None:
        super().__init__(pob, script)
        self.clock = clock

    def fill_slot(self, slot, base, **kwargs):
        res = super().fill_slot(slot, base, **kwargs)
        if res.raw is not None:
            self.pob.equip({slot: res.raw})
        if self.clock is not None:
            self.clock[0] += 1000.0
        return res


def _drive(monkeypatch, *, script=None, kick=False, picks=False, lanes_raise=False, max_seconds=600.0, spend_time=False):
    """Run the improvement loop (max_passes=1) and `_finish` on the fake; return what the exit handed `_finish`."""

    import time as real_time

    pob = GemPob(1000.0)
    tree = _Tree(pob, [])
    p, _derived, logs = _finish_pipeline(monkeypatch, pob, tree, {})
    p._take_picks = lambda *_a, **_k: None
    p._tune_lanes = lambda _sk, *, identity=False: {}
    joint = None
    if lanes_raise:
        def tune(_sk, *, identity=False):
            if not identity:
                raise PoBHeadlessHostContractError("fake_failure", "the lanes move raised")
            return {}
        p._tune_lanes = tune

    clock = [0.0]
    if spend_time:  # a move that spends the budget: the next plan entry finds it gone
        monkeypatch.setattr("junkroan.optimizer.improvement_loop.time", SimpleNamespace(perf_counter=lambda: real_time.perf_counter() + clock[0]))
    loot = RerollLoot(pob, script or {}, clock if (spend_time and not picks) else None)

    if kick:
        draws: list[int] = []

        def joint_round(_sk, _loot, _tree, **_kwargs):
            draws.append(1)
            if len(draws) == 1:  # the first joint draw re-rolls the body armour into an uncoloured item and finds +16 %
                pob.value = 1300.0
                pob.raws["Body Armour"] = NEW_BODY
                _loot.current_raw["Body Armour"] = NEW_BODY
            return "ruined Body Armour"

        joint = joint_round

    sk = _finish_skeleton()
    sk.rare_bases = {"Body Armour": "Full Plate"}
    sk.main_link = ["Fireball", "Spell Echo"] if picks else ["Puncture"]  # one gem: the picks move is skipped

    class _Gen:
        def __init__(self, *_a, **_k) -> None:
            self.picks = ()

        def rejudge_picks(self, _skeleton, **_kwargs):
            pob.gems[1] = "Added Cold Damage"  # a swapped gem of another colour; the picks move keeps what the sweep kept
            pob.value += 200.0
            if spend_time:
                clock[0] += 1000.0
            return [{"text": "swapped Added Fire Damage for Added Cold Damage"}]

    monkeypatch.setattr("junkroan.search.generator.SkeletonGenerator", _Gen)

    steps = [0]
    import junkroan.optimizer.pipeline as pipeline_module
    real_step = pipeline_module.colour_step

    def counting_step(*args, **kwargs):
        steps[0] += 1
        return real_step(*args, **kwargs)

    monkeypatch.setattr(pipeline_module, "colour_step", counting_step)

    seen: dict = {}
    real_finish = p._finish

    def finish(*args, **kwargs):
        seen["stale"] = p._sockets_stale()
        seen["steps_before_finish"] = steps[0]
        return real_finish(*args, **kwargs)

    rig = loop_over(pob, tree=tree, gear=loot, skeleton=sk, objective=None, tune_lanes=p._tune_lanes, take_picks=p._take_picks, joint_round=joint,
                    judging=p.judging, log=p.log, rails=p.rails, socket_owner=p)  # the same judging context and colour memory `_finish` reads
    result = rig.started()
    outcome = rig.run(LoopPlan(seed=1, max_passes=1, max_seconds=max_seconds, min_gain=0.005, loot_n=5))
    loop_last = result.stages[-1].score_value
    finish(result, sk, 0.0)
    final = next(s for s in result.stages if s.name == "config (final lanes)")
    return SimpleNamespace(note=outcome.note, stale=seen["stale"], finish_steps=steps[0] - seen["steps_before_finish"], loop_last=loop_last, final=final.score_value, result=result)


def _assert_judged(run, stopped: str) -> None:
    assert stopped in run.note, run.note
    off = abs(run.final / run.loop_last - 1.0)
    assert not run.stale and run.finish_steps == 0 and off < 0.02, (
        f"stale at `_finish` start: {run.stale}; colour steps `_finish` ran: {run.finish_steps}; "
        f"loop's last pass {run.loop_last:,.0f} vs final lanes {run.final:,.0f} ({off:+.2%})")


def test_max_passes_right_after_a_kept_kick_that_re_rolled_the_gear(monkeypatch) -> None:
    run = _drive(monkeypatch, kick=True)

    assert any(m["move"] == "kick joint" and m["kept"] for m in run.result.moves)
    _assert_judged(run, "stopped: max passes")


@pytest.mark.parametrize("move", ["gear", "picks"])
def test_time_budget_right_after_a_kept_gear_or_picks_move(monkeypatch, move) -> None:
    if move == "gear":
        run = _drive(monkeypatch, script={"Body Armour": [(NEW_BODY, 1300.0)]}, spend_time=True)
        assert any(m["move"] == "gear Body Armour" and m["kept"] for m in run.result.moves)
    else:
        run = _drive(monkeypatch, picks=True, spend_time=True)
        assert any(m["move"] == "picks" and m["kept"] for m in run.result.moves)

    _assert_judged(run, "stopped: time budget")


def test_a_pass_whose_lanes_move_raises_still_ends_on_judged_colours(monkeypatch) -> None:
    run = _drive(monkeypatch, script={"Body Armour": [(NEW_BODY, 1300.0)]}, lanes_raise=True)

    assert run.result.dropped_moves and "lanes" in run.result.dropped_moves[0]["move"]
    _assert_judged(run, "stopped: max passes")


def test_the_replay_bench_row_and_table_carry_the_loops_exit() -> None:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import replay_bench

    row = {"ok": True, "reference": "bow_a", "source": "a.xml", "move": "loop", "value_before": 100.0, "value_after": 110.0, "gain_percent": 10.0,
           "seconds": 60.0, "kept": 2, "not_kept": 3, "judged_and_reverted": 1, "violation_before": 0.0, "violation_after": 0.0,
           "audit_errors": 0, "damage_kind": "attack", "loop_stop": "max passes"}
    loop_report = replay_bench.render_report([row, dict(row, reference="bow_b", loop_stop="time budget"), dict(row, reference="bow_c", loop_stop="converged")],
                                             stamp="x", move="loop", passes=3, workers=1, seconds=60.0)
    table = {ln.split("|")[1].strip(): ln for ln in loop_report.splitlines() if ln.startswith("| bow_")}
    assert "| loop exit |" in loop_report
    assert [table[k].split("|")[-2].strip() for k in ("bow_a", "bow_b", "bow_c")] == ["max passes", "time budget", "converged"]
    assert "loop exit" not in replay_bench.render_report([dict(row, move="refine", loop_stop=None)], stamp="x", move="refine", passes=1, workers=1, seconds=60.0)
    assert replay_bench.loop_exit_cell({}) == "-"
