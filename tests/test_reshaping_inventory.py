"""#1042 unit 1: the keystone part of the day-1 reshaping inventory, regenerated from #1030's parse and flips (no PoB).

Two groups. The synthetic group runs anywhere: rows built from the tracked #1030 parse fixture plus small flip dicts.
The artifact group reads `artifacts/keystone_flip/*.json` (untracked, linked into every worktree) and skips when they
are absent; it holds the regeneration check (0 differing rows) and the three sanity rows on the real numbers."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import reshaping_inventory as inv  # noqa: E402
from junkroan.keystone_parse import classify_keystone  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "issue1030_keystone_parse.json"
ARTIFACTS = ROOT / "artifacts" / "keystone_flip"
HAVE_ARTIFACTS = all((ARTIFACTS / f"{n}.json").exists() for n in ("parse", *inv.BUILDS))
needs_artifacts = pytest.mark.skipif(not HAVE_ARTIFACTS, reason="artifacts/keystone_flip/*.json not present")

BASE = {"Life": 4000, "Mana": 900, "ManaUnreserved": 50, "EnergyShield": 300, "FireResist": 75, "ColdResist": 75, "LightningResist": 75}
RAILS = {"floors": {"Life": 4500}, "tree": {"forbidden_text": []}}


def _fixture_parse() -> list[dict]:
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))
    out = [classify_keystone(r["keystone"], r["stats"], r["parsed"]) for r in rows]
    battery_line = "Energy Shield protects Mana instead of Life"
    battery = {"line": battery_line, "ok": True, "extra": "", "mods": [{"name": "EnergyShieldProtectsMana", "type": "FLAG", "value": True}]}
    out.append(classify_keystone("Eldritch Battery", [battery_line], [battery]))
    return out


def _flip(name: str, state2: dict, flip: str = "add", status: str = "ok", reason: str | None = None) -> dict:
    return {"keystone": name, "status": status, "reason": reason, "flip": flip, "state1": BASE, "state2": state2 or None, "delta_pct": {"CombinedDPS": 1.5}}


def _flips(extra: dict[str, list[dict]] | None = None) -> dict[str, dict]:
    per_build = {
        "Chaos Inoculation": {**BASE, "Life": 1},
        "Blood Magic": {**BASE, "Life": 4400, "Mana": 0, "ManaUnreserved": None},
        "Mind Over Matter": {**BASE, "Life": 4010},
        "Eldritch Battery": {**BASE, "EnergyShield": 310},
    }
    return {b: {"rows": [_flip(n, s) for n, s in per_build.items()] + (extra or {}).get(b, [])} for b in inv.BUILDS}


def _rows(parse=None, flips=None, rails=None):
    node_ids = {r["keystone"]: i for i, r in enumerate(parse or _fixture_parse(), start=1)}
    return inv.keystone_rows(parse or _fixture_parse(), flips or _flips(), rails or RAILS, node_ids)


def test_stat_collapsed_needs_a_value_to_lose_and_a_missing_or_halved_state_2() -> None:
    assert inv.stat_collapsed(4000, 1)
    assert inv.stat_collapsed(50, None)
    assert inv.stat_collapsed(50, 24)
    assert not inv.stat_collapsed(50, 25)
    assert not inv.stat_collapsed(0, 0)
    assert not inv.stat_collapsed(-52, -100)
    assert not inv.stat_collapsed(None, 5)


def test_mana_is_named_only_when_manaunreserved_did_not_collapse() -> None:
    gone = {**BASE, "Mana": 0, "ManaUnreserved": None}
    assert inv.collapsed_floors(BASE, gone) == ("ManaUnreserved",)
    assert inv.collapsed_floors(BASE, {**BASE, "Mana": 0}) == ("Mana",)


def test_mod_floor_reads_pool_words_of_redirects_and_pool_overrides_only() -> None:
    assert inv.mod_floor("zero", {"name": "ChaosInoculation", "type": "FLAG", "value": True}) == "Life"
    assert inv.mod_floor("zero", {"name": "EnergyShield", "type": "MORE", "value": -100}) == "EnergyShield"
    assert inv.mod_floor("redirect", {"name": "EnergyShieldProtectsMana", "type": "FLAG", "value": True}) == "EnergyShield"
    assert inv.mod_floor("redirect", {"name": "DamageTakenFromManaBeforeLife", "type": "BASE", "value": 40}) == "ManaUnreserved"
    assert inv.mod_floor("zero", {"name": "NoLifeRegen", "type": "FLAG", "value": True}) is None
    assert inv.mod_floor("redirect", {"name": "PhysicalDamageConvertToFire", "type": "BASE", "value": 50}) is None


def test_sanity_rows_on_the_fixture() -> None:
    rows, excluded = _rows()
    by = {r.choice: r for r in rows}
    ci = by["Chaos Inoculation"]
    assert (ci.kind, ci.parse_kind, ci.floors) == ("keystone", "zero", ("Life",))
    bm = by["Blood Magic"]
    assert "redirect" in bm.parse_kind and "ManaUnreserved" in bm.floors  # the flip collapses ManaUnreserved: a candidate
    eb = by["Eldritch Battery"]
    assert (eb.parse_kind, eb.floors) == ("redirect", ("EnergyShield",))
    assert "from the parsed mods" in eb.flip  # no flip collapsed a pool: the floor is the mod's
    assert {e.choice: e.reason for e in excluded} == {"Iron Grip": "add", "Elemental Equilibrium": "unparsed"}


def test_blood_magic_without_a_collapse_would_keep_the_floor_the_mod_names() -> None:
    flips = _flips()
    for payload in flips.values():
        for row in payload["rows"]:
            if row["keystone"] == "Blood Magic":
                row["state2"] = {**BASE, "Life": 4400}
    bm = {r.choice: r for r in _rows(flips=flips)[0]}["Blood Magic"]
    assert "from the parsed mods" in bm.flip
    assert bm.floors == ("Life", "ManaUnreserved")  # Mana -100 and Reserve Life instead of Mana: the pools the mods name


def test_unknown_node_keeps_a_keystone_out_of_the_pool() -> None:
    reason = "PoBHeadlessHostContractError: mutate_tree_nodes: unknown node id(s): [4242]"
    refused = {b: [_flip("Chaos Inoculation", {}, status="pob_refused", reason=reason)] for b in inv.BUILDS}
    flips = _flips(refused)
    for payload in flips.values():  # the later row for the same name wins: drop the measured one
        payload["rows"] = [r for r in payload["rows"] if not (r["keystone"] == "Chaos Inoculation" and r["status"] == "ok")]
    ci = {r.choice: r for r in _rows(flips=flips)[0]}["Chaos Inoculation"]
    assert ci.in_pool == "no: node 4242 unknown to PoB's tree"
    assert ci.floors == ("Life",)  # the mod's own floor still stands


def test_rails_forbidden_text_keeps_a_keystone_out_of_the_pool() -> None:
    rails = {"floors": {"Life": 4500}, "tree": {"forbidden_text": ["Maximum Life becomes 1"]}}
    rows, _ = _rows(rails=rails)
    assert {r.choice: r.in_pool for r in rows}["Chaos Inoculation"].startswith("no: the rails")


def test_header_counts_kinds_and_floors() -> None:
    rows, excluded = _rows()
    header = inv.header_line(rows, excluded)
    assert "keystone 4 candidates (4 in the day-1 pool, 0 not), 2 excluded" in header
    assert "stacking 0 candidates" in header and "unique 0 candidates" in header
    assert "Life 1, ManaUnreserved 2, EnergyShield 1" in header  # Blood Magic and Mind over Matter / Chaos Inoculation / Eldritch Battery


def test_render_is_deterministic_and_fills_the_unit_2_sections() -> None:
    parse, flips = _fixture_parse(), _flips()
    ids = {r["keystone"]: i for i, r in enumerate(parse, start=1)}
    first, second = inv.render(parse, flips, RAILS, ids), inv.render(parse, flips, RAILS, ids)
    assert first == second
    assert "## Stacking directions (Dex, Int, Str)" in first
    assert "## Uniques (parsed zero or redirect mod on a resource or a defence)" in first
    assert "floors.Life 4,500" in first


def test_unique_mod_effect_reads_the_parsed_mod_not_the_words() -> None:
    zero_life = {"line": "x", "name": "CannotGainLife", "type": "FLAG", "value": True}
    assert inv.unique_mod_effect(zero_life) == ("zero", None, "parse kind")
    assert inv.unique_mod_effect({"line": "x", "name": "EnergyShield", "type": "MORE", "value": -100}) == ("zero", "EnergyShield", "parse kind")
    assert inv.unique_mod_effect({"line": "x", "name": "ChaosResist", "type": "OVERRIDE", "value": 0})[:2] == ("zero", "ChaosResist")
    assert inv.unique_mod_effect({"line": "x", "name": "ColdResist", "type": "OVERRIDE", "value": 75}) is None  # not a zero
    assert inv.unique_mod_effect({"line": "x", "name": "Multiplier:ArmourDoubled", "type": "OVERRIDE", "value": 1}) is None
    assert inv.unique_mod_effect({"line": "x", "name": "CannotChill", "type": "FLAG", "value": True}) is None  # zero, no resource
    assert inv.unique_mod_effect({"line": "x", "name": "ExtraLifeReserved", "type": "BASE", "value": 30})[:2] == ("redirect", "Life")
    assert inv.unique_mod_effect({"line": "x", "name": "EnergyShieldToWard", "type": "FLAG", "value": True})[:2] == ("redirect", "EnergyShield")
    assert inv.unique_mod_effect({"line": "x", "name": "ConvertArmourESToLife", "type": "FLAG", "value": True})[:2] == ("redirect", "EnergyShield")


@needs_artifacts
def test_regeneration_gives_the_committed_table_to_the_byte() -> None:
    text = inv.render(*inv.load_inputs())
    committed = inv.OUT_PATH.read_text(encoding="utf-8")
    differing = [(a, b) for a, b in zip(text.splitlines(), committed.splitlines()) if a != b]
    assert len(text.splitlines()) == len(committed.splitlines())
    assert differing == []  # 0 differing rows
    assert text == committed


@needs_artifacts
def test_every_keystone_of_the_parse_is_in_exactly_one_table() -> None:
    parse, flips, rails, ids = inv.load_inputs()
    rows, excluded = inv.keystone_rows(parse, flips, rails, ids)
    names = [r.choice for r in rows] + [e.choice for e in excluded]
    assert sorted(names) == sorted(e["keystone"] for e in parse)
    assert len(names) == len(set(names)) == 57


@needs_artifacts
def test_three_sanity_rows_on_the_real_numbers() -> None:
    rows, excluded = inv.keystone_rows(*inv.load_inputs())
    by = {r.choice: r for r in rows}
    ci = by["Chaos Inoculation"]
    assert (ci.kind, ci.parse_kind, ci.floors) == ("keystone", "zero", ("Life",))
    assert ci.flip.count("floors collapsed: Life") == 3  # spark, cold_dot, smite
    bm = by["Blood Magic"]
    assert "redirect" in bm.parse_kind
    assert bm.floors == ("ManaUnreserved",)
    assert bm.flip.count("floors collapsed: ManaUnreserved") == 3
    eb = by["Eldritch Battery"]
    assert (eb.parse_kind, eb.floors) == ("redirect", ("EnergyShield",))
    assert "Blood Magic" not in {e.choice for e in excluded}


@needs_artifacts
def test_blood_magic_floor_is_read_from_the_real_keystone_row() -> None:
    # #1065 rule 2 on the real numbers: the floor the two Blood Magic support uniques take is the keystone row's own
    parse, flips, rails, ids = inv.load_inputs()
    floors = inv.blood_magic_keystone_floors(inv.keystone_rows(parse, flips, rails, ids)[0])
    assert floors == BLOOD_MAGIC_FLOORS == ("ManaUnreserved",)
    by = {r.choice: r for r in inv.unique_rows(inv.load_corpora(), rails, floors)[0]}
    assert by["Prism Guardian, Archon Kite Shield"].floors == floors == by["The Covenant, Spidersilk Robe"].floors


# the floor of the Blood Magic keystone row, as the fixture passes it to unique_rows; the artifact group reads the real row
BLOOD_MAGIC_FLOORS = ("ManaUnreserved",)


@pytest.fixture(scope="module")
def unit2():
    corpora, rails = inv.load_corpora(), json.loads(inv.RAILS_PATH.read_text(encoding="utf-8"))
    s_rows, s_excluded = inv.stacking_rows(corpora, rails)
    u_rows, u_excluded = inv.unique_rows(corpora, rails, BLOOD_MAGIC_FLOORS)
    return {r.choice: r for r in s_rows}, {r.choice: r for r in u_rows}, s_excluded, u_excluded


def test_stacking_has_the_three_directions_with_corpus_entries(unit2) -> None:
    stacking, _unique, s_excluded, _ = unit2
    assert sorted(stacking) == ["Dex stacking (Dexterity)", "Int stacking (Intelligence)", "Str stacking (Strength)"]
    for row in stacking.values():
        assert row.kind == "stacking" and row.floors == () and len(row.lines) == len(row.corpus.split("<br>"))
    # read in uniques.json / scaling_vectors.json: Wildwrap, Strapped Leather has "1% increased Damage per 15 Dexterity" (PerStat Dex div 15, stat Damage), legacy
    dex = stacking["Dex stacking (Dexterity)"]
    assert any("1% increased Damage per 15 Dexterity" in line and "[not in pool: availability legacy]" in line for line in dex.lines)
    assert "uniques.json key Wildwrap, Strapped Leather" in dex.corpus
    # read in passives.json: node 54436 Cold to the Core is a notable with one line per attribute
    assert any(l.startswith("Cold to the Core (notable, damage)") and "per 25 Dexterity" in l for l in dex.lines) and "passives.json node_id 54436" in dex.corpus
    assert any("Whispering Ice" in l and "1% increased Spell Damage per 10 Intelligence" in l for l in stacking["Int stacking (Intelligence)"].lines)
    assert any("Iron Fortress" in l and "Chance to Block Attack Damage per 50 Strength" in l for l in stacking["Str stacking (Strength)"].lines)
    assert any("a threshold, not per point" in e.reason for e in s_excluded)
    assert not any(e.reason.startswith("family mastery") for e in s_excluded)  # #1065 rule 1: a mastery line is a payoff


def test_str_row_holds_the_armour_mastery_payoff(unit2) -> None:
    # #1065 rule 1: masteries.json holds the "Armour Mastery" nodes with effect 46180 "+1 Armour per 2 Strength"
    # (PerStat Str div 2, stat Armour); node 45358 is the first of the five nodes that carry it
    stacking, _unique, _s, _u = unit2
    str_row = stacking["Str stacking (Strength)"]
    assert "Armour Mastery: +1 Armour per 2 Strength (mastery, defence): +1 Armour per 2 Strength" in str_row.lines
    assert "masteries.json node_id 45358" in str_row.corpus.split("<br>")
    assert str_row.in_pool == "yes" and str_row.kind == "stacking"


def test_blood_magic_support_uniques_take_the_blood_magic_floor(unit2) -> None:
    # #1065 rule 2: Prism Guardian and The Covenant carry ExtraSupport SupportBloodMagicUniquePrismGuardian
    _stacking, unique, _s, _u = unit2
    for name in ("Prism Guardian, Archon Kite Shield", "The Covenant, Spidersilk Robe"):
        assert unique[name].floors == ("ManaUnreserved",)
        assert "floor from the Blood Magic keystone row" in unique[name].flip
    with pytest.raises(ValueError):  # no keystone floor given: the generator refuses to invent one
        inv.unique_rows(inv.load_corpora(), json.loads(inv.RAILS_PATH.read_text(encoding="utf-8")))


def test_stun_threshold_lines_are_excluded_and_skyforth_zero_stays(unit2) -> None:
    # #1065 rule 3: "Stun Threshold is based on Energy Shield instead of Life" names no floor stat
    _stacking, unique, _s, u_excluded = unit2
    stun = {e.choice for e in u_excluded if e.reason == inv.STUN_REASON}
    assert {"Valyrium, Moonstone Ring", "Skyforth, Sorcerer Boots"} <= stun
    assert "Valyrium, Moonstone Ring" not in unique  # its only zero / redirect candidate line was the stun line: none left
    sky = unique["Skyforth, Sorcerer Boots"]
    assert (sky.parse_kind, sky.lines, sky.floors) == ("zero", ("You have no Life Regeneration",), ())


def test_unique_rows_sanity_on_the_corpus(unit2) -> None:
    _s, unique, _se, u_excluded = unit2
    # read in uniques.json: Glimpse of Chaos, Vaal Mask: "Chaos Resistance is Zero" = ChaosResist OVERRIDE 0, availability boss
    glimpse = unique["Glimpse of Chaos, Vaal Mask"]
    assert (glimpse.parse_kind, glimpse.floors) == ("zero", ("ChaosResist",)) and glimpse.in_pool == "no: availability boss"
    # Faithguard: EnergyShieldToWard (pool move), core, req 25, no tier data: in the pool
    faith = unique["Faithguard, Runic Helm"]
    assert (faith.parse_kind, faith.floors, faith.in_pool) == ("redirect", ("EnergyShield",), "yes")
    # Waxen Soul: CostLifeInsteadOfMana + BloodMagicReserved, core, in the pool
    waxen = unique["Waxen Soul, Saint's Hauberk"]
    assert (waxen.parse_kind, waxen.floors, waxen.in_pool) == ("redirect", ("Life",), "yes")
    # Midnight Bargain: "Reserves 30% of Life" parses as ExtraLifeReserved BASE 30; tier 4, outside the day-1 tier 5 rule
    bargain = unique["Midnight Bargain, Calling Wand"]
    assert "Reserves 30% of Life" in bargain.lines and bargain.floors == ("Life",) and bargain.in_pool == "no: tier 4"
    assert "Veil of the Night, Great Helmet" in unique and unique["Veil of the Night, Great Helmet"].floors == ("FireResist", "ColdResist", "LightningResist")
    assert u_excluded and all(e.kind == "unique" for e in u_excluded)
