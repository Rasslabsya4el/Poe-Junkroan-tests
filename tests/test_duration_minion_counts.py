"""D57 rule 6, no PoB: a duration minion cannot be counted above what its caster keeps alive.
The count is casts per second x duration x minions per cast (PoB's own Speed and Duration),
never above the limit stat; every other minion stays at the limit (D49)."""

from junkroan.pob.skill_facts import is_duration_minion, minions_per_cast
from junkroan.search.skeleton import derived_counts

from conftest import needs_skill_source

pytestmark = needs_skill_source


class _Pob:
    """Answers whatever stat keys `derived_counts` asks for and records the asking."""

    def __init__(self, **values: float) -> None:
        self.values = values
        self.asked: list[tuple[str, ...]] = []

    def stats(self, keys):
        self.asked.append(tuple(keys))
        return {k: self.values[k] for k in keys if k in self.values}


def test_the_duration_minion_facts_come_from_pob_skill_data() -> None:
    assert is_duration_minion("SummonRagingSpirit"), "duration = true, base_skill_effect_duration 5000, 20 allowed"
    assert is_duration_minion("SummonSkeletons") and is_duration_minion("Absolution")
    assert not is_duration_minion("RaiseZombie"), "permanent minion: no duration flag, infinite_minion_duration"
    assert not is_duration_minion("RaiseSpectre"), "infinite_minion_duration"
    assert not is_duration_minion("Fireball") and not is_duration_minion("NoSuchSkill")

    assert minions_per_cast("SummonRagingSpirit") == 1, "no *_to_summon stat: one spirit a cast"
    assert minions_per_cast("SummonSkeletons") == 3, "number_of_melee_skeletons_to_summon, level 18 row"
    assert minions_per_cast("SummonSkeletonsAltX") == 3, "the same stat at another position in the list"
    assert minions_per_cast("Fireball") == 1 and minions_per_cast("NoSuchSkill") == 1


def test_a_duration_minion_is_capped_by_the_cast_rate_that_feeds_it() -> None:
    # the SRS reference: 2.8 casts/s x 8.2 s x 1 = 22 >= the limit of 20, so the limit stands
    pob = _Pob(ActiveRagingSpiritLimit=20, Speed=2.8, Duration=8.2)
    assert derived_counts(pob, ["Summon Raging Spirit"]) == {"Summon Raging Spirit": 20}
    assert "Speed" in pob.asked[0] and "Duration" in pob.asked[0]

    # a slower caster keeps fewer alive than the limit allows: 1.5 x 8.2 = 12
    assert derived_counts(_Pob(ActiveRagingSpiritLimit=20, Speed=1.5, Duration=8.2), ["Summon Raging Spirit"]) == {"Summon Raging Spirit": 12}
    # no duration (or no speed) from PoB: the limit, as before
    assert derived_counts(_Pob(ActiveRagingSpiritLimit=20, Speed=1.5), ["Summon Raging Spirit"]) == {"Summon Raging Spirit": 20}
    assert derived_counts(_Pob(ActiveRagingSpiritLimit=20, Speed=0, Duration=8.2), ["Summon Raging Spirit"]) == {"Summon Raging Spirit": 20}
    # never below one
    assert derived_counts(_Pob(ActiveRagingSpiritLimit=20, Speed=0.05, Duration=1.0), ["Summon Raging Spirit"]) == {"Summon Raging Spirit": 1}


def test_minions_per_cast_multiplies_what_the_caster_keeps_alive() -> None:
    # Summon Skeletons puts 3 down a cast: 0.2 x 5 x 3 = 3 of a limit of 10
    assert derived_counts(_Pob(ActiveSkeletonLimit=10, Speed=0.2, Duration=5.0), ["Summon Skeletons"]) == {"Summon Skeletons": 3}
    assert derived_counts(_Pob(ActiveSkeletonLimit=10, Speed=0.5, Duration=8.0), ["Summon Skeletons"]) == {"Summon Skeletons": 10}


def test_the_cap_is_the_main_skills_own_and_leaves_every_other_minion_alone() -> None:
    # Speed and Duration belong to the main skill: a duration minion in another group keeps the limit
    pob = _Pob(ActiveRagingSpiritLimit=20, Speed=1.5, Duration=8.2)
    counts = derived_counts(pob, ["Fireball", "Summon Raging Spirit"], links=[["Fireball"], ["Summon Raging Spirit"]])
    assert counts == {"Summon Raging Spirit": 20}
    assert all("Speed" not in keys and "Duration" not in keys for keys in pob.asked), "no main-link duration minion: no cast-rate question"

    # a permanent minion is never capped by the cast rate, main skill or not
    assert derived_counts(_Pob(ActiveZombieLimit=9, Speed=2.0, Duration=1.0), ["Raise Zombie"]) == {"Raise Zombie": 9}
