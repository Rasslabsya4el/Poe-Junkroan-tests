"""#1119 unit 2: the day-1 red-line grouping rule (scripts/day1_groups.py).

The rule is code: first matching family in GROUPS order wins; `other` is last.
Expected groups below were read off the line text by hand against the family
order, not produced by the rule.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from day1_groups import GROUPS, group_of  # noqa: E402

CORPUS = ROOT / "src" / "junkroan" / "pob" / "corpus_data" / "uniques.json"

# (line, expected group): real lines from uniques.json unsupported_lines, copied verbatim.
PINNED = [
    ("Cannot have Minions other than Raised Spectres", "cannot_immune"),
    ("Totems cannot be Stunned", "cannot_immune"),
    ("Nearby Enemies cannot gain Power, Frenzy or Endurance Charges", "cannot_immune"),
    ("Critical Strikes do not inherently inflict non-Damaging Ailments", "cannot_immune"),
    ("Raised Zombies Cover Enemies in Ash on Hit", "minion"),
    ("Summon 2 additional Skeletons with Summon Skeletons", "minion"),
    ("10% chance to gain a Power Charge on Kill", "on_kill"),
    ("Enemies you kill are Shocked", "on_kill"),
    ("Kills grant an additional Vaal Soul if you have Rampaged Recently", "on_kill"),
    ("Recover 88% of Life on use", "trigger"),
    ("Grants Last Breath when you Use a Skill during Effect, for 525% of Mana Cost", "trigger"),
    ("Recover 39% of Mana and Energy Shield when you Focus", "recovery"),
    ("75% of Suppressed Spell Damage taken Recouped as Energy Shield", "recovery"),
    ("Chill Enemy for 1 second when Hit, reducing their Action Speed by 30%", "on_hit"),
    ("20% chance to Freeze Enemies for 1 second when they Hit you", "on_hit"),
    ("Reflects 10 Cold Damage to Melee Attackers", "reflect"),
    ("Hexes applied by Socketed Curse Skills are Reflected back to you", "reflect"),
    ("10% chance to Steal Power, Frenzy, and Endurance Charges on Hit", "steal"),
    ("Sacrifice 5% of Life to gain that much Energy Shield when you Cast a Spell", "self_cost"),
    ("Removes 13% of Life when Used", "self_cost"),
    ("Lose all Frenzy Charges on reaching Maximum Frenzy Charges to make the next Bow Attack you perform fire that many additional Arrows", "charges"),
    ("Gain a random Blood Shrine buff every 10 seconds", "buff"),
    ("Passives granting Cold Resistance or all Elemental Resistances in Radius", "jewel_conditional"),
    ("0% to Lightning Resistance", "defence"),
    ("35% chance for Elemental Resistances to count as being 90% against Enemy Hits", "defence"),
    ("+50% chance to be Shocked", "ailment"),
    ("Corrupted", "item_text"),
    ("Requires Level 55, 52 Dex, 52 Int", "item_text"),
    ("Maximum Quality is 200%", "item_text"),
    ("Projectiles Return to you", "skill_specific"),
    ("Can Consume 4 Uncorrupted Support Gems", "skill_specific"),
    ("45% reduced Quantity of Fish Caught", "plain_stat"),
    ("You can catch Exotic Fish", "other"),
    ("Unaffected by Burning Ground", "cannot_immune"),
    ("Consecrated Ground created by this Flask has Tripled Radius", "ground"),
    ("Increases and Reductions to Effect of Flasks applied to you\nalso applies to Effect of Arcane Surge on you at 225% of their value", "flask"),
    ("15% of Fire and Cold Damage taken as Lightning Damage while\naffected by Purity of Lightning", "conversion"),
]


def _unsupported_lines() -> list[str]:
    data = json.loads(CORPUS.read_text(encoding="utf-8"))
    return sorted({line for rec in data["records"] for line in rec.get("unsupported_lines", [])})


def test_groups_list_is_ordered_and_other_is_last():
    assert len(GROUPS) == len(set(GROUPS))
    assert GROUPS[-1] == "other"


def test_pinned_real_lines_get_their_expected_group():
    assert len(PINNED) >= 20
    assert {g for _, g in PINNED} == set(GROUPS)
    corpus = set(_unsupported_lines())
    not_in_corpus = [line for line, _ in PINNED if line not in corpus]
    assert not_in_corpus == [], not_in_corpus
    wrong = [(line, want, group_of(line)) for line, want in PINNED if group_of(line) != want]
    assert wrong == [], wrong


def test_every_line_of_a_200_line_sample_gets_exactly_one_group():
    lines = _unsupported_lines()
    sample = random.Random(1119).sample(lines, 200)
    assert len(sample) == 200
    counts: dict[str, int] = {g: 0 for g in GROUPS}
    for line in sample:
        group = group_of(line)
        assert isinstance(group, str)
        assert group in GROUPS, (line, group)
        counts[group] += 1
    assert sum(counts.values()) == 200
    print("sample group counts:", counts)


def test_every_distinct_unsupported_line_gets_a_group():
    lines = _unsupported_lines()
    assert len(lines) > 900
    assert all(group_of(line) in GROUPS for line in lines)
