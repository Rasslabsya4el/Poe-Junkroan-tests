"""Manual active-skill affordability from fake PoB state and stats only."""

from __future__ import annotations

from types import SimpleNamespace

from junkroan.optimizer.gear_interface import GearInterface
from junkroan.optimizer.audit import audit_castability, audit_stats
from junkroan.optimizer.castability import CastabilityMetrics, LIFE_COST_STAT, MANA_COST_POOL_STAT, MANA_COST_STAT, castability_context, costed_skills, replace_castability_skill, with_castability_floors
from junkroan.optimizer.improvement_loop import LoopFlags, LoopPlan
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.pipeline import BuildPipeline, BuildResult

from judging_fakes import pob_judging
from loop_fakes import loop_over


class FakePob:
    def __init__(self) -> None:
        self._state = {
            "skills_state": {
                "socket_groups": [
                    {
                        "enabled": True,
                        "socket_group_id": "main",
                        "main_active_skill_index": 1,
                        "gems": [{"gem_entry_id": "trigger-support", "skill_id": "SupportTrigger"}],
                        "active_skill_entries": [
                            {"active_skill_id": "manual", "name": "Manual", "granted_effect_id": "manual", "triggered": False, "support_links": []},
                            {"active_skill_id": "life", "name": "Life Skill", "granted_effect_id": "life", "triggered": False, "support_links": []},
                            {"active_skill_id": "triggered", "name": "Triggered", "granted_effect_id": "triggered", "triggered": True, "support_links": []},
                            {"active_skill_id": "parent-with-trigger-link", "name": "Manual With Trigger Link", "granted_effect_id": "manual", "triggered": False,
                             "support_links": [{"skill_id": "SupportTrigger", "source_gem_entry_id": "trigger-support"}]},
                            {"active_skill_id": "support-trigger", "name": "Support Trigger", "granted_effect_id": "support-trigger", "triggered": False,
                             "trigger_label": "", "support_links": [{"skill_id": "TriggeredEffect", "source_gem_entry_id": "trigger-support"}]},
                            {"active_skill_id": "reservation", "name": "Reservation", "granted_effect_id": "reservation", "triggered": False, "support_links": []},
                            {"active_skill_id": "disabled", "name": "Disabled", "granted_effect_id": "disabled", "enabled": False, "triggered": False, "support_links": []},
                            # A `minion_id` marks the player's own SUMMON skill: the player casts it
                            # and pays for it (PoB's ManaCostWarningList names it). A minion's own
                            # attack never appears in the player's socket groups.
                            {"active_skill_id": "summon", "name": "Summon Lightning Golem", "granted_effect_id": "summon", "minion_id": "SummonedLightningGolem", "triggered": False, "support_links": []},
                            {"active_skill_id": "unknown", "name": "Unknown", "granted_effect_id": "unknown", "triggered": False, "support_links": []},
                        ],
                    }
                ]
            }
        }
        self.costs = {
            "manual": {"ManaCost": 30, "LifeCost": 0},
            "parent-with-trigger-link": {"ManaCost": 40, "LifeCost": 0},
            "life": {"ManaCost": 0, "LifeCost": 100},
            "triggered": {"ManaCost": 900, "LifeCost": 900},
            "support-trigger": {"ManaCost": 800, "LifeCost": 800},
            "reservation": {"ManaCost": 100, "LifeCost": 0, "ManaReservedPercent": 100},
            "disabled": {"ManaCost": 600, "LifeCost": 600},
            "summon": {"ManaCost": 52, "LifeCost": 0},
        }
        self.pools = {"Mana": 100, "ManaUnreserved": 29, "EnergyShield": 0, "EnergyShieldProtectsMana": 0, "Life": 200, "LifeUnreserved": 100}
        self.active_skill_calls: list[tuple[str, ...]] = []

    def read_state(self) -> dict:
        return self._state

    def active_skill_stats(self, ids, _keys) -> dict:
        self.active_skill_calls.append(tuple(ids))
        return {skill_id: self.costs[skill_id] for skill_id in ids if skill_id in self.costs}

    def stats(self, _keys) -> dict:
        return self.pools


def test_costed_skills_include_triggers_and_reservation_skills_with_a_cost(monkeypatch) -> None:
    monkeypatch.setattr("junkroan.pob.skill_facts.skill_types", lambda effect: {
        "manual": frozenset({"spell"}),
        "life": frozenset({"spell"}),
        "triggered": frozenset({"spell"}),
        "support-trigger": frozenset({"spell"}),
        "reservation": frozenset({"spell", "hasreservation"}),
        "disabled": frozenset({"spell"}),
        "summon": frozenset({"spell", "minion"}),
        "unknown": frozenset(),
    }[effect])
    skills = costed_skills(FakePob())

    assert [(skill.name, skill.mana_cost, skill.life_cost, skill.triggered) for skill in skills] == [
        ("Manual", 30.0, 0.0, False),
        ("Life Skill", 0.0, 100.0, False),
        ("Triggered", 900.0, 900.0, True),
        ("Manual With Trigger Link", 40.0, 0.0, False),
        ("Support Trigger", 800.0, 800.0, False),
        ("Reservation", 100.0, 0.0, False),
        ("Summon Lightning Golem", 52.0, 0.0, False),
    ]


def test_objective_uses_largest_costed_skill_and_life_matches_pob(monkeypatch) -> None:
    monkeypatch.setattr("junkroan.pob.skill_facts.skill_types", lambda _effect: frozenset({"spell"}))
    pob = FakePob()
    # Keep this test focused on the two manual entries.
    pob._state["skills_state"]["socket_groups"][0]["active_skill_entries"] = pob._state["skills_state"]["socket_groups"][0]["active_skill_entries"][:2]
    obj = with_castability_floors(pob, Objective(maximize="dps"))

    assert {stat.name for stat in obj.derived} >= {MANA_COST_POOL_STAT, MANA_COST_STAT, LIFE_COST_STAT}
    assert MANA_COST_STAT not in obj.stat_keys and LIFE_COST_STAT not in obj.stat_keys  # constants are injected before scoring, not fetched from PoB
    assert not obj.score({"dps": 1, "ManaUnreserved": 29, "EnergyShield": 0, "EnergyShieldProtectsMana": 0, "LifeUnreserved": 101, "Mana": 100, "Life": 200}).feasible
    assert obj.score({"dps": 1, "ManaUnreserved": 30, "EnergyShield": 0, "EnergyShieldProtectsMana": 0, "LifeUnreserved": 100, "Mana": 100, "Life": 200}).feasible


def test_mana_cost_pool_includes_energy_shield_only_when_pob_flag_is_on(monkeypatch) -> None:
    monkeypatch.setattr("junkroan.pob.skill_facts.skill_types", lambda _effect: frozenset({"spell"}))
    pob = FakePob()
    pob._state["skills_state"]["socket_groups"][0]["active_skill_entries"] = pob._state["skills_state"]["socket_groups"][0]["active_skill_entries"][:1]
    obj = with_castability_floors(pob, Objective(maximize="dps"))
    stats = {"dps": 1, "ManaUnreserved": 0, "EnergyShield": 52, "LifeUnreserved": 101, "Mana": 100, "Life": 200}

    assert obj.violations({**stats, "EnergyShieldProtectsMana": 1}) == {}
    assert obj.violations({**stats, "EnergyShieldProtectsMana": 0}) == {"ManaCostPool>=CostedManaCost": 1.0}


def test_a_costed_reservation_skill_uses_its_own_reservation_in_the_pool(monkeypatch) -> None:
    monkeypatch.setattr("junkroan.pob.skill_facts.skill_types", lambda _effect: frozenset({"hasreservation"}))
    pob = FakePob()
    pob._state["skills_state"]["socket_groups"][0]["active_skill_entries"] = pob._state["skills_state"]["socket_groups"][0]["active_skill_entries"][6:7]
    obj = with_castability_floors(pob, Objective(maximize="dps"))

    assert obj.violations({"dps": 1, "Mana": 100, "ManaUnreserved": 0, "EnergyShield": 0, "EnergyShieldProtectsMana": 0}) == {}


def test_audit_reports_the_exact_manual_skill_cost_errors(monkeypatch) -> None:
    monkeypatch.setattr("junkroan.pob.skill_facts.skill_types", lambda _effect: frozenset({"spell"}))
    pob = FakePob()
    pob._state["skills_state"]["socket_groups"][0]["active_skill_entries"] = pob._state["skills_state"]["socket_groups"][0]["active_skill_entries"][:2]

    findings = audit_castability(pob)

    assert [finding.detail for finding in findings] == [
        "Manual costs 30 mana, 29 unreserved",
        "Life Skill costs 100 life, 100 unreserved",
    ]


def test_a_summon_skill_the_player_cannot_afford_is_a_finding(monkeypatch) -> None:
    """PoB charges the player for its own summon skills and warns about them.

    Measured 2026-09-20 on the delivered builds: vd_spellslinger s1 carries
    three Summon Golems at 52 mana against 33 unreserved and winter_orb s1 one,
    and PoB's `ManaCostWarningList` names every one of them.
    """

    monkeypatch.setattr("junkroan.pob.skill_facts.skill_types", lambda _effect: frozenset({"spell", "minion"}))
    pob = FakePob()
    entries = pob._state["skills_state"]["socket_groups"][0]["active_skill_entries"]
    pob._state["skills_state"]["socket_groups"][0]["active_skill_entries"] = entries[7:8]
    pob.pools.update({"ManaUnreserved": 33, "LifeUnreserved": 1_000})

    assert [finding.detail for finding in audit_castability(pob)] == [
        "Summon Lightning Golem costs 52 mana, 33 unreserved",
    ]
    pob.pools["ManaUnreserved"] = 52  # PoB warns on `totalPool < cost`: equality is affordable
    assert audit_castability(pob) == []


def test_the_audit_names_the_live_main_skill_the_frozen_relations_leave_out(monkeypatch) -> None:
    monkeypatch.setattr("junkroan.pob.skill_facts.skill_types", lambda _effect: frozenset({"spell"}))
    pob = FakePob()
    pob._state["skills_state"]["socket_groups"][0]["active_skill_entries"] = pob._state["skills_state"]["socket_groups"][0]["active_skill_entries"][:2]
    pob._state["skills_state"]["main_socket_group_id"] = "main"

    frozen = castability_context(pob)
    audited = castability_context(pob, include_live=True)

    assert [skill.name for skill in frozen.skills] == ["Life Skill"]  # "Manual" is the live main skill
    assert [skill.name for skill in audited.skills] == ["Life Skill"]  # the frozen side is unchanged
    assert [skill.name for skill in audited.all_skills] == ["Manual", "Life Skill"]
    assert [finding.detail for finding in audit_castability(pob, skills=audited.all_skills)] == [
        "Manual costs 30 mana, 29 unreserved",
        "Life Skill costs 100 life, 100 unreserved",
    ]


def test_audit_uses_energy_shield_mana_pool_and_marks_triggered_skills(monkeypatch) -> None:
    monkeypatch.setattr("junkroan.pob.skill_facts.skill_types", lambda _effect: frozenset({"spell"}))
    pob = FakePob()
    pob._state["skills_state"]["socket_groups"][0]["active_skill_entries"] = pob._state["skills_state"]["socket_groups"][0]["active_skill_entries"][2:3]
    pob.pools.update({"ManaUnreserved": 0, "EnergyShield": 1_000, "EnergyShieldProtectsMana": 1, "LifeUnreserved": 1_000})

    assert audit_castability(pob) == []
    pob.pools["EnergyShield"] = 0
    assert [finding.detail for finding in audit_castability(pob)] == [
        "Triggered (triggered) costs 900 mana, 0 unreserved mana + 0 energy shield",
    ]


def test_one_refresh_context_is_shared_by_all_objectives_and_restored_without_a_read(monkeypatch) -> None:
    monkeypatch.setattr("junkroan.pob.skill_facts.skill_types", lambda _effect: frozenset({"spell"}))
    pob = FakePob()
    pob._state["skills_state"]["socket_groups"][0]["active_skill_entries"] = pob._state["skills_state"]["socket_groups"][0]["active_skill_entries"][:2]
    pipe = BuildPipeline.__new__(BuildPipeline)
    pipe.pob = pob
    pipe.castability_metrics = CastabilityMetrics()
    pipe.judging = pob_judging(pipe)
    pipe.objective = Objective(maximize="dps")
    pipe.judging.attach("tree_construction", SimpleNamespace(objective=Objective(maximize="dps")))
    pipe.judging.attach("tree", SimpleNamespace(objective=Objective(maximize="dps")))
    pipe.judging.attach("gear", SimpleNamespace(objective=Objective(maximize="dps")))

    pipe.judging.refresh_castability()
    frozen = pipe.judging.castability_context
    assert pob.active_skill_calls == [("manual", "life")]
    assert pipe.castability_metrics.calls == 1
    assert {d.context for d in pipe.objective.derived if d.name in {MANA_COST_STAT, LIFE_COST_STAT}} == {30.0, 100.0}
    assert {d.context for d in pipe.judging.trees()[0].objective.derived if d.name in {MANA_COST_STAT, LIFE_COST_STAT}} == {30.0, 100.0}
    assert {d.context for d in pipe.judging.view("gear").objective.derived if d.name in {MANA_COST_STAT, LIFE_COST_STAT}} == {30.0, 100.0}

    assert frozen is not None
    pipe.judging.refresh_castability(frozen)  # a move snapshot's frozen costs restored
    assert pob.active_skill_calls == [("manual", "life")]
    assert pipe.castability_metrics.calls == 1


def test_replacing_a_utility_skill_reads_only_that_skill(monkeypatch) -> None:
    monkeypatch.setattr("junkroan.pob.skill_facts.skill_types", lambda _effect: frozenset({"spell"}))
    pob = FakePob()
    entries = pob._state["skills_state"]["socket_groups"][0]["active_skill_entries"]
    pob._state["skills_state"]["socket_groups"][0]["active_skill_entries"] = [entries[0], entries[1]]
    metrics = CastabilityMetrics()
    baseline = castability_context(pob, metrics=metrics)
    pob._state["skills_state"]["socket_groups"][0]["active_skill_entries"] = [entries[0], entries[2]]

    candidate = replace_castability_skill(pob, baseline, remove=("life",), active_skill_id="triggered", metrics=metrics)

    assert pob.active_skill_calls == [("manual", "life"), ("triggered",)]
    assert metrics.calls == 2
    assert candidate.mana_cost == 900.0 and candidate.life_cost == 900.0


def test_replacing_the_live_main_skill_does_not_read_it_again(monkeypatch) -> None:
    monkeypatch.setattr("junkroan.pob.skill_facts.skill_types", lambda _effect: frozenset({"spell"}))
    pob = FakePob()
    entries = pob._state["skills_state"]["socket_groups"][0]["active_skill_entries"]
    pob._state["skills_state"]["main_socket_group_id"] = "main"
    pob._state["skills_state"]["socket_groups"][0]["active_skill_entries"] = [entries[0], entries[1]]
    metrics = CastabilityMetrics()
    baseline = castability_context(pob, metrics=metrics)
    assert baseline.live_active_skill_ids == frozenset({"manual"})
    pob._state["skills_state"]["socket_groups"][0]["active_skill_entries"] = [entries[2], entries[1]]

    candidate = replace_castability_skill(pob, baseline, remove=("manual",), active_skill_id="triggered", metrics=metrics)

    assert pob.active_skill_calls == [("life",)]
    assert candidate.mana_cost is None and candidate.life_cost == 100.0


def test_audit_marks_a_missed_mana_cost_pool_relation_as_an_error() -> None:
    objective = Objective(maximize="dps", relations=((MANA_COST_POOL_STAT, "ManaCost", 1.0, "Mana"),))

    findings = audit_stats({"dps": 1, MANA_COST_POOL_STAT: 10, "ManaCost": 20, "Mana": 100}, objective)

    assert [(finding.severity, finding.check) for finding in findings] == [("error", "relation")]


def test_loop_pass_reads_costs_at_its_start_and_after_each_kept_move_only(monkeypatch) -> None:
    """Three tree allocations, one gear move, and a reverted batch: the pass-start read, one read for each KEPT move (#941: a kept
    move is judged under the costs it left), none for the reverted batch, and the last pass's close on the final build."""

    monkeypatch.setattr("junkroan.pob.skill_facts.skill_types", lambda _effect: frozenset({"spell"}))

    class LoopPob(FakePob):
        def __init__(self) -> None:
            super().__init__()
            self._state["skills_state"]["socket_groups"][0]["active_skill_entries"] = self._state["skills_state"]["socket_groups"][0]["active_skill_entries"][:1]
            self.value = 100.0
            self._snapshots: dict[str, float] = {}
            self.loaded: list[str] = []

        def stats(self, keys) -> dict:
            return {key: 0.0 for key in keys} | self.pools | {"dps": self.value, "CombinedDPS": self.value, "Life": 200.0}

        def export_xml(self) -> str:
            token = f"snapshot-{len(self._snapshots)}"
            self._snapshots[token] = self.value
            return token

        def load_xml(self, token: str) -> None:
            self.loaded.append(token)
            self.value = self._snapshots[token]

        def equip(self, _items: dict) -> None:
            return None

    class Tree:
        restore_failures = 0

        def __init__(self, pob) -> None:
            self.pob = pob
            self.history: list = []
            self.objective = Objective(maximize="dps")  # the loop's move snapshot saves and restores it
            self.moves = 0

        def note_build_change(self) -> None:
            return None  # #34: the real TreeOptimizer drops its hooked-score cache here; the stub caches nothing

        def refine(self, *, max_rounds: int, repair_rounds: int = 60):
            if max_rounds == 10:
                self.moves += 3
                self.pob.value += 10.0

        def swap_subtrees(self, *, max_size: int, max_seconds: float, max_candidates=None):
            return None  # judged and reverted as a no-op

        def exchange_corridors(self, **_kwargs):
            return None  # plan B's trunk moves keep nothing here: the loop skips them without a judge

        def challenge_regions(self, **_kwargs):
            return None

    class Gear(GearInterface):
        def __init__(self, pob) -> None:
            self.pob = pob
            self.uniques, self.anoint, self.forced_lines = {}, None, {}
            self.current_raw = {"Boots": "incumbent"}
            self.objective = Objective(maximize="dps")  # the loop's move snapshot saves and restores it
            self.calls = 0

        def item_level_for(self, slot):
            return 86

        def other_weapon_bases(self, base):
            return []

        def fill_slot(self, *_args, **_kwargs):
            self.calls += 1
            self.pob.value += 10.0
            self.current_raw["Boots"] = "candidate"
            return SimpleNamespace(raw="candidate")

    pob = LoopPob()
    tree, gear = Tree(pob), Gear(pob)
    skeleton = SimpleNamespace(class_name="Witch", ascendancy="Elementalist", main_link=["Manual"], extra_groups=[], rare_bases={"Boots": "Boots"}, uniques={}, sockets={})
    pipe = loop_over(pob, tree=tree, gear=gear, skeleton=skeleton, objective=Objective(maximize="dps"), rails=SimpleNamespace())

    # the extra pass without its stage name is a combination no `LoopPlan` kind gives: the flags say it
    pipe.run(LoopPlan(seed=1, max_passes=1, max_seconds=60.0, min_gain=0.005, loot_n=1),
             flags=LoopFlags(local_only=True, opening_lanes=False, stage_name=None), result=BuildResult(skeleton=skeleton))

    assert tree.moves == 3 and gear.calls == 1 and pob.loaded
    # pass start 1, the kept refine 1, the kept gear move 1; the reverted swaps batch none; the close on the final build
    # (#941 (b)) reads 1 and, the fake's pool leaving its relation missed, 1 more after its repair round
    assert pob.active_skill_calls == [("manual",)] * 5
    assert pipe.castability_metrics.calls == 5
