"""#398: an item trial into a slot that was first emptied scores like the same item equipped.

The slot holds a two-hander with six sockets; Weapon 1 has a socket group (`slot="Weapon 1"`). PoB keeps
`gemInstance.matchesSocket` (the matching-socket quality bonus the calc reads) per gem, set from the item the
slot HOLDS, so on an emptied slot a what-if item used to lose it in fast mode (CalcSetup.lua:1578,
SkillsTab.lua:1215-1237), and a full-mode trial did not look at the item at all. Skipped without the runtime."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from junkroan.pob.session import PobSession, decode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]

pytestmark = [pytest.mark.pob, pytest.mark.skipif(
    not (RUNTIME_ROOT / "lua51.dll").is_file(),
    reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}",
)]

SLOT = "Weapon 1"
BASE = "Sundering Axe"


def _numeric(stats: dict) -> dict:
    return {k: v for k, v in stats.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


@pytest.fixture(scope="module")
def pob():
    with PobSession(run_id="test-trial-emptied-slot", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as session:
        session.load_xml(decode_import_code((FIXTURES / "stormbrand.pob.txt").read_text(encoding="utf-8").strip()))
        yield session


def test_trial_into_an_emptied_slot_reads_as_the_item_equipped(pob: PobSession) -> None:
    mods = pob.list_item_mods(BASE, ilvl=84)
    physical = next(m for m in mods["mods"] if m["type"] == "Prefix" and m["group"] == "LocalPhysicalDamagePercent")
    speed = next(m for m in mods["mods"] if m["type"] == "Suffix" and m["group"] == "LocalIncreasedAttackSpeed")
    crafted = pob.craft_rare(BASE, prefixes=[physical["mod_id"]], suffixes=[speed["mod_id"]], ilvl=84, quality=20, sockets="R-R-R-R-R-R")
    assert crafted["problems"] == []
    raw = crafted["raw"]
    trial = [{"item": {"slot": SLOT, "raw": raw}}]

    pob.equip({"Weapon 2": None})  # a two-hander
    pob.equip({SLOT: raw})
    equipped = _numeric(pob.calc())
    assert equipped["CombinedDPS"] > 0
    keys = sorted(equipped)

    def read(mode: str) -> dict:
        out = pob.trial_stats(trial, keys, mode=mode)[0]
        assert out["ok"], out.get("error")
        return out["stats"]

    # the as-equipped reference: a trial of the item sitting in its slot (a, b, c)
    reference = {mode: read(mode) for mode in ("fast", "full")}
    for mode, stats in reference.items():
        assert stats["CombinedDPS"] == pytest.approx(equipped["CombinedDPS"], rel=1e-9), mode
        assert pob.stats(["CombinedDPS"])["CombinedDPS"] == pytest.approx(equipped["CombinedDPS"], rel=1e-9), f"{mode} trial left the build changed"

    assert pob.equip({SLOT: None})["equipped"] == [{"slot": SLOT, "item_id": 0}]  # the slot is really empty
    for mode in ("fast", "full"):
        emptied = read(mode)
        assert emptied.get("HitChance") == reference[mode].get("HitChance"), mode
        moved = {k: (reference[mode][k], emptied.get(k)) for k in reference[mode]
                 if emptied.get(k) is None or abs(emptied[k] - reference[mode][k]) > 1e-9 * max(1.0, abs(reference[mode][k]))}
        assert not moved, f"{mode} trial on the emptied slot differs from the item equipped: {moved}"

    pob.equip({SLOT: raw})
    assert _numeric(pob.calc())["CombinedDPS"] == pytest.approx(equipped["CombinedDPS"], rel=1e-9)
