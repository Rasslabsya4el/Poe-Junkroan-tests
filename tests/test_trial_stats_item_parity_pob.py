"""#419: `trial_stats` fast mode builds its trial item the way a real `equip` does.

Equip goes through `CreateDisplayItemFromRaw(raw, true)`: the slot's anoint / enchant / eldritch implicits are
copied onto the new item and its quality is normalised. Fast mode does the same item-building part without
touching UI state; the tests assert fast == equip to the digit for every stat read (`KEYS`) on

(a) a rare Amulet without anoint tried while the equipped amulet carries an anoint;
(b) a non-unique rare Body Armour at Quality 0 tried into Body Armour;

plus: a trial batch leaves the build's own stats unchanged, and the timing of 50 fast item trials is printed
(the "before" number is taken on the #419 unit 1 Lua; see the issue).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from junkroan.pob.session import PobSession, decode_import_code
from junkroan.report_format import human_duration

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]

pytestmark = [pytest.mark.pob, pytest.mark.skipif(
    not (RUNTIME_ROOT / "lua51.dll").is_file(),
    reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}",
)]

KEYS = ("CombinedDPS", "Life", "TotalEHP")
OBJECTIVE = "CombinedDPS"
ANOINT = "Heart of Thunder"  # 30% increased Lightning Damage, Damage Penetrates 6% Lightning Resistance


@pytest.fixture()
def pob():
    with PobSession(run_id="test-trial-parity", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as session:
        session.load_xml(decode_import_code((FIXTURES / "stormbrand.pob.txt").read_text(encoding="utf-8").strip()))
        yield session


def _pick(mods: dict, needle: str) -> str:
    for m in mods["mods"]:
        if m["type"] in ("Prefix", "Suffix") and any(needle in line for line in m["lines"]):
            return m["mod_id"]
    raise AssertionError(f"no mod with {needle!r}")


def _with_anoint(raw: str, notable: str) -> str:
    """The raw item with an `{enchant}Allocates <notable>` line counted into its Implicits."""

    out: list[str] = []
    for line in raw.splitlines():
        if line.startswith("Implicits:"):
            out += [f"Implicits: {int(line.split(':')[1]) + 1}", f"{{enchant}}Allocates {notable}"]
        else:
            out.append(line)
    return chr(10).join(out)


def _fast_equip(pob: PobSession, slot: str, raw: str) -> dict[str, dict]:
    fast = pob.trial_stats([{"item": {"slot": slot, "raw": raw}}], KEYS, mode="fast")[0]
    assert fast["ok"], fast
    pob.equip({slot: raw})
    return {"fast": fast["stats"], "equip": pob.stats(KEYS)}


def _print(case: str, row: dict[str, dict]) -> None:
    for mode in ("fast", "equip"):
        print(f"PARITY {case} {mode:5s} {OBJECTIVE}={row[mode][OBJECTIVE]!r} Life={row[mode]['Life']!r} TotalEHP={row[mode]['TotalEHP']!r}")


def _amulet_raws(pob: PobSession) -> tuple[str, str]:
    mods = pob.list_item_mods("Onyx Amulet", ilvl=84)
    life = _pick(mods, "maximum Life")
    anointed = pob.craft_rare("Onyx Amulet", prefixes=[life], ilvl=84, name="Anointed Probe")
    assert anointed["problems"] == [], anointed
    plain = pob.craft_rare("Onyx Amulet", prefixes=[life], suffixes=[_pick(mods, "to all Attributes")], ilvl=84, name="Plain Probe")
    assert plain["problems"] == [], plain
    return _with_anoint(anointed["raw"], ANOINT), plain["raw"]


def _body_raw(pob: PobSession) -> str:
    mods = pob.list_item_mods("Astral Plate", ilvl=84)
    body = pob.craft_rare("Astral Plate", prefixes=[_pick(mods, "maximum Life")], ilvl=84, quality=0, sockets="B-B-B-B-B", name="Quality Zero Probe")
    assert body["problems"] == [], body
    return body["raw"]


def test_item_trial_parity_amulet_with_anointed_equipped(pob: PobSession) -> None:
    anointed_raw, plain_raw = _amulet_raws(pob)
    print(f"PARITY amulet baseline(original) {OBJECTIVE}={pob.stats(KEYS)[OBJECTIVE]!r}")
    pob.equip({"Amulet": anointed_raw})
    row = _fast_equip(pob, "Amulet", plain_raw)
    _print("amulet", row)
    assert row["fast"] == row["equip"]
    assert row["equip"][OBJECTIVE] == pytest.approx(951539.50031712, rel=1e-9)
    assert row["equip"]["Life"] == 4345


def test_item_trial_parity_body_armour_quality_0(pob: PobSession) -> None:
    raw = _body_raw(pob)
    print(f"PARITY body baseline {OBJECTIVE}={pob.stats(KEYS)[OBJECTIVE]!r}")
    row = _fast_equip(pob, "Body Armour", raw)
    _print("body", row)
    assert row["fast"] == row["equip"]
    assert row["equip"][OBJECTIVE] == pytest.approx(870110.96870816, rel=1e-9)
    assert row["equip"]["Life"] == 4269
    assert row["equip"]["TotalEHP"] == pytest.approx(9202.32, abs=0.01)


def test_item_trial_batch_leaves_the_build_unchanged(pob: PobSession) -> None:
    baseline = pob.stats(KEYS)
    assert baseline[OBJECTIVE] == pytest.approx(898678.24762797, rel=1e-12)
    anointed_raw, plain_raw = _amulet_raws(pob)
    body_raw = _body_raw(pob)
    pob.equip({"Amulet": anointed_raw})
    before = pob.stats(KEYS)
    trials = [{"item": {"slot": "Amulet", "raw": plain_raw}}, {"item": {"slot": "Body Armour", "raw": body_raw}}] * 3
    results = pob.trial_stats(trials, KEYS, mode="fast")
    assert all(r["ok"] for r in results), results
    assert pob.stats(KEYS) == before
    # Repeating a trial gives the same numbers: the slot's anoint is not consumed or altered by a trial.
    again = pob.trial_stats(trials[:2], KEYS, mode="fast")
    assert [r["stats"] for r in again] == [r["stats"] for r in results[:2]]
    assert pob.stats(KEYS) == before


def test_full_mode_equips_the_item_of_a_trial_like_fast_mode(pob: PobSession) -> None:
    """Since #398 a full-mode item trial in the headless worker is a real equip (equip, read, unequip), so full and
    fast mode agree on the trial item's stats to the digit, and both differ from the baseline."""

    mods = pob.list_item_mods("Astral Plate", ilvl=84)
    better = pob.craft_rare("Astral Plate", prefixes=[_pick(mods, "maximum Life")], ilvl=84, quality=20, sockets="B-B-B-B-B", name="Life Probe")
    before = pob.stats(KEYS)
    fast = pob.trial_stats([{"item": {"slot": "Body Armour", "raw": better["raw"]}}], KEYS, mode="fast")[0]["stats"]
    full = pob.trial_stats([{"item": {"slot": "Body Armour", "raw": better["raw"]}}], KEYS, mode="full")[0]["stats"]
    print(f"PARITY plainly-better-body Life: baseline={before['Life']!r} fast={fast['Life']!r} full={full['Life']!r}")
    print(f"PARITY plainly-better-body {OBJECTIVE}: baseline={before[OBJECTIVE]!r} fast={fast[OBJECTIVE]!r} full={full[OBJECTIVE]!r}")
    assert full == fast
    assert full != before
    assert pob.stats(KEYS) == before  # the full-mode equip was undone


def test_timing_of_50_fast_item_trials(pob: PobSession) -> None:
    """Reported, not asserted: the bar (after <= before x 1.10) is judged against the unit 1 Lua by hand."""

    anointed_raw, plain_raw = _amulet_raws(pob)
    body_raw = _body_raw(pob)
    pob.equip({"Amulet": anointed_raw})
    trials = [{"item": {"slot": "Amulet", "raw": plain_raw}}, {"item": {"slot": "Body Armour", "raw": body_raw}}] * 25
    pob.trial_stats(trials[:2], KEYS, mode="fast")  # warm up
    times = []
    for _ in range(7):
        t0 = time.perf_counter()
        results = pob.trial_stats(trials, KEYS, mode="fast")
        times.append(time.perf_counter() - t0)
        assert len(results) == 50 and all(r["ok"] for r in results)
    print(f"TIMING 50 fast item trials: best {human_duration(min(times))} ({min(times):.4f} s raw), runs {[round(t, 3) for t in times]}")
