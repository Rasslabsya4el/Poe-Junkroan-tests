"""#1156 unit 1: the fill step. PoB-free (fakes), D113 kind A: rail tests plus the trace counter at the PoB boundary.

The owner's word (2026-10-16): every socket filled with something PoB counts, free mana into auras. After
`pick_utilities` and the movement pair, a fill step measures every gem PoB counts as an aura, a guard, a herald or a
buff (retrieved from the corpus and PoB's skill types, never listed), each with its own config choices tried (Flesh and
Stone under Blood and Sand stance), and keeps it when TotalEHP or the objective rises >= 0.5 % while the objective does
not fall by more than 0.1 % and no floor is missed. It is not capped by `utilities.max_groups`.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from junkroan.optimizer.castability import CastabilityMetrics
from junkroan.optimizer.config_rules import DerivedConfig, LaneConfig
from junkroan.optimizer.judging import tune_given_choices
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.trace import TRACE
from junkroan.optimizer.trace_output import trace_output_from_xml
from junkroan.pob.skill_facts import SKILL_DATA_DIRS
from junkroan.search.generator import SkeletonGenerator, own_choices
from junkroan.search.skeleton import Skeleton, SocketGroup

needs_skill_data = pytest.mark.skipif(not any(d.is_dir() for d in SKILL_DATA_DIRS), reason="PoB skill data is not checked out")

# the fake PoB's price of each gem: (CombinedDPS share added, TotalEHP share added, ManaUnreserved taken, Life taken)
PRICE = {
    "Haste": (0.060, 0.0, 100.0, 0.0),
    "Determination": (0.0, 0.100, 150.0, 0.0),
    "Tiny": (0.0, 0.004, 0.0, 0.0),            # +0.4 % EHP: below the 0.5 % bar
    "Costly": (-0.002, 0.020, 0.0, 0.0),        # EHP up but the objective falls 0.2 %: more than the 0.1 % allowed
    "Barely": (-0.0009, 0.020, 0.0, 0.0),       # the objective falls 0.09 %: allowed
    "Fragile": (0.100, 0.100, 0.0, 60.0),       # misses the Life floor
    "Heavy Aura": (0.0, 0.100, 400.0, 0.0),
    "Tempest Shield": (0.0, 0.030, 0.0, 0.0),
    "Flesh and Stone": (0.0, 0.0, 120.0, 0.0),  # the EHP is in the stance below
    "Blood Aura": (0.0, 0.050, 0.0, 0.0),       # reserves Life (LIFE_RESERVED below), no Mana
    "Blood Aura 2": (0.0, 0.040, 0.0, 0.0),
}
LIFE_RESERVED = {"Blood Aura": 100.0, "Blood Aura 2": 50.0}
STANCE_EHP = {"BLOOD": 0.0, "SAND": 0.080}


@pytest.fixture(autouse=True)
def _fresh_trace():
    TRACE.reset()
    yield
    TRACE.reset()


class _Pob:
    """The PoB boundary: stats read the enabled extra groups, the stance written last, and record both."""

    def __init__(self, skeleton: Skeleton) -> None:
        self.skeleton = skeleton
        self.stance = "BLOOD"
        self.stances_seen: set[str] = set()
        self.calls = 0

    def stats(self, keys) -> dict:
        self.calls += 1
        gems = [g for grp in self.skeleton.extra_groups if grp.enabled for g in grp.gems]
        dps = sum(PRICE.get(g, (0, 0, 0, 0))[0] for g in gems)
        ehp = sum(PRICE.get(g, (0, 0, 0, 0))[1] for g in gems) + (STANCE_EHP[self.stance] if "Flesh and Stone" in gems else 0.0)
        if "Flesh and Stone" in gems:
            self.stances_seen.add(self.stance)
        return {key: 0.0 for key in keys} | {
            "CombinedDPS": 1000.0 * (1 + dps), "TotalEHP": 10000.0 * (1 + ehp),
            "ManaUnreserved": 500.0 - sum(PRICE.get(g, (0, 0, 0, 0))[2] for g in gems),
            "LifeUnreserved": 100.0 - sum(LIFE_RESERVED.get(g, 0.0) for g in gems),
            "Life": 100.0 - sum(PRICE.get(g, (0, 0, 0, 0))[3] for g in gems),
        }


def _skeleton(*carried: str) -> Skeleton:
    return Skeleton(class_name="Marauder", ascendancy="Juggernaut", main_link=["Cleave"],
                    extra_groups=[SocketGroup(gems=[name], slot="Helmet", label=name) for name in carried])


def _gen(skeleton: Skeleton, candidates: list[str], *, capacity: dict[str, int] | None = None, max_groups: int = 4,
         reserving: tuple[str, ...] = ("Haste", "Determination", "Flesh and Stone"), life_reserving: tuple[str, ...] = (),
         sockets: dict[str, list[str]] | None = None) -> tuple[SkeletonGenerator, _Pob]:
    pob = _Pob(skeleton)
    gen = SkeletonGenerator.__new__(SkeletonGenerator)
    gen.pob = pob
    gen.rails = SimpleNamespace(gems=SimpleNamespace(level=18, quality=0, main_quality=0), utility_max_groups=max_groups,
                                fill_min_gain=0.005, fill_max_objective_loss=0.001)
    gen.objective = Objective(maximize="CombinedDPS", floors={"Life": 100.0})
    gen.log = lambda _m: None
    gen.picks = []
    gen.castability_context = None
    gen.castability_metrics = CastabilityMetrics()
    gen._set_main_link = lambda *_a, **_k: None
    gen._reconfigure = lambda *_a, **_k: None
    gen._restore_castability = lambda *_a, **_k: None
    gen.fill_candidates = lambda _sk: list(candidates)
    gen._reserve_pools = lambda name: frozenset(({"Mana"} if name in reserving else set()) | ({"Life"} if name in life_reserving else set()))
    room = capacity if capacity is not None else {"Helmet": 3, "Gloves": 3}
    # PoB's readback of the sockets no gem holds yet, as the colours of those sockets (white unless the test names them)
    gen._free_sockets = lambda: ({slot: list(colours) for slot, colours in sockets.items()} if sockets is not None else
                                 {slot: ["W"] * (n - sum(len(g.gems) for g in skeleton.extra_groups if g.slot == slot)) for slot, n in room.items()})
    return gen, pob


def _tune(pob: _Pob, skeleton: Skeleton):
    """The pipeline's callback in miniature: the REAL `tune_given_choices` over a fake lane writer."""

    def write(_skeleton, derived) -> None:
        pob.stance = str(derived.conservative.inputs.get("bloodSandStance") or "BLOOD")

    def tune(sk: Skeleton, choices: dict[str, list[str]]) -> dict[str, str]:
        derived = DerivedConfig(conservative=LaneConfig(), optimistic=LaneConfig(), shown=[])
        return tune_given_choices(pob, sk, derived, choices, objective=Objective(maximize="CombinedDPS", floors={"Life": 100.0}),
                                  write=write, log=lambda _m: None)

    return tune


def _counter(cls: str) -> tuple[int, int]:
    row = TRACE.considered()["picks"].get(cls) or {"generated": 0, "evaluated": 0}
    return row["generated"], row["evaluated"]


def _run(gen: SkeletonGenerator, pob: _Pob, skeleton: Skeleton) -> list[SocketGroup]:
    added = gen.pick_fill(skeleton, tune=_tune(pob, skeleton))
    TRACE.flush("picks")
    return added


# -- row 1: the candidates are retrieved ---------------------------------------------------

@needs_skill_data
def test_the_candidate_list_is_retrieved_and_holds_the_four_named_gems() -> None:
    gen = SkeletonGenerator.__new__(SkeletonGenerator)
    gen.rails = Rails.load()
    names = gen.fill_candidates(_skeleton())

    # Skitterbots is PoB's "Summon Skitterbots"; Tempest Shield and Withering Step carry no aura / guard / herald tag,
    # PoB's skill type "buff" is what retrieves them
    assert {"Tempest Shield", "Summon Skitterbots", "Withering Step", "Flesh and Stone"} <= set(names)
    assert {"Haste", "Determination", "Herald of Ash"} <= set(names)


@needs_skill_data
def test_the_uptime_rule_the_vaal_variants_and_the_present_gems_are_left_out() -> None:
    gen = SkeletonGenerator.__new__(SkeletonGenerator)
    gen.rails = Rails.load()
    names = set(gen.fill_candidates(_skeleton("Haste")))

    assert not names & {"Steelskin", "Immortal Call", "Phase Run", "Arcane Cloak"}, "buff_uptime < 0.9 is dropped as today"
    assert not [n for n in names if n.startswith("Vaal ")]
    assert "Haste" not in names, "a gem the build carries is not offered twice"
    assert not names & {"Smoke Mine", "Lightning Warp"}


@needs_skill_data
def test_flesh_and_stone_owns_the_stance_choice_and_tempest_shield_owns_none() -> None:
    assert own_choices("Flesh and Stone") == {"bloodSandStance": ["BLOOD", "SAND"]}
    assert own_choices("Tempest Shield") == {}
    assert own_choices("Haste") == {}


# -- row 1: Flesh and Stone is measured under both stances -----------------------------------

def test_flesh_and_stone_is_measured_under_both_stances_and_keeps_the_better_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("junkroan.search.generator.own_choices",
                        lambda name: {"bloodSandStance": ["BLOOD", "SAND"]} if name == "Flesh and Stone" else {})
    skeleton = _skeleton()
    gen, pob = _gen(skeleton, ["Flesh and Stone"])

    added = _run(gen, pob, skeleton)

    assert pob.stances_seen == {"BLOOD", "SAND"}, "the config default alone (Blood) would drop the gem"
    assert [g.gems for g in added] == [["Flesh and Stone"]]
    assert skeleton.tuned_choices == {"bloodSandStance": "SAND"}, "the kept stance stays on the skeleton for every later reconfigure"


def test_a_rejected_candidate_leaves_the_tuned_choices_as_they_were(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("junkroan.search.generator.own_choices", lambda name: {"bloodSandStance": ["BLOOD", "SAND"]})
    skeleton = _skeleton()
    skeleton.tuned_choices = {"bloodSandStance": "BLOOD", "other": "x"}
    gen, pob = _gen(skeleton, ["Tiny"])

    added = _run(gen, pob, skeleton)

    assert added == []
    assert skeleton.tuned_choices == {"bloodSandStance": "BLOOD", "other": "x"}


# -- the keep rule -------------------------------------------------------------------------

@pytest.mark.parametrize("gem, kept", [
    ("Haste", True),             # objective +6 %
    ("Determination", True),     # TotalEHP +10 %, objective flat
    ("Tempest Shield", True),    # TotalEHP +3 %
    ("Tiny", False),             # +0.4 % EHP: below 0.5 %
    ("Costly", False),           # objective -0.2 %: more than 0.1 %
    ("Barely", True),            # objective -0.09 % with EHP +2 %: inside the 0.1 % allowed
    ("Fragile", False),          # +10 % on both but the Life floor is missed
])
def test_the_keep_rule(gem: str, kept: bool) -> None:
    skeleton = _skeleton()
    gen, pob = _gen(skeleton, [gem])

    added = _run(gen, pob, skeleton)

    assert [g.gems[0] for g in added] == ([gem] if kept else [])
    assert [g for grp in skeleton.extra_groups for g in grp.gems] == ([gem] if kept else [])


def test_the_step_is_greedy_and_ends_when_nothing_is_kept() -> None:
    skeleton = _skeleton()
    gen, pob = _gen(skeleton, ["Tiny", "Determination", "Haste", "Costly"])

    added = _run(gen, pob, skeleton)

    assert [g.gems[0] for g in added] == ["Haste", "Determination"], "the best objective first, then the EHP aura; Tiny and Costly never"
    assert all(g.picked for g in added)


# -- not capped by max_groups, bounded by the free sockets ------------------------------------

def test_the_step_adds_groups_beyond_max_groups() -> None:
    skeleton = _skeleton("Dash", "Frostblink", "Shield Charge", "Smite")  # 4 groups already, max_groups = 2
    skeleton.extra_groups.append(SocketGroup(gems=["Grace"], slot="Boots", label="Grace"))
    gen, pob = _gen(skeleton, ["Haste", "Tempest Shield"], max_groups=2, capacity={"Helmet": 4, "Gloves": 3, "Boots": 2})

    added = _run(gen, pob, skeleton)

    assert [g.gems[0] for g in added] == ["Haste", "Tempest Shield"]
    assert len(skeleton.extra_groups) == 7


def test_the_step_stops_when_no_socket_is_free_and_writes_nothing() -> None:
    skeleton = _skeleton("Dash")
    gen, pob = _gen(skeleton, ["Haste", "Tempest Shield"], capacity={"Helmet": 1})

    added = _run(gen, pob, skeleton)

    assert added == [] and pob.calls == 0, "no free socket: no PoB call"
    assert _counter("fill-candidate") == (0, 0)


def test_a_group_goes_into_a_slot_that_has_a_free_socket() -> None:
    skeleton = _skeleton("Dash")
    gen, pob = _gen(skeleton, ["Haste"], capacity={"Helmet": 1, "Gloves": 2})

    added = _run(gen, pob, skeleton)

    assert [(g.gems[0], g.slot) for g in added] == [("Haste", "Gloves")]


def test_the_step_fills_every_free_socket_a_candidate_fits() -> None:
    skeleton = _skeleton()
    gen, pob = _gen(skeleton, ["Haste", "Tempest Shield"], capacity={"Helmet": 1, "Gloves": 1})

    added = _run(gen, pob, skeleton)

    assert {g.gems[0] for g in added} == {"Haste", "Tempest Shield"}
    assert {g.slot for g in added} == {"Helmet", "Gloves"}


def test_reserving_candidates_are_not_offered_once_no_mana_is_left() -> None:
    skeleton = _skeleton()
    # Haste takes 100 of the 500 Mana and Heavy Aura the other 400: nothing is left for Flesh and Stone
    gen, pob = _gen(skeleton, ["Haste", "Heavy Aura", "Flesh and Stone", "Tempest Shield"], reserving=("Haste", "Heavy Aura", "Flesh and Stone"))

    added = _run(gen, pob, skeleton)

    names = [g.gems[0] for g in added]
    assert names == ["Haste", "Heavy Aura", "Tempest Shield"], names
    assert "Flesh and Stone" not in names, "ManaUnreserved is 0: a reserving gem is not measured any more"


# -- the socket colour (send-back 1): a gem goes only into a free socket its colour fits ------------

@pytest.fixture
def colours(monkeypatch: pytest.MonkeyPatch):
    table: dict[str, str | None] = {}
    monkeypatch.setattr("junkroan.search.generator.gem_colour", lambda name: table.get(name))
    return table


def test_a_gem_with_no_free_socket_of_its_colour_is_never_evaluated(colours) -> None:
    colours.update({"Haste": "R", "Tempest Shield": "B"})
    skeleton = _skeleton()
    gen, pob = _gen(skeleton, ["Haste", "Tempest Shield"], sockets={"Helmet": ["R"]})

    added = _run(gen, pob, skeleton)

    assert [g.gems[0] for g in added] == ["Haste"]
    assert _counter("gem:Tempest Shield") == (0, 0), "a blue gem with only a red free socket never reaches PoB"
    assert _counter("gem:Haste")[1] > 0


def test_a_white_socket_takes_any_colour_and_an_abyss_socket_none(colours) -> None:
    colours.update({"Haste": "R", "Tempest Shield": "B"})
    skeleton = _skeleton()
    gen, pob = _gen(skeleton, ["Haste", "Tempest Shield"], sockets={"Helmet": ["W"], "Gloves": ["A"]})

    added = _run(gen, pob, skeleton)

    assert [(g.gems[0], g.slot) for g in added] == [("Haste", "Helmet")], "Haste takes the white socket; the abyss socket takes nothing"
    assert _counter("gem:Tempest Shield") == (1, 1), "the blue gem fitted the white socket in round one (measured once), then no socket was left"


def test_a_gem_with_no_colour_in_the_corpus_fits_any_socket_but_an_abyss_one(colours) -> None:
    skeleton = _skeleton()
    gen, pob = _gen(skeleton, ["Haste"], sockets={"Helmet": ["A"], "Gloves": ["R"]})

    added = _run(gen, pob, skeleton)

    assert [(g.gems[0], g.slot) for g in added] == [("Haste", "Gloves")]


def test_a_kept_gem_uses_up_the_socket_it_fits_and_takes_its_own_colour_before_a_white_one(colours) -> None:
    colours.update({"Haste": "R", "Determination": "B", "Tempest Shield": "R"})
    skeleton = _skeleton()
    # Haste (the best objective) must take the red socket, not the white: then Determination (blue) still has the white one
    gen, pob = _gen(skeleton, ["Haste", "Determination", "Tempest Shield"], sockets={"Helmet": ["W", "R"]})

    added = _run(gen, pob, skeleton)

    assert [g.gems[0] for g in added] == ["Haste", "Determination"], "both sockets are used up: Tempest Shield (red) finds none left"
    assert _counter("gem:Tempest Shield")[1] == 2, "measured in rounds one and two (the white socket fits it), then both sockets were used up"


def test_the_slot_is_the_first_one_with_a_socket_that_fits(colours) -> None:
    colours.update({"Haste": "B"})
    skeleton = _skeleton()
    gen, pob = _gen(skeleton, ["Haste"], sockets={"Helmet": ["R", "R"], "Gloves": ["B"]})

    added = _run(gen, pob, skeleton)

    assert [(g.gems[0], g.slot) for g in added] == [("Haste", "Gloves")]


# -- the reservation pools (send-back 1): Mana and Life each stop their own reservers -------------------

def test_a_life_reserving_gem_is_not_offered_once_no_life_is_left(colours) -> None:
    skeleton = _skeleton()
    # Blood Aura reserves 100 of the 100 Life: Blood Aura 2 is not measured although 500 Mana is free; Tempest Shield still is
    gen, pob = _gen(skeleton, ["Blood Aura", "Blood Aura 2", "Tempest Shield"], reserving=(), life_reserving=("Blood Aura", "Blood Aura 2"))

    added = _run(gen, pob, skeleton)

    assert [g.gems[0] for g in added] == ["Blood Aura", "Tempest Shield"], [g.gems[0] for g in added]
    assert _counter("gem:Blood Aura 2") == (1, 1), "measured in round one only, while Life was whole"


def test_a_mana_reserving_gem_is_still_offered_while_only_life_is_spent(colours) -> None:
    skeleton = _skeleton()
    gen, pob = _gen(skeleton, ["Blood Aura", "Haste"], reserving=("Haste",), life_reserving=("Blood Aura",))

    added = _run(gen, pob, skeleton)

    assert {g.gems[0] for g in added} == {"Blood Aura", "Haste"}


def test_the_reservation_pools_come_from_pobs_level_data() -> None:
    from junkroan.pob.skill_facts import reservation_pools_from_block

    def block(*fields: str) -> str:
        return 'skills["X"] = {\n\tlevels = {\n\t\t[1] = { ' + ", ".join(fields) + ', levelRequirement = 1, },\n\t},\n}'

    assert reservation_pools_from_block(block("manaReservationPercent = 25")) == frozenset({"Mana"})
    assert reservation_pools_from_block(block("lifeReservationPercent = 10")) == frozenset({"Life"})
    assert reservation_pools_from_block(block("manaReservationFlat = 30")) == frozenset({"Mana"})
    assert reservation_pools_from_block(block("manaReservationPercent = 25", "lifeReservationPercent = 10")) == frozenset({"Mana", "Life"})
    support_constant = 'skills["Z"] = {\n\tstatMap = { skill("lifeReservationFlat", 0), skill("lifeReservationPercent", 0), },\n}'
    assert reservation_pools_from_block(support_constant) == frozenset(), "a constant 0 is no reservation"


@needs_skill_data
def test_pobs_own_gems_name_their_pool() -> None:
    from junkroan.pob.skill_facts import reservation_pools

    assert reservation_pools("ThirstForBlood") == frozenset({"Life"}), "a level-data lifeReservationPercent names Life"
    assert reservation_pools("Haste") == frozenset({"Mana"})


# -- the trace counter ---------------------------------------------------------------------

def test_fill_candidate_is_generated_before_the_pob_call_and_evaluated_at_it() -> None:
    skeleton = _skeleton()
    gen, pob = _gen(skeleton, ["Haste", "Tiny"])

    _run(gen, pob, skeleton)

    generated, evaluated = _counter("fill-candidate")
    assert generated > 0 and evaluated > 0, (generated, evaluated)
    assert _counter("gem:Haste")[1] > 0 and _counter("gem:Tiny")[1] > 0, "the gem classes are counted as the picker's are"


def test_the_trace_output_counts_the_delivered_fill_gems(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("junkroan.search.generator.fill_candidate_names", lambda: frozenset({"Haste", "Tempest Shield"}))
    xml = ("<PathOfBuilding><Build mainSocketGroup=\"1\"/><Skills activeSkillSet=\"1\"><SkillSet id=\"1\">"
           "<Skill enabled=\"true\" slot=\"Body Armour\"><Gem nameSpec=\"Haste\" enabled=\"true\"/></Skill>"  # the main group is never counted
           "<Skill enabled=\"true\" slot=\"Helmet\"><Gem nameSpec=\"Haste\" enabled=\"true\"/></Skill>"
           "<Skill enabled=\"true\" slot=\"Gloves\"><Gem nameSpec=\"Tempest Shield\" enabled=\"true\"/></Skill>"
           "<Skill enabled=\"false\" slot=\"Boots\"><Gem nameSpec=\"Haste\" enabled=\"true\"/></Skill>"
           "<Skill enabled=\"true\" slot=\"Boots\"><Gem nameSpec=\"Dash\" enabled=\"true\"/></Skill>"
           "</SkillSet></Skills></PathOfBuilding>")

    assert trace_output_from_xml(xml)["fill-candidate"] == 2


# -- the free sockets are PoB's own readback -----------------------------------------------------

def _socket(colour: str, group: int = 0) -> dict:
    return {"color": colour, "group": group}  # PoB's own readback shape (headless worker collect_socket_list)


def test_the_free_sockets_are_the_colours_of_the_items_sockets_no_gem_holds() -> None:
    gen = SkeletonGenerator.__new__(SkeletonGenerator)
    state = {"items_state": {"slots": {"Helmet": {"item": {"sockets": [_socket("W"), _socket("R"), _socket("B")]}},
                                       "Gloves": {"item": {"sockets": [_socket("W"), _socket("W")]}},
                                       "Boots": {"item": None}, "Body Armour": {"item": {"sockets": [_socket("W")] * 6}}}},
             "skills_state": {"socket_groups": [{"slot": "Helmet", "gems": [{"gem_name": "Haste"}]},
                                                {"slot": "Gloves", "gems": [{"gem_name": "A"}, {"gem_name": "B"}]},
                                                {"slot": "Body Armour", "gems": [{"gem_name": "Cleave"}] * 6}]}}
    gen.pob = SimpleNamespace(read_state=lambda: state)

    assert gen._free_sockets() == {"Helmet": ["R", "B"]}, "PoB gives the first socket to the first gem; Gloves are full, Boots hold no item, the Body Armour holds the main link"


# -- the rails ------------------------------------------------------------------------------------

def test_the_rails_key_is_on_on_day_one_and_the_thresholds_live_in_the_rails_file() -> None:
    rails = Rails.load()
    assert rails.fill_step is True
    assert rails.fill_min_gain == 0.005 and rails.fill_max_objective_loss == 0.001
