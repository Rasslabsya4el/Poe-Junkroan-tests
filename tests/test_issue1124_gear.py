"""#1124 unit 3/5: the gear rejection lets a marked red line through, PoB-free.

The four reject sites (gear_filler forced + candidate, the loop's weapon-base move, wishlist `_raw`) read the item's
`unsupported_lines` through `red_line_gate.red_lines_blocking`. A line with a record that has a non-empty lane no
longer drops the item; no record, a zero record or an illegal-mod `problems` entry still do. No marks file = the
old behaviour.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from junkroan.optimizer.gear_filler import GearFiller
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.red_line_gate import red_lines_blocking
from junkroan.optimizer.red_line_marks import ENV_PATH, RedLineMarks, load_marks
from junkroan.optimizer.wishlist_gear import WishlistGear

import test_weapon_base_move as wbm

FIXTURE = Path(__file__).parent / "fixtures" / "red_line_marks_fixture.json"
BOTH = "10% chance to Recover 10% of Mana when you use a Skill"  # marked on boss and optimistic
OPTIMISTIC_ONLY = "10% chance to create a Smoke Cloud on Kill"  # marked on the optimistic lane only
ZERO = "Can Allocate Passives from the Duelist's starting point"  # a record with both lanes empty
UNKNOWN = "Some Line With No Record At All"


@pytest.fixture(autouse=True)
def _marks(monkeypatch):
    monkeypatch.setenv(ENV_PATH, str(FIXTURE))


@pytest.fixture
def no_marks(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_PATH, str(tmp_path / "missing.json"))


# -- the shared helper -----------------------------------------------------------------------------------------------


def test_helper_keeps_only_lines_without_a_usable_mark():
    lines = [BOTH, OPTIMISTIC_ONLY, ZERO, UNKNOWN]
    assert red_lines_blocking(lines) == [ZERO, UNKNOWN]  # no lane: marked on either lane is allowed
    assert red_lines_blocking(lines, lane="boss") == [OPTIMISTIC_ONLY, ZERO, UNKNOWN]
    assert red_lines_blocking(lines, lane="optimistic") == [ZERO, UNKNOWN]
    assert red_lines_blocking([]) == []


def test_helper_with_no_marks_returns_the_lines_unchanged(no_marks):
    lines = [BOTH, ZERO, UNKNOWN]
    assert red_lines_blocking(lines) == lines
    assert red_lines_blocking(lines, lane="boss") == lines
    assert red_lines_blocking(lines, marks=load_marks()) == lines


def test_helper_takes_explicit_marks_over_the_env():
    assert red_lines_blocking([BOTH], marks=RedLineMarks(())) == [BOTH]


# -- gear_filler -----------------------------------------------------------------------------------------------------


MOD = {"mod_id": "ModA", "type": "Prefix", "group": "GroupA", "level": 1, "lines": ["+10 to Strength"]}


class _FillerPob:
    def __init__(self, *, unsupported=(), problems=()):
        self.unsupported = list(unsupported)
        self.problems = list(problems)

    def list_item_mods(self, base):
        return {"mods": [dict(MOD)]}

    def craft_rare(self, base, **_kw):
        return {"raw": "RAW", "problems": list(self.problems), "unsupported_lines": list(self.unsupported)}

    def trial_stats(self, trials, keys, mode="fast"):
        return [{"ok": True, "stats": {key: 200.0 for key in keys}} for _ in trials]

    def stats(self, keys):
        return {key: 100.0 for key in keys}

    def equip(self, items):
        pass


def _filler(**kw):
    rails = SimpleNamespace(gear=SimpleNamespace(item_level=84, quality=20, max_explicit_mods=1, max_prefixes=3, max_suffixes=3))
    return GearFiller(_FillerPob(**kw), Objective(maximize="Dmg"), rails, log=lambda _m: None)


@pytest.mark.parametrize("line,kept", [(BOTH, True), (OPTIMISTIC_ONLY, True), (ZERO, False), (UNKNOWN, False)])
def test_filler_candidate(line, kept):
    result = _filler(unsupported=[line]).fill_slot("Weapon 1", "Base")
    assert bool(result.raw) is kept


def test_filler_candidate_problems_drop_even_if_marked():
    result = _filler(unsupported=[BOTH], problems=["Prefix ModA: unknown mod for this base"]).fill_slot("Weapon 1", "Base")
    assert result.raw == ""


def test_filler_candidate_no_marks_drops_a_marked_line(no_marks):
    assert _filler(unsupported=[BOTH]).fill_slot("Weapon 1", "Base").raw == ""


@pytest.mark.parametrize("line,raises", [(BOTH, False), (ZERO, True), (UNKNOWN, True)])
def test_filler_forced(line, raises):
    filler = _filler(unsupported=[line])
    if raises:
        with pytest.raises(ValueError):
            filler.fill_slot("Weapon 1", "Base", forced=["+10 to Strength"])
    else:
        assert filler.fill_slot("Weapon 1", "Base", forced=["+10 to Strength"]).raw == "RAW"


def test_filler_forced_problems_raise_even_if_marked():
    with pytest.raises(ValueError):
        _filler(unsupported=[BOTH], problems=["duplicate mod group"]).fill_slot("Weapon 1", "Base", forced=["+10 to Strength"])


def test_filler_forced_no_marks_raises(no_marks):
    with pytest.raises(ValueError):
        _filler(unsupported=[BOTH]).fill_slot("Weapon 1", "Base", forced=["+10 to Strength"])


# -- the loop's weapon-base move --------------------------------------------------------------------------------------


class _WeaponPob(wbm._Pob):
    def __init__(self, *, unsupported=(), problems=()):
        super().__init__()
        self.unsupported = list(unsupported)
        self.problems = list(problems)

    def craft_rare(self, base, **kw):
        out = super().craft_rare(base, **kw)
        if base == "High Base":
            out = {**out, "unsupported_lines": list(self.unsupported), "problems": list(self.problems)}
        return out


def _weapon_move(monkeypatch, pob):
    pipeline, _pob, loot, skeleton, result = wbm._setup(monkeypatch, pob=pob)
    kept, note = pipeline.weapon_base_move(
        result, skeleton, loot, "Weapon 1", current_score=Objective(maximize="CombinedDPS").score({"CombinedDPS": 100.0}),
        min_gain=0.005, move_state=wbm._state(pob, loot, skeleton), snapshot_fresh=True, t0=0.0,
        judge=wbm._judge(pipeline, pob, result, loot, skeleton),
        restore_move=lambda state, **kw: wbm._restore(pob, loot, skeleton, state, **kw), last_rejected={},
    )
    return kept, note, result


def test_weapon_base_marked_line_is_trialled(monkeypatch):
    kept, note, result = _weapon_move(monkeypatch, _WeaponPob(unsupported=[BOTH]))
    assert kept and note == "Weapon 1 base Low Base -> High Base"
    assert result.weapon_base_skipped == {"One Handed Sword": 1}  # only the Illegal Base, as with no unsupported line


@pytest.mark.parametrize("line", [ZERO, UNKNOWN])
def test_weapon_base_unmarked_line_is_skipped(monkeypatch, line):
    kept, _note, result = _weapon_move(monkeypatch, _WeaponPob(unsupported=[line]))
    assert not kept
    assert result.weapon_base_skipped == {"One Handed Sword": 2}


def test_weapon_base_problems_skip_even_if_marked(monkeypatch):
    kept, _note, result = _weapon_move(monkeypatch, _WeaponPob(unsupported=[BOTH], problems=["duplicate mod group"]))
    assert not kept
    assert result.weapon_base_skipped == {"One Handed Sword": 2}


def test_weapon_base_no_marks_skips_a_marked_line(monkeypatch, no_marks):
    kept, _note, result = _weapon_move(monkeypatch, _WeaponPob(unsupported=[BOTH]))
    assert not kept
    assert result.weapon_base_skipped == {"One Handed Sword": 2}


# -- wishlist `_raw` -------------------------------------------------------------------------------------------------


def _wishlist_raw(*, unsupported=(), problems=()):
    pob = SimpleNamespace(craft_rare=lambda base, **_kw: {"raw": "RAW", "problems": list(problems), "unsupported_lines": list(unsupported)})
    gear = object.__new__(WishlistGear)
    gear.pob = pob
    gear.rails = SimpleNamespace(gear=SimpleNamespace(quality=20))
    gear._raw_cache = {}
    gear.anoint = None
    return gear._raw("Base", 84, [], None, None)


@pytest.mark.parametrize("line,raw", [(BOTH, "RAW"), (OPTIMISTIC_ONLY, "RAW"), (ZERO, None), (UNKNOWN, None)])
def test_wishlist_raw(line, raw):
    assert _wishlist_raw(unsupported=[line]) == raw


def test_wishlist_raw_problems_drop_even_if_marked():
    assert _wishlist_raw(unsupported=[BOTH], problems=["unknown mod for this base"]) is None


def test_wishlist_raw_no_marks_drops_a_marked_line(no_marks):
    assert _wishlist_raw(unsupported=[BOTH]) is None


def test_wishlist_raw_clean_craft_is_unchanged(no_marks):
    assert _wishlist_raw() == "RAW"
