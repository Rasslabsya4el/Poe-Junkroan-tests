"""Pipeline invariants that need no PoB: a stage recorded as "no change" must not move the
number, and the bandit is the rails' call, not the optimizer's."""

from types import SimpleNamespace

import pytest

from junkroan.optimizer.judging import write_lanes
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.pipeline import BuildPipeline, BuildResult
from junkroan.optimizer.rails import Rails

from judging_fakes import pob_judging


class _Pob:
    def __init__(self, values):
        self.values = list(values)

    def stats(self, keys):
        v = self.values.pop(0) if len(self.values) > 1 else self.values[0]
        return {k: 0 for k in keys} | {"CombinedDPS": v}


def _pipeline(values):
    p = BuildPipeline.__new__(BuildPipeline)
    p.pob = _Pob(values)
    p.log = lambda _m: None
    p.judging = pob_judging(p)
    p.objective = Objective(maximize="CombinedDPS")
    return p


def test_a_no_change_stage_that_moves_the_number_raises() -> None:
    p = _pipeline([1_000_000, 1_000_000, 66_000, 66_000])
    r = BuildResult(skeleton=SimpleNamespace(class_name="Witch", ascendancy="Necromancer", main_link=["Summon Raging Spirit"]))
    p._record(r, "loop pass 1", 0.0, "Boots +2.0%")
    with pytest.raises(RuntimeError, match="no change"):
        p._record(r, "loop pass 2", 0.0, "no change")


def test_a_no_change_stage_within_tolerance_passes() -> None:
    p = _pipeline([1_000_000, 1_000_000, 990_000, 990_000])
    r = BuildResult(skeleton=SimpleNamespace(class_name="Witch", ascendancy="Necromancer", main_link=["Summon Raging Spirit"]))
    p._record(r, "loop pass 1", 0.0, "Boots +2.0%")
    p._record(r, "loop pass 2", 0.0, "no change")
    assert [s.score_value for s in r.stages] == [1_000_000, 990_000]


class _IdentityPob(_Pob):
    """Enough PoB for the identity tuning: it answers stats and records every config write."""

    def __init__(self):
        super().__init__([1_000_000])
        self.applied: list[dict] = []

    def set_config(self, **kwargs):
        self.applied.append(kwargs)

    def mutate_nodes(self, **_kwargs):
        return {"points_used": 0}


class _ConfigPob(_Pob):
    """Enough PoB for `write_lanes`: it answers `config_inputs()` with whatever a fixture's own
    build carries and records every `set_config` call."""

    def __init__(self, inputs):
        super().__init__([0])
        self._inputs = dict(inputs)
        self.applied: list[dict] = []

    def config_inputs(self):
        return dict(self._inputs)

    def set_config(self, **kwargs):
        self.applied.append(kwargs)


def test_apply_config_drops_a_fixture_config_var_pob_does_not_know() -> None:
    """spec 2026-09-22 requirement 1: two Zizaran Explosive Arrow references carry the config var
    "enemyHit" in their own XML, a name PoB 2.67.2 does not know (`z325_champion_explosive_arrow`,
    `z329_champion_explosive_arrow` failed to load with `config_payload.config_sets[1].inputs
    references unknown PoB config var(s): enemyHit`). `write_lanes` preserves the build's own
    non-boolean config inputs verbatim (`preserved`); a name our config surfaces corpus does not
    carry must be dropped there, with one log line, before it ever reaches `set_config` -- never
    by weakening the worker's contract check."""

    logs: list[str] = []
    p = _pipeline([0])
    p.pob = _ConfigPob({"enemyHit": 5, "multiplierPoisonOnEnemy": 12, "enemyIsBoss": "Pinnacle", "usePowerCharges": True})
    p.log = logs.append
    p.judging = pob_judging(p, objective=p.objective)  # over the new session
    derived = SimpleNamespace(
        conservative=SimpleNamespace(inputs={}),
        optimistic=SimpleNamespace(inputs={}),
        ailment_stack_caps={},
        custom_mods=(),
    )
    skeleton = SimpleNamespace(bandit="None", pantheon_major="None", pantheon_minor="None", user_config={}, tuned_choices={})
    write_lanes(p.pob, skeleton, derived, log=p.log)
    assert "fixture config var dropped: enemyHit (unknown to PoB)" in logs
    applied = p.pob.applied[-1]
    assert "enemyHit" not in applied["inputs"] and "enemyHit" not in applied["conditional"]["inputs"]
    assert applied["inputs"]["multiplierPoisonOnEnemy"] == 12, "a var our corpus does know is kept"

    def mutate_nodes(self, **_kwargs):
        return {"points_used": 0}


def _identity_pipeline():
    p = _pipeline([1_000_000])
    p.pob = _IdentityPob()
    p.rails = Rails.load()
    p.judging = pob_judging(p, objective=p.objective)  # over the new session and rails
    return p


def test_the_bandit_is_a_rail_and_the_authors_choice_never_survives() -> None:
    """The user, 2026-09-18: every PoB kills all the bandits for the passive points. It was a
    judged choice and kinetic_fusillade s2 came back helping Alira."""

    assert Rails.load().bandit == "None"
    p = _identity_pipeline()
    skeleton = SimpleNamespace(bandit="Alira", pantheon_major="None", pantheon_minor="None", user_config={})
    p._rails_identity(skeleton)
    assert skeleton.bandit == "None"


def test_the_identity_tuning_judges_the_pantheons_and_not_the_bandit() -> None:
    p = _identity_pipeline()
    skeleton = SimpleNamespace(bandit="None", pantheon_major="None", pantheon_minor="None", user_config={}, level=77)
    derived = SimpleNamespace(conservative=SimpleNamespace(inputs={}), optimistic=SimpleNamespace(inputs={}))

    chosen = p._tune_identity(skeleton, derived)

    assert "bandit" not in chosen and set(chosen) == {"pantheon_major", "pantheon_minor"}
    assert p.pob.applied and all(call["bandit"] == "None" for call in p.pob.applied)
