"""PoB-free tests of the forced classes of the trace counter (#510)."""

from junkroan.optimizer.trace import TRACE

KIK = "Rarity: UNIQUE\nKikazaru\nTopaz Ring\nItem Level: 83\n"
OTHER = "Rarity: UNIQUE\nOther Ring\nTopaz Ring\nItem Level: 83\n"
HELM = "Rarity: Rare\nDoom Crown\nHubris Circlet\nItem Level: 84\n+1 to Level of all Fire Spell Skill Gems\n"
HELM2 = "Rarity: Rare\nDoom Crown\nHubris Circlet\nItem Level: 84\n+90 to maximum Life\n"
HELM3 = "Rarity: Rare\nDoom Crown\nIron Hat\nItem Level: 84\n+1 to Level of all Fire Spell Skill Gems\n"
FORCED = {
    "uniques": {"Ring 1": "Kikazaru"},
    "bases": {"Helmet": "Hubris Circlet"},
    "nodes": [7, 8],
    "affixes": {"Helmet": ["+2 to Level of all Fire Spell Skill Gems"]},
}


def item(raw, slot):
    return {"item": {"slot": slot, "raw": raw}}


TRIALS = [
    (item(KIK, "Ring 1"), {"forced:kept"}),
    (item(OTHER, "Ring 1"), {"forced-missing:unique:Ring 1"}),
    (item(OTHER, "Ring 2"), {"forced:kept"}),
    (item(HELM, "Helmet"), {"forced:kept"}),
    (item(HELM2, "Helmet"), {"forced-missing:affix:Helmet"}),
    (item(HELM3, "Helmet"), {"forced-missing:base:Helmet"}),
    ({"remove": [1]}, {"forced:kept"}),
    ({"remove": [1, 7]}, {"forced-missing:node:7"}),
    ({"add": [7]}, {"forced:kept"}),
    ({"add": [9], "mastery": {"8": 3}}, {"forced-missing:node:8"}),
    ({"add": [9], "mastery": {"5": 3}}, {"forced:kept"}),
]


def _forced_only(moves):
    return {c: v for c, v in moves.get("(unattributed)", {}).items() if c.startswith("forced")}


def test_forced_classes_generated_and_evaluated() -> None:
    for trial, want in TRIALS:
        TRACE.reset()
        TRACE.set_forced(FORCED)
        TRACE.count_candidates([trial])
        TRACE.count_trial(trial)
        got = _forced_only(TRACE.considered())
        assert got == {c: {"generated": 1, "evaluated": 1} for c in want}, (trial, got)
    TRACE.reset()


def test_without_forced_nothing_changes() -> None:
    def run(forced):
        TRACE.reset()
        TRACE.set_forced(forced)
        for trial, _ in TRIALS:
            TRACE.count_candidates([trial])
            TRACE.count_trial(trial)
        return TRACE.considered()

    base = run(None)
    assert not any(c.startswith("forced") for c in base["(unattributed)"])
    assert run({}) == base
    with_forced = run(FORCED)
    stripped = {m: {c: v for c, v in cl.items() if not c.startswith("forced")} for m, cl in with_forced.items()}
    assert stripped == base
    TRACE.reset()
