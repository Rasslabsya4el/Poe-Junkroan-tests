"""#1156 unit 1, fill-config-leak: a fill trial leaves no config behind in PoB (D113 kind B, a loop/evaluation fix).

The defect (measured on the contagion witch A1, 37,844 -> 47,258): `tune_given_choices` writes a candidate's own choice
(`bloodSandStance=SAND`) into PoB's config; the candidate is rejected, but `restore_choices` restores only the skeleton's
`tuned_choices`, and the next lane write carries every non-bool input still in PoB's config, so SAND rode on into a build with
no Flesh and Stone. The fix: the fill step holds the last written config plan and writes it back after every own-choice
candidate, with the build as it was before the trial gem.

Generator level: a fake PoB whose tune write sets a sticky stance. Judging level: `PobLanes` over a fake `set_config`.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from junkroan.optimizer.judging import Judging, PobLanes
from junkroan.optimizer.trace import TRACE
from junkroan.search.skeleton import SocketGroup

from judging_fakes import _Reads
from test_issue1156_fill import _gen, _skeleton


@pytest.fixture(autouse=True)
def _fresh_trace():
    TRACE.reset()
    yield
    TRACE.reset()


# -- generator level ---------------------------------------------------------------------------------------------

def _sticky_tune(pob):
    """The pipeline's callback in miniature: the lane write sets the stance in PoB's config and nothing takes it back."""

    def tune(sk, choices):
        for value in choices["bloodSandStance"]:
            pob.config["bloodSandStance"] = value
        return {"bloodSandStance": choices["bloodSandStance"][-1]}

    return tune


def test_a_rejected_own_choice_candidate_leaves_pobs_config_as_it_was(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("junkroan.search.generator.own_choices", lambda name: {"bloodSandStance": ["BLOOD", "SAND"]})
    skeleton = _skeleton()
    gen, pob = _gen(skeleton, ["Tiny"])
    pob.config = {"enemyLevel": 84}
    restored_with: list[list[str]] = []

    def hold_config():
        held = dict(pob.config)

        def restore() -> None:
            restored_with.append([g for grp in skeleton.extra_groups for g in grp.gems])
            pob.config.clear()
            pob.config.update(held)

        return restore

    added = gen.pick_fill(skeleton, tune=_sticky_tune(pob), hold_config=hold_config)

    assert added == []
    assert pob.config == {"enemyLevel": 84}, "SAND must not outlive the rejected trial"
    assert restored_with and all(gems == [] for gems in restored_with), "written back with the build as it was, without the trial gem"


def test_without_a_hold_the_fill_step_runs_as_before(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("junkroan.search.generator.own_choices", lambda name: {"bloodSandStance": ["BLOOD", "SAND"]})
    skeleton = _skeleton()
    gen, pob = _gen(skeleton, ["Tiny"])
    pob.config = {}

    assert gen.pick_fill(skeleton, tune=_sticky_tune(pob)) == []


# -- judging level -----------------------------------------------------------------------------------------------

class _ConfigPob:
    """`set_config` replaces the inputs and `config_inputs` reads them back, as PoB's config set does."""

    def __init__(self) -> None:
        self.inputs: dict = {}
        self.writes: list[dict] = []

    def config_inputs(self) -> dict:
        return dict(self.inputs)

    def set_config(self, **kwargs) -> None:
        self.inputs = dict(kwargs["inputs"])
        self.writes.append(dict(kwargs["inputs"]))


def _lanes(**inputs):
    lane = lambda: SimpleNamespace(inputs=dict(inputs), reasons={}, proof_lines={})  # noqa: E731
    return SimpleNamespace(conservative=lane(), optimistic=lane(), custom_mods=(), ailment_stack_caps={})


def _sk():
    return SimpleNamespace(bandit="None", pantheon_major="None", pantheon_minor="None", user_config={}, tuned_choices={})


def test_the_last_written_plan_is_written_back_over_a_later_one() -> None:
    pob = _ConfigPob()
    lanes = PobLanes(pob)
    assert lanes.written() is None, "nothing written yet: nothing to hold"
    sk = _sk()

    lanes.write(sk, _lanes(enemyLevel=84))
    held = lanes.written()
    lanes.write(sk, _lanes(enemyLevel=84, bloodSandStance="SAND"))
    assert pob.inputs["bloodSandStance"] == "SAND"

    lanes.rewrite(*held)

    assert pob.inputs == {"enemyLevel": 84}, "the trial's stance is gone, the held plan stands"


def test_hold_config_restores_the_plan_and_is_a_no_op_before_any_write() -> None:
    pob = _ConfigPob()
    judging = Judging(PobLanes(pob), _Reads([]))
    sk = _sk()
    judging.hold_config(sk)()  # nothing written: no set_config call
    assert pob.writes == []

    judging.lanes.write(sk, _lanes(enemyLevel=84))
    restore = judging.hold_config(sk)
    judging.lanes.write(sk, _lanes(enemyLevel=84, bloodSandStance="SAND"))
    restore()

    assert pob.inputs == {"enemyLevel": 84}
    assert len(pob.writes) == 3


# -- a candidate rejected only under the re-derived lanes (the winner's `honest` re-judge) -------------------------

from test_issue1156_fill import PRICE, _Pob  # noqa: E402

# what a full re-judge derives into the lane while the gem is in the build: a Link gem makes `linkedToMinion` shown, and
# PoB's own count is lower for it; an own-choice gem derives a var of its own. Both ride on in a sticky config.
LANE_OF = {"Protective Link": {"linkedToMinion": True}, "Sandy": {"derivedBad": True}}
PRE_TRIAL = {"enemyLevel": 84}


class _StickyPob(_Pob):
    """A config that is carried over by every write (`plan_config` keeps what PoB still holds), a full re-judge that writes
    carry-over + the lane derived from the build + the tuned choices, and a held plan that is written back exactly."""

    def __init__(self, skeleton) -> None:
        super().__init__(skeleton)
        self.config = dict(PRE_TRIAL)
        self.written = dict(PRE_TRIAL)

    def write(self, plan: dict) -> None:
        self.config, self.written = dict(plan), dict(plan)

    def rejudge(self, *_a, full: bool = False, **_k) -> None:
        if full:
            gems = [g for grp in self.skeleton.extra_groups for g in grp.gems]
            lane = {k: v for g in gems for k, v in LANE_OF.get(g, {}).items()}
            self.write({**self.config, **lane, **self.skeleton.tuned_choices})

    def stats(self, keys) -> dict:
        out = super().stats(keys)
        if self.config.get("linkedToMinion") or self.config.get("derivedBad"):
            out["CombinedDPS"] *= 0.5  # only the re-derived lane carries it, so only the `honest` re-judge sees the loss
        return out


def _sticky_run(monkeypatch: pytest.MonkeyPatch, name: str, *, own: bool):
    monkeypatch.setitem(PRICE, name, (0.0, 0.100, 0.0, 0.0))
    monkeypatch.setattr("junkroan.search.generator.own_choices",
                        lambda n: {"bloodSandStance": ["BLOOD", "SAND"]} if own else {})
    skeleton = _skeleton()
    gen, _ = _gen(skeleton, [name], reserving=())
    pob = _StickyPob(skeleton)
    gen.pob = pob
    gen._reconfigure = lambda callback, sk, *, full=False: pob.rejudge(full=full)

    def tune(sk, choices):
        pob.write({**pob.config, "bloodSandStance": "SAND"})
        sk.tuned_choices["bloodSandStance"] = "SAND"

    def hold_config():
        plan = dict(pob.written)
        return lambda: pob.write(plan)

    added = gen.pick_fill(skeleton, tune=tune if own else None, hold_config=hold_config)
    return added, pob, skeleton


def test_a_link_gem_rejected_under_the_rederived_lane_leaves_no_linkedToMinion(monkeypatch: pytest.MonkeyPatch) -> None:
    added, pob, skeleton = _sticky_run(monkeypatch, "Protective Link", own=False)

    assert added == [], "measured under the pre-trial lane it looked good; the re-derived lane (linkedToMinion shown) refuses it"
    assert pob.config == PRE_TRIAL
    assert skeleton.tuned_choices == {}


def test_an_own_choice_gem_rejected_under_the_rederived_lane_leaves_the_config_as_it_was(monkeypatch: pytest.MonkeyPatch) -> None:
    added, pob, skeleton = _sticky_run(monkeypatch, "Sandy", own=True)

    assert added == []
    assert pob.config == PRE_TRIAL, "neither the stance nor the derived var outlives the rejected winner"
    assert skeleton.tuned_choices == {}
