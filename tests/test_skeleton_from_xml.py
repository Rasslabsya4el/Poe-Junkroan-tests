"""What the skeleton of an author's build carries and what it drops (the user's reading of
2026-09-18): only rares are rolled and only uniques are fixed, and a socket group that supports
nothing is not a group. No PoB: the derivation reads the export and the corpora.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_from_skeleton import ascendancy_from_nodes, base_of_item_name, drop_unsupported_gems, main_active_gem_index, skeleton_from_xml  # noqa: E402

from conftest import needs_skill_source  # noqa: E402
from junkroan.optimizer.rails import Rails  # noqa: E402
from junkroan.pob.session import decode_import_code  # noqa: E402
from junkroan.search.skeleton import Skeleton, SocketGroup  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "tuadh_329"
ZIZARAN = ROOT / "tests" / "fixtures"


def _skeleton(slug: str):
    return skeleton_from_xml(decode_import_code((FIXTURES / f"{slug}.pob.txt").read_text(encoding="utf-8").strip()))


def _zizaran_skeleton(league: str, slug: str, log=None):
    path = ZIZARAN / f"zizaran_{league}" / "early" / f"{slug}.pob.txt"
    return skeleton_from_xml(decode_import_code(path.read_text(encoding="utf-8").strip()), log=log)


def _synthetic(gems, *, main_active_skill=1, class_name="Witch", ascendancy="Necromancer", nodes="", items: dict[str, str] | None = None) -> str:
    """A minimal PoB export: one socket group, one spec. `gems` is (name, enabled) pairs in the
    author's own order, which is not necessarily the order PoB reads them in. `items` is
    {slot: raw item text}, the same shape `Skeleton.apply`'s `equip` and PoB's own export use."""

    sockets = "".join(f'<Gem nameSpec="{name}" level="20" quality="20" enabled="{"true" if enabled else "false"}"/>' for name, enabled in gems)
    items = items or {}
    item_elements = "".join(f'<Item id="{i}">{text}</Item>' for i, text in enumerate(items.values(), start=1))
    slot_elements = "".join(f'<Slot name="{slot}" itemId="{i}"/>' for i, slot in enumerate(items, start=1))
    return (
        f'<PathOfBuilding><Build level="90" className="{class_name}" ascendClassName="{ascendancy}" mainSocketGroup="1"/>'
        f'<Skills activeSkillSet="1"><SkillSet id="1">'
        f'<Skill slot="Body Armour" mainActiveSkill="{main_active_skill}" enabled="true">{sockets}</Skill>'
        f'</SkillSet></Skills>'
        f'<Tree activeSpec="1"><Spec treeVersion="3_29" nodes="{nodes}"/></Tree>'
        f'<Items activeItemSet="1">{item_elements}<ItemSet id="1">{slot_elements}</ItemSet></Items></PathOfBuilding>'
    )


def test_the_main_link_head_is_the_active_skill_mainactiveskill_names_not_the_first_gem() -> None:
    """PoB's `mainActiveSkill` is a 1-based index into the group's ACTIVE skills, and an author may
    socket a support first. Reading gems[0] as the main skill made `objective_for` pick CombinedDPS
    for a support name and score two references 0 (2026-09-18)."""

    support_first = _synthetic([("Minion Damage", True), ("Raise Spectre", True), ("Spell Echo", True)])
    skeleton = skeleton_from_xml(support_first)
    assert skeleton.main_link == ["Raise Spectre", "Minion Damage", "Spell Echo"], "the head moves, the supports keep the author's order"

    # a group with several active skills: the author's index picks among them, supports do not count
    three = [("Spellslinger", True), ("Controlled Destruction", True), ("Contagion", True), ("Essence Drain", True)]
    assert skeleton_from_xml(_synthetic(three, main_active_skill=3)).main_link[0] == "Essence Drain"
    assert skeleton_from_xml(_synthetic(three, main_active_skill=1)).main_link[0] == "Spellslinger"
    assert skeleton_from_xml(_synthetic(three, main_active_skill=9)).main_link[0] == "Essence Drain", "PoB clamps the index to the list length"

    # a disabled gem is in no list; a group of nothing but supports keeps the author's order
    assert skeleton_from_xml(_synthetic([("Cyclone", False), ("Melee Physical Damage", True), ("Boneshatter", True)])).main_link[0] == "Boneshatter"
    assert main_active_gem_index(["Melee Physical Damage", "Brutality"], 1) is None

    # a Vaal gem grants two skills and takes two places in PoB's list; either place is the same gem
    vaal = ["Vaal Ground Slam of Earthshaking", "Fist of War", "Pulverise"]
    assert main_active_gem_index(vaal, 1) == 0 and main_active_gem_index(vaal, 2) == 0
    assert main_active_gem_index(["Vaal Absolution", "Minion Damage", "Flame Dash"], 3) == 2, "the Vaal gem shifts the entries after it by one"


def test_the_two_references_whose_author_socketed_a_support_first_derive_their_real_skill() -> None:
    """z327_necromancer_raise_spectre lists Minion Damage first, z328_hierophant_shock_nova_archmage
    lists Archmage; both scored 0 as references before the head was read from `mainActiveSkill`."""

    assert _zizaran_skeleton("327", "necromancer_raise_spectre").main_link[0] == "Raise Spectre"
    assert _zizaran_skeleton("328", "hierophant_shock_nova_archmage").main_link[0] == "Shock Nova"
    # the same trap one step further in: Spellslinger is an active gem that deals no damage
    assert _zizaran_skeleton("329", "occultist_essence_drain").main_link[0] == "Essence Drain"
    # and the Tuadh references, whose authors socket the main skill first, are untouched
    assert _skeleton("stormbrand").main_link[0] == "Storm Brand"
    assert _skeleton("bleed_bow").main_link[0] == "Puncture"


def test_an_ascendancy_is_read_from_the_allocated_nodes_when_the_build_names_none() -> None:
    """z326_chieftain_righteous_fire exports `ascendClassName="None"` (the spec the author left
    active is their level 1-20 one) with six Chieftain nodes allocated. Without the inference
    `Skeleton.apply` would call `set_tree(ascendancy_id="None")` and lose the ascendancy."""

    lines: list[str] = []
    skeleton = _zizaran_skeleton("326", "chieftain_righteous_fire", log=lines.append)
    assert skeleton.class_name == "Marauder" and skeleton.ascendancy == "Chieftain"
    assert len(skeleton.ascendancy_nodes) == 6
    assert any("ascendancy read from the 6 allocated ascendancy nodes: Chieftain" in line for line in lines), lines

    # the nodes are the evidence, and a class filter keeps another class's ids out of the vote
    assert ascendancy_from_nodes(skeleton.ascendancy_nodes) == "Chieftain"
    assert ascendancy_from_nodes(skeleton.ascendancy_nodes, "Marauder") == "Chieftain"
    assert ascendancy_from_nodes(skeleton.ascendancy_nodes, "Witch") is None
    assert ascendancy_from_nodes([]) is None and ascendancy_from_nodes([1]) is None

    # an ascendancy the build does name is never second-guessed, and nothing is logged
    lines.clear()
    assert skeleton_from_xml(_synthetic([("Spark", True)], ascendancy="Occultist"), log=lines.append).ascendancy == "Occultist"
    assert skeleton_from_xml(_synthetic([("Spark", True)], ascendancy="None"), log=lines.append).ascendancy == "None", "no nodes, nothing to infer"
    assert lines == []


def test_a_magic_item_of_the_authors_becomes_a_rare_slot_to_roll() -> None:
    """vd_spellslinger s3 wore the author's own "Virile Ruby Ring of Craft": a MAGIC item fell
    through the UNIQUE / RARE sort and was carried as a fixed item for the whole run."""

    assert base_of_item_name("Virile Ruby Ring of Craft") == "Ruby Ring"  # the longest base in the name, never "Ring"
    assert base_of_item_name("Athlete's Great Crown of Craft") == "Great Crown"
    assert base_of_item_name("Nothing The Corpus Knows") is None

    skeleton = _skeleton("vd_spellslinger")
    assert skeleton.rare_bases.get("Ring 1") == "Ruby Ring"
    assert not any("Ring" in slot for slot in skeleton.jewels), skeleton.jewels
    assert all("Flask" in slot or "Jewel" in slot or "Abyssal" in slot for slot in skeleton.jewels), skeleton.jewels


def test_a_group_with_no_active_gem_is_not_carried_into_the_skeleton() -> None:
    """The audit already warns about a support-only group ("dead support group"); the skeleton
    now never brings one in. Eight references carry one: smite's helmet holds a lone Fortify."""

    smite = _skeleton("smite")
    assert all(g.gems for g in smite.extra_groups)
    assert not any(g.gems == ["Fortify"] for g in smite.extra_groups), [g.gems for g in smite.extra_groups]

    dead = {"absolution_minions": "More Duration", "hit_penance_brand": "Increased Critical Damage", "impale_cyclone": "Brutality",
            "poison_spectral_throw": "Greater Multiple Projectiles", "pyroclast_mine": "Momentum", "regular_viper_strike": "Chance to Poison",
            "smite": "Fortify", "spectral_shield_throw": "More Duration"}
    for slug, gem in dead.items():
        assert not any(g.gems == [gem] for g in _skeleton(slug).extra_groups), (slug, gem)


class _Readback:
    """PoB's unsupported-gem readback, as `PobSession.unsupported_gems` returns it."""

    def __init__(self, rows):
        self.rows = rows

    def unsupported_gems(self):
        return list(self.rows)


def test_a_support_pob_applies_to_nothing_is_dropped_from_its_group() -> None:
    """PoB's own verdict on the author's build (vd_spellslinger: Faster Attacks and Momentum in
    the boots, physical_dot: Unleash in the weapon), read back before we rebuild it."""

    skeleton = Skeleton(class_name="Witch", ascendancy="Necromancer", main_link=["Spark", "Sacrifice", "Cruelty"],
                        extra_groups=[SocketGroup(gems=["Hatred", "Generosity"], slot="Helmet", source_index=3),
                                      SocketGroup(gems=["Flame Dash"], slot="Boots", source_index=4)])
    rows = [{"group": 1, "gem": "Cruelty", "reason": "cannot apply to any of the active skills", "slot": "Body Armour"},
            {"group": 3, "gem": "Generosity", "reason": "superseded", "slot": "Helmet"},
            {"group": 4, "gem": "Flame Dash", "reason": "cannot apply to any of the active skills", "slot": "Boots"},
            {"group": 9, "gem": "Nothing", "reason": "cannot apply to any of the active skills", "slot": "Gloves"}]

    dropped = drop_unsupported_gems(_Readback(rows), skeleton, main_index=1)

    assert skeleton.main_link == ["Spark", "Sacrifice"], "a support of the main link goes too"
    assert [g.gems for g in skeleton.extra_groups] == [["Hatred"], ["Flame Dash"]], "the last gem of a group is never taken away"
    assert len(dropped) == 2 and "Cruelty (cannot apply to any of the active skills) from group 1" in dropped[0]


def test_every_reference_keeps_only_uniques_and_jewels_out_of_the_rolled_slots() -> None:
    """The same on the whole reference set: eight of them equip a magic item in a gear slot."""

    for slug in sorted(p.name[: -len(".pob.txt")] for p in FIXTURES.glob("*.pob.txt")):
        skeleton = _skeleton(slug)
        assert all("Flask" in slot or "Jewel" in slot or "Abyssal" in slot for slot in skeleton.jewels), (slug, skeleton.jewels)
        assert not set(skeleton.rare_bases) & set(skeleton.uniques), slug


# -- spec 2026-09-22: the six ziz-rules gaps (fixture skeleton loads and obeys the rails) --------

_UNIQUE_ITEM = """Rarity: UNIQUE
{name}
{base}
Item Level: 83
LevelReq: {req_level}
Implicits: 0
"""


def test_a_unique_our_corpus_does_not_know_leaves_our_skeleton_but_the_base_stays() -> None:
    """requirement 3: z328_hierophant_shock_nova_archmage's "Foulborn Kikazaru" (a Settlers
    "Foulborn" mutated unique) is not a name our uniques corpus carries -- it only knows the base
    unique, "Kikazaru". Our own skeleton drops it; the slot becomes a rare slot on the item's own
    base (a legal rare base PoB's item corpus knows), one log line names the reason."""

    lines: list[str] = []
    xml = _synthetic([("Spark", True)], items={"Ring 1": _UNIQUE_ITEM.format(name="Foulborn Kikazaru", base="Topaz Ring", req_level=20)})
    skeleton = skeleton_from_xml(xml, log=lines.append, rails=Rails.load())
    assert "Ring 1" not in skeleton.uniques
    assert skeleton.rare_bases.get("Ring 1") == "Topaz Ring"
    assert any(l == "fixture unique dropped from our skeleton: Ring 1: Foulborn Kikazaru (unknown to our uniques corpus)" for l in lines), lines


def test_a_drop_disabled_unique_leaves_our_skeleton_on_its_own_base() -> None:
    """requirement 4: z327_assassin_poison_spark's Winterweave is availability "legacy" (wiki:
    drop disabled) in our uniques corpus -- known, but `Rails.unique_allowed` rejects it, same
    mechanism as requirement 3, on `Rails.load()`'s default rails (allowed availability "core")."""

    lines: list[str] = []
    xml = _synthetic([("Spark", True)], items={"Ring 2": _UNIQUE_ITEM.format(name="Winterweave", base="Coral Ring", req_level=24)})
    skeleton = skeleton_from_xml(xml, log=lines.append, rails=Rails.load())
    assert "Ring 2" not in skeleton.uniques
    assert skeleton.rare_bases.get("Ring 2") == "Coral Ring"
    assert any(l == "fixture unique dropped from our skeleton: Ring 2: Winterweave (legacy: no longer obtainable)" for l in lines), lines


def test_a_unique_merely_outside_the_rails_is_kept_not_dropped() -> None:
    """A unique `Rails.unique_allowed` rejects for a reason OTHER than "legacy" (wrong
    availability, req level, tier) is left in OUR skeleton: the audit already flags it as a
    WARNING ("unique outside the rails"), never an error, and two Necromancer references
    (z326_necromancer_zombie_army_early, z327_necromancer_raise_spectre) carry exactly this case
    with "Darkness Enthroned" (availability "boss"). Dropping it here broke requirement 6 ("no
    other skeleton may change") when this function used the literal, broader
    `not rails.unique_allowed(record)` test; see the final report."""

    lines: list[str] = []
    xml = _synthetic([("Spark", True)], items={"Weapon 1": _UNIQUE_ITEM.format(name="Jiquani's Potential", base="Imperial Staff", req_level=66)})
    assert not Rails.load().unique_allowed({"availability": "boss", "req_level": 66, "tier": 3}), "boss is not core: the rails already reject it elsewhere"
    skeleton = skeleton_from_xml(xml, log=lines.append, rails=Rails.load())
    assert skeleton.uniques.get("Weapon 1") == "Jiquani's Potential"
    assert "Weapon 1" not in skeleton.rare_bases
    assert lines == []


def test_a_known_legal_unique_is_never_touched() -> None:
    """No mismatch, no log: the filter is a no-op for the 56 other fixture skeletons (requirement
    6). "Kikazaru" itself (not the Foulborn variant) is `core`, tier 4, req level 20 -- legal."""

    lines: list[str] = []
    xml = _synthetic([("Spark", True)], items={"Ring 1": _UNIQUE_ITEM.format(name="Kikazaru", base="Topaz Ring", req_level=20)})
    skeleton = skeleton_from_xml(xml, log=lines.append, rails=Rails.load())
    assert skeleton.uniques.get("Ring 1") == "Kikazaru"
    assert "Ring 1" not in skeleton.rare_bases
    assert lines == []


def test_an_ascendancy_node_id_outside_the_selected_ascendancy_is_remapped_by_name() -> None:
    """requirement 2: z328_hierophant_kinetic_fusillade's fixture (a 3.28 tree) carries ascendancy
    node id 43376 for Hierophant; at the pinned tree version that id is Aul's Atlas-tree "The
    King's Heritage", not a Hierophant node at all -- `set_tree` rejected it as "outside selected
    ascendancy Hierophant". Node 922 is Hierophant's real, current "Divine Guidance": remapping by
    the fixture's own (pre-conversion) name recovers it."""

    lines: list[str] = []
    xml = _synthetic([("Storm Burst", True)], ascendancy="Hierophant", nodes="43376", class_name="Templar")
    skeleton = skeleton_from_xml(xml, log=lines.append, ascendancy_node_names={43376: "Divine Guidance"})
    assert skeleton.ascendancy_nodes == [922]
    assert "fixture ascendancy node 43376 'Divine Guidance' -> 922" in lines


def test_an_unmatched_ascendancy_node_id_is_dropped_not_guessed() -> None:
    """No name, or a name with no single match in the selected ascendancy: dropped, not carried
    through to `set_tree` where it would fail again or silently path onto the wrong node."""

    lines: list[str] = []
    xml = _synthetic([("Storm Burst", True)], ascendancy="Hierophant", nodes="43376", class_name="Templar")
    skeleton = skeleton_from_xml(xml, log=lines.append)  # no ascendancy_node_names at all
    assert skeleton.ascendancy_nodes == []
    assert "fixture ascendancy node 43376 '?' -> dropped" in lines

    lines.clear()
    skeleton = skeleton_from_xml(xml, log=lines.append, ascendancy_node_names={43376: "Not A Real Node Name"})
    assert skeleton.ascendancy_nodes == []
    assert "fixture ascendancy node 43376 'Not A Real Node Name' -> dropped" in lines


def test_a_valid_ascendancy_node_id_is_never_touched() -> None:
    """The no-op case, general (requirement 6): a node id already valid for the selected
    ascendancy is kept exactly as it is, whether or not old names are supplied."""

    lines: list[str] = []
    xml = _synthetic([("Storm Burst", True)], ascendancy="Hierophant", nodes="922", class_name="Templar")
    skeleton = skeleton_from_xml(xml, log=lines.append, ascendancy_node_names={43376: "Divine Guidance"})
    assert skeleton.ascendancy_nodes == [922]
    assert lines == []


def test_ascendancy_nodes_the_conversion_dropped_leave_the_skeleton() -> None:
    """spec 2026-09-23: z325_berserker_ground_slam_autocry's fixture allocates 8 ascendancy nodes
    on its 3.25 tree; `pob.convert_tree()` drops one (on the current tree its prerequisite is not
    allocated). Our skeleton is read from the PRE-conversion XML, so the lead's rule is: only the
    author's ascendancy nodes STILL allocated after the conversion. Carrying a dropped id made
    `set_tree` path through the missing prerequisite, and the build ended with 9 ascendancy nodes
    against the rails' 8 (`prepare_author` reads the converted set from PoB and passes it here)."""

    from junkroan.pob.tree_payload_normalization import canonical_active_tree_corpus  # noqa: PLC0415
    from junkroan.search.hypothesis import ascendancies  # noqa: PLC0415

    canon = {int(n) for n in canonical_active_tree_corpus()["ascendancy_node_ids"]}
    record = ascendancies()["berserker"]
    ids = [int(n["node_id"]) for n in record["nodes"] if not n.get("is_ascendancy_start") and int(n["node_id"]) in canon][:8]
    names = {int(n["node_id"]): str(n.get("name") or "") for n in record["nodes"]}
    assert len(ids) == 8, ids

    xml = _synthetic([("Ground Slam", True)], ascendancy="Berserker", class_name="Marauder", nodes=",".join(str(n) for n in ids))
    dropped = ids[-1]

    lines: list[str] = []
    skeleton = skeleton_from_xml(xml, log=lines.append, ascendancy_node_names=names, allocated_after_convert=set(ids[:-1]))
    assert skeleton.ascendancy_nodes == ids[:-1], "a node the conversion dropped is not carried"
    assert lines == [f"fixture ascendancy node {dropped} '{names[dropped]}' dropped: not allocated after tree conversion"], lines

    lines.clear()
    assert skeleton_from_xml(xml, log=lines.append, ascendancy_node_names=names).ascendancy_nodes == ids, "None keeps today's behaviour"
    assert lines == []


class _RecordingPob:
    """Records the skills payload `Skeleton.apply_skills` writes (no PoB)."""

    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def set_skills(self, **payload) -> None:
        self.payloads.append(payload)


def _written_levels(skeleton) -> dict[str, int]:
    pob = _RecordingPob()
    rail = Rails.load().gems.level
    skeleton.apply_skills(pob, gem_level=rail)
    groups = pob.payloads[-1]["extra_groups"]
    return {gem["gem_name"]: gem["level"] for group in groups for gem in group["gems"]}


def _with_vitality(level: int):
    xml = _synthetic([("Fireball", True), ("Added Fire Damage", True)])
    group = '<Skill slot="Helmet" enabled="true" mainActiveSkill="1"><Gem nameSpec="Vitality" level="%d" quality="0" enabled="true"/></Skill>' % level
    return skeleton_from_xml(xml.replace("</Skill></SkillSet>", "</Skill>" + group + "</SkillSet>"))


@needs_skill_source  # #1207: flat_reservation_auras() reads vendor/pob data; the GitHub copy has none
def test_816_row9_aura_level_below_the_rail_in_the_xml_survives_the_first_skills_write() -> None:
    """#816 row 9a: a delivered build whose Vitality is level 1 re-written at the rail level by the bench's first
    rejudge dropped five floors. The level comes from the XML, so `apply_skills` writes the same level back."""

    skeleton = _with_vitality(1)
    assert skeleton.aura_levels == {"Vitality": 1}
    assert _written_levels(skeleton)["Vitality"] == 1


def test_816_row9_aura_level_at_or_above_the_rail_keeps_todays_behaviour() -> None:
    rail = Rails.load().gems.level
    for level in (rail, rail + 2):
        skeleton = _with_vitality(level)
        assert skeleton.aura_levels == {}, "the pipeline pops a level equal to the rail; a level above it is written at the rail anyway"
        assert _written_levels(skeleton)["Vitality"] == rail
