"""Gems of a limited family above their limit are dropped at derivation (P2, 2026-09-18).

PoB applies every enabled golem's buff whatever ActiveGolemLimit says, so a skeleton carrying more
golem gems than its build can summon is scored on buffs the game cannot give it. Curses are the
other way round -- CalcPerform.lua fills `curseSlots` in `for i = 1, source.limit do`, so PoB
already drops the ones beyond EnemyCurseLimit -- but a skeleton that carries them anyway spends
sockets on nothing and disagrees with the audit's warning.

The limit is the one the skeleton guarantees (class, ascendancy, keystones, uniques, jewels), not
the author's readback: cold_dot's author reads ActiveGolemLimit 4 only because they allocated the
ordinary notable Golem Commander, which no skeleton carries.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from build_from_skeleton import best_scoring_subset, tagged_gems, xml_with_gems_disabled  # noqa: E402
from junkroan.search.hypothesis import is_limited_curse  # noqa: E402

FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"


def test_the_best_scoring_subset_is_pobs_pick_and_a_tie_keeps_the_authors_order() -> None:
    """The choice among subsets is a number PoB returns; the code only ranks them."""

    golems = ["Summon Chaos Golem", "Summon Lightning Golem", "Summon Flame Golem", "Summon Stone Golem"]
    scores = {("Summon Chaos Golem", "Summon Lightning Golem", "Summon Flame Golem"): 228_121.0,
              ("Summon Chaos Golem", "Summon Lightning Golem", "Summon Stone Golem"): 212_758.0,
              ("Summon Chaos Golem", "Summon Flame Golem", "Summon Stone Golem"): 228_121.0,
              ("Summon Lightning Golem", "Summon Flame Golem", "Summon Stone Golem"): 203_622.0}
    calls: list[tuple[str, ...]] = []

    def score(subset: tuple[str, ...]) -> float:
        calls.append(subset)
        return scores[subset]

    kept, scored = best_scoring_subset(golems, 3, score)

    assert len(calls) == 4 == len(scored), "one PoB read per subset, no more"
    # two subsets tie at 228,121: the author's order decides, so the earliest gems stay
    assert kept == ["Summon Chaos Golem", "Summon Lightning Golem", "Summon Flame Golem"]
    assert [g for g in golems if g not in kept] == ["Summon Stone Golem"]


def test_a_lone_best_subset_wins_wherever_it_sits_in_the_order() -> None:
    kept, _ = best_scoring_subset(["A", "B", "C"], 2, lambda s: 2.0 if s == ("B", "C") else 1.0)
    assert kept == ["B", "C"]

    kept, scored = best_scoring_subset(["A", "B"], 0, lambda s: 7.0)
    assert kept == [] and scored == {(): 7.0}, "a limit of 0 drops the whole family"


def test_the_curse_family_is_the_audits_own_count_a_mark_included() -> None:
    """PoB's curse slots are shared by hexes and marks (#784: spark-s4, limit 1, Conductivity + Sniper's Mark,
    PoB applied only the Mark), so the family is the audit's count (`is_limited_curse`: curse and (hex or
    mark), not aura). The corpus tags Hexblast -- a damage spell that eats a hex -- and Bane, which carries
    other people's hexes, "hex" without "curse", so the family is never "hex" alone."""

    from build_from_skeleton import LIMITED_GEM_FAMILIES

    curses = next(f[0] for f in LIMITED_GEM_FAMILIES if f[1] == "EnemyCurseLimit")
    names = ["Conductivity", "Sniper's Mark", "Frostbite", "Summon Flame Golem", "Frostbite", "Hexblast", "Bane"]
    assert tagged_gems(names, curses) == ["Conductivity", "Sniper's Mark", "Frostbite"], "a mark is a curse slot too, and a repeat is one gem"
    assert tagged_gems(names, ("curse", "hex")) == ["Conductivity", "Frostbite"], "the tag pair alone misses the marks"
    assert tagged_gems(names, "hex") == ["Conductivity", "Frostbite", "Hexblast", "Bane"], "the corpus tag alone is too wide"
    assert tagged_gems(names, "golem") == ["Summon Flame Golem"]


def test_disabling_a_gem_by_name_writes_the_flag_pob_reads() -> None:
    xml = ('<PathOfBuilding><Skills><Skill slot="Helmet"><Gem nameSpec="Summon Stone Golem" enabled="true"/>'
           '<Gem nameSpec="Summon Flame Golem" enabled="true"/></Skill></Skills></PathOfBuilding>')
    out = xml_with_gems_disabled(xml, ["summon stone golem"])
    assert 'nameSpec="Summon Stone Golem" enabled="false"' in out
    assert 'nameSpec="Summon Flame Golem" enabled="true"' in out
    assert xml_with_gems_disabled(xml, []) is xml


@pytest.mark.skipif(not (PROJECT_ROOT / "var" / "cache" / "pob").is_dir(), reason="PoB runtime not present")
@pytest.mark.pob
def test_cold_dot_keeps_three_golems_and_one_hex_and_pob_picks_which() -> None:
    """The measured case (2026-09-18): cold_dot's author runs four golem gems and two hexes; the
    build our skeleton describes summons 3 golems and applies 1 curse. The rule keeps the subsets
    PoB scores best -- golems 228,121 CombinedDPS against 212,758 / 203,622 for the subsets that
    drop Flame or Chaos, curses Frostbite 188,082 against Elemental Weakness 176,642 -- and the
    build PoB holds is left exactly as it was."""

    from build_from_skeleton import skeleton_from_xml
    from junkroan.optimizer.pipeline import REPORT_KEYS
    from junkroan.pob.session import PobSession, decode_import_code

    xml = decode_import_code((FIXTURES / "cold_dot.pob.txt").read_text(encoding="utf-8").strip())
    before = skeleton_from_xml(xml)
    names = lambda sk: list(sk.main_link) + [g for grp in sk.extra_groups for g in grp.gems]  # noqa: E731
    assert len(tagged_gems(names(before), "golem")) == 4 and len(tagged_gems(names(before), is_limited_curse)) == 2

    lines: list[str] = []
    with PobSession(run_id="test_over_limit_gems") as pob:
        pob.load_xml(xml)
        stats_before = pob.stats(REPORT_KEYS)  # the benchmark's author row is read right after the derivation
        after = skeleton_from_xml(xml, pob=pob, log=lines.append)
        assert pob.stats(REPORT_KEYS) == stats_before, "the author's build is restored, every reported stat of it"

    golems, hexes = tagged_gems(names(after), "golem"), tagged_gems(names(after), is_limited_curse)
    assert len(golems) == 3 and len(hexes) == 1, (golems, hexes)
    assert "Summon Stone Golem" not in golems and hexes == ["Frostbite"]
    assert all(g.gems for g in after.extra_groups), "a group emptied by the drop is gone"

    golem_line = next(l for l in lines if "golem limit of 3" in l)
    curse_line = next(l for l in lines if "curse limit of 1" in l and "golem" not in l)
    assert "kept Summon Chaos Golem, Summon Lightning Golem, Summon Flame Golem" in golem_line, golem_line
    assert "dropped Summon Stone Golem" in golem_line and "4 golem gems" in golem_line
    assert "kept Frostbite" in curse_line and "dropped Elemental Weakness" in curse_line, curse_line

    # the kept subset is the best-scoring one, read back from the line PoB's numbers wrote
    for line in (golem_line, curse_line):
        subsets = {part.rsplit(" ", 1)[0]: float(part.rsplit(" ", 1)[1].replace(",", "")) for part in line.split("subsets: ")[1].rstrip(")").split(" | ")}
        kept = line.split("kept ", 1)[1].split(", dropped")[0].replace(", ", "+")
        assert subsets[kept] == max(subsets.values()), (kept, subsets)
