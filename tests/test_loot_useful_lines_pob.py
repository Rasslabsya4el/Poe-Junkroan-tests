"""#437 row 5: the `g-useful-n` rule through the real `LootGear.fill_slot` on a real PoB build.

Fixture: smoke `stormbrand` (`tests/fixtures/tuadh_329`), put in a state where its floors are missed: every rare
but the two weapons is taken off (Life 4156 -> 2532, Fire/Cold -33, Lightning -18), and Ring 2 pushes Lightning
over its cap (+47 from a Lightning Resistance affix and a `{crafted}` +50). The objective is
`maximize=CombinedDPS` with the floors Life >= 0.97 x the original Life and Fire / Cold / Lightning Resistance
at their max (75).

The one candidate for `Ring 1` is a constructed ring (`craft_rare` on an Iron Ring): IncreasedLife6 (a prefix),
FireResist6 and ColdResist6 (under cap), LightningResist6 (over cap in this state), and the two plain explicit
lines a loot rare never rolls but a PoB item text can hold: `+30 to Dexterity` (an attribute the spell build has
no use for) and `-20 to maximum Life`. Six lines, N_slot 3. Everything but `random_rares` is the real
`PobSession`: `_OneCandidate` hands `fill_slot` that one ring in place of the 200 rolled rares and passes every
other call through. `bench=False`: no bench craft competes as a line, so the ring's three useful lines are
exactly what stays.

The measurement (every number read to the digit, no tolerance):

(a) PoB itself says the Lightning and the Dexterity lines are neutral and `-20 to maximum Life` is a drawback
    (hand-built rings without that line: the same CombinedDPS, Life, three resistances);
(b) the delivered ring holds the Life, Fire and Cold lines and `-20 to maximum Life`; no Lightning, no Dexterity;
(c) `trial_stats` mode fast of the delivered ring equals the full `equip` + `stats` on CombinedDPS, Life, TotalEHP;
(d) `export_xml` -> `load_xml` round-trips the ring and those three stats.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from junkroan.optimizer.loot_gear import LootGear
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.useful_lines import item_lines
from junkroan.pob.session import PobSession, decode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]

pytestmark = [pytest.mark.pob, pytest.mark.skipif(
    not (RUNTIME_ROOT / "lua51.dll").is_file(),
    reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}",
)]

BASE = "Iron Ring"
SLOT = "Ring 1"
TAKEN_OFF = ("Amulet", "Helmet", "Body Armour", "Gloves", "Boots", "Belt", "Ring 1", "Ring 2")
KEYS3 = ("CombinedDPS", "Life", "TotalEHP")
KEYS = ("CombinedDPS", "Life", "TotalEHP", "FireResist", "ColdResist", "LightningResist", "Str", "Dex", "Int")
DEX_LINE = "+30 to Dexterity"
DRAWBACK = "-20 to maximum Life"
LIFE = {"mod_id": "IncreasedLife6", "range": 0.5}
FIRE = {"mod_id": "FireResist6", "range": 0.5}
COLD = {"mod_id": "ColdResist6", "range": 0.5}
LIGHTNING = {"mod_id": "LightningResist6", "range": 0.5}


class _OneCandidate:
    """The real PobSession, except `random_rares` answers with the one constructed candidate."""

    def __init__(self, pob: PobSession, candidate: dict) -> None:
        self._pob = pob
        self._candidate = candidate

    def random_rares(self, *_args, **_kwargs):
        return [self._candidate]

    def __getattr__(self, name: str):
        return getattr(self._pob, name)


def _ring(pob: PobSession, prefixes, suffixes, plain: tuple[str, ...]) -> str:
    crafted = pob.craft_rare(BASE, prefixes=prefixes, suffixes=suffixes, ilvl=84, quality=20)
    assert crafted["problems"] == [], crafted
    return crafted["raw"].rstrip("\n") + "".join(f"\n{line}" for line in plain) + ("\n" if plain else "")


def _trial(pob: PobSession, raw: str, keys=KEYS) -> dict:
    out = pob.trial_stats([{"item": {"slot": SLOT, "raw": raw}}], keys, mode="fast")[0]
    assert out["ok"], out
    return out["stats"]


def _worn_item(xml: str, slot: str) -> str:
    root = ET.fromstring(xml)
    item_id = next(s.get("itemId") for s in root.iter("Slot") if s.get("name") == slot and s.get("itemId") != "0")
    return next((i.text or "").strip() for i in root.iter("Item") if i.get("id") == item_id)


@pytest.fixture(scope="module")
def rig():
    with PobSession(run_id="test-loot-useful-lines", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as pob:
        pob.load_xml(decode_import_code((FIXTURES / "stormbrand.pob.txt").read_text(encoding="utf-8").strip()))
        original = pob.stats(KEYS + ("FireResistMax", "ColdResistMax", "LightningResistMax"))
        print(f"POB5 original: {original}")
        pob.equip({slot: None for slot in TAKEN_OFF})
        over = pob.craft_rare(BASE, suffixes=[{"mod_id": "LightningResist8", "range": 0.5}], extra_lines=["{crafted}+50% to Lightning Resistance"], ilvl=84, quality=20)
        assert over["problems"] == [], over
        pob.equip({"Ring 2": over["raw"]})
        state = pob.stats(KEYS)
        print(f"POB5 state (rares but the weapons off, Ring 2 = Lightning source): {state}")
        objective = Objective(
            maximize="CombinedDPS",
            floors={
                "Life": 0.97 * original["Life"],
                "FireResist": original["FireResistMax"],
                "ColdResist": original["ColdResistMax"],
                "LightningResist": original["LightningResistMax"],
            },
        )
        raw = _ring(pob, [LIFE], [FIRE, COLD, LIGHTNING], (DEX_LINE, DRAWBACK))
        print(f"POB5 candidate:\n{raw}")
        yield pob, objective, original, state, raw


def test_the_state_misses_life_and_two_resistances_and_the_lines_read_as_designed(rig) -> None:
    pob, objective, original, state, raw = rig
    assert state["Life"] < objective.floors["Life"]
    assert state["FireResist"] < 75 and state["ColdResist"] < 75
    assert state["LightningResist"] >= 75  # Ring 2 pushed Lightning to its cap
    assert [(ln.kind, ln.text) for ln in item_lines(raw)] == [
        ("prefix", "IncreasedLife6"), ("suffix", "FireResist6"), ("suffix", "ColdResist6"), ("suffix", "LightningResist6"),
        ("explicit", DEX_LINE), ("explicit", DRAWBACK),
    ]

    full = _trial(pob, raw)
    print(f"POB5 candidate worn: {full}")
    scored = objective.score(full)
    without = {
        "Lightning": _ring(pob, [LIFE], [FIRE, COLD], (DEX_LINE, DRAWBACK)),
        "Dexterity": _ring(pob, [LIFE], [FIRE, COLD, LIGHTNING], (DRAWBACK,)),
        "drawback": _ring(pob, [LIFE], [FIRE, COLD, LIGHTNING], (DEX_LINE,)),
    }
    for name, text in without.items():
        stats = _trial(pob, text)
        print(f"POB5 without the {name} line: {stats} -> score {objective.score(stats)} (with: {scored})")
    for name in ("Lightning", "Dexterity"):  # neutral: PoB's numbers do not move, so the Score does not
        stats = _trial(pob, without[name])
        assert {k: stats[k] for k in KEYS if k not in ("Dex", "Str", "Int")} == {k: full[k] for k in KEYS if k not in ("Dex", "Str", "Int")}
        assert objective.score(stats) == scored
    drawback = _trial(pob, without["drawback"])
    assert drawback["Life"] > full["Life"] and objective.score(drawback) > scored  # -20 to maximum Life reads negative


def test_fill_slot_delivers_three_useful_lines_and_the_drawback(rig) -> None:
    pob, objective, original, state, raw = rig
    logs: list[str] = []
    loot = LootGear(_OneCandidate(pob, {"raw": raw, "mod_ids": [m["mod_id"] for m in (LIFE, FIRE, COLD, LIGHTNING)]}), objective, Rails.load(), log=logs.append)

    result = loot.fill_slot(SLOT, BASE, n=1, seed=1, bench=False)
    print("POB5 log:\n" + "\n".join(logs))
    print(f"POB5 delivered:\n{result.raw}")

    assert [(ln.kind, ln.text) for ln in item_lines(result.raw)] == [
        ("prefix", "IncreasedLife6"), ("suffix", "FireResist6"), ("suffix", "ColdResist6"), ("explicit", DRAWBACK),
    ]
    assert result.lines_total == 6 and result.lines_counted == 3
    assert sorted(result.dropped) == sorted(["LightningResist6", DEX_LINE])
    assert result.drawbacks == [DRAWBACK]
    assert "Lightning" not in result.raw and "Dexterity" not in result.raw
    assert "maximum Life" in result.raw and "Fire Resistance" in result.raw and "Cold Resistance" in result.raw
    assert loot.current_raw[SLOT] == result.raw


def test_the_delivered_ring_trial_equals_the_full_equip_and_survives_export_load(rig) -> None:
    pob, objective, original, state, raw = rig
    delivered = LootGear(_OneCandidate(pob, {"raw": raw, "mod_ids": []}), objective, Rails.load()).fill_slot(SLOT, BASE, n=1, seed=1, bench=False).raw

    fast = _trial(pob, delivered, KEYS3)
    pob.equip({SLOT: delivered})
    full = pob.stats(KEYS3)
    print(f"POB5 fast trial {fast}\nPOB5 full equip {full}")
    assert fast == full

    xml = pob.export_xml()
    worn = _worn_item(xml, SLOT)
    pob.load_xml(xml)
    loaded = pob.stats(KEYS3)
    print(f"POB5 after export -> load {loaded}")
    assert loaded == full
    assert [(ln.kind, ln.text) for ln in item_lines(_worn_item(pob.export_xml(), SLOT))] == [(ln.kind, ln.text) for ln in item_lines(worn)]
    assert _worn_item(pob.export_xml(), SLOT) == worn
