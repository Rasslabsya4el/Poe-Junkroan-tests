"""#1154: a base the loadout excludes is never offered to a slot (search-space rail, kind A; no PoB).

The rails key `gear.bases_excluded_by_loadout` maps a loadout to the base names it never offers: day1 and t16 list
"Prismatic Ring", endgame lists nothing. Every site that offers a base reads it; the trace class
`base-excluded-by-loadout` stays at 0 generated / 0 evaluated while other ring bases are evaluated.
"""

from __future__ import annotations

import json
from pathlib import Path

from junkroan.optimizer.item_bases import bases_of_type, without_excluded
from junkroan.optimizer.loot_gear import LootGear
from junkroan.optimizer.rails import DEFAULT_RAILS_PATH, Rails
from junkroan.optimizer.trace import TRACE
from junkroan.optimizer.wishlist_gear import WishlistGear
from junkroan.search.generator import ARMOUR_SLOT_TYPES, SkeletonGenerator, candidate_bases
from junkroan.optimizer.objective import Objective
from junkroan.search.skeleton import Skeleton

PRISMATIC = "Prismatic Ring"
OTHER_RINGS = {"Amethyst Ring", "Two-Stone Ring (Fire/Cold)", "Ruby Ring"}


def _rails_with(tmp_path: Path, table: dict[str, list[str]], loadout: str) -> Rails:
    raw = json.loads(DEFAULT_RAILS_PATH.read_text(encoding="utf-8"))
    raw["gear"]["bases_excluded_by_loadout"] = table
    path = tmp_path / "rails.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Rails.load(path, loadout=loadout)


class _Pob:
    """Rolls one trivial rare per base; remembers every trial sent (what reaches the PoB boundary)."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def equip(self, mapping) -> None:
        pass

    def list_item_mods(self, base, ilvl=None, pool="explicit") -> dict:
        return {"mods": [{"mod_id": "life1", "lines": ["+1 life"]}]}

    def random_rares(self, base, *, n, ilvl=None, quality=None, seed=None, forced=None) -> list[dict]:
        return [{"raw": f"Rarity: Rare\nName {i}\n{base}\n+1 life"} for i in range(n)]

    def trial_stats(self, trials, keys, mode="fast") -> list[dict]:
        for t in trials:
            self.sent.append((t["item"]["slot"], t["item"]["raw"]))
            TRACE.count_trial(t)
        return [{"ok": True, "stats": {"CombinedDPS": 1.0}} for _ in trials]


def _screened_ring_bases(rails: Rails) -> set[str]:
    pob = _Pob()
    gen = SkeletonGenerator(pob, rails, objective=Objective(maximize="CombinedDPS"), log=lambda _m: None, gear_mode="loot")
    sk = Skeleton(class_name="Ranger", ascendancy="Deadeye", level=77, main_link=["Lightning Arrow"])
    TRACE.reset()
    gen._screen_armour(sk, n=3, seed=1, wishlist=False)
    TRACE.reset()
    return {raw.splitlines()[2] for slot, raw in pob.sent if slot == "Ring 1"}


def test_the_rail_lists_prismatic_ring_for_day1_and_t16_and_nothing_for_endgame() -> None:
    assert PRISMATIC.casefold() in Rails.load().gear.excluded_bases  # the default loadout is day1
    assert PRISMATIC.casefold() in Rails.load(loadout="day1").gear.excluded_bases
    assert PRISMATIC.casefold() in Rails.load(loadout="t16").gear.excluded_bases
    assert not Rails.load(loadout="endgame").gear.excluded_bases


def test_the_day1_ring_screen_never_sends_a_prismatic_ring_and_the_endgame_one_does() -> None:
    day1 = _screened_ring_bases(Rails.load())
    assert PRISMATIC not in day1 and OTHER_RINGS & day1  # the other ring bases are still screened
    assert PRISMATIC in _screened_ring_bases(Rails.load(loadout="endgame"))


def test_the_trace_class_counts_the_excluded_base_and_stays_zero_on_a_day1_screen() -> None:
    pob = _Pob()
    gen = SkeletonGenerator(pob, Rails.load(), objective=Objective(maximize="CombinedDPS"), log=lambda _m: None, gear_mode="loot")
    sk = Skeleton(class_name="Ranger", ascendancy="Deadeye", level=77, main_link=["Lightning Arrow"])
    TRACE.reset()
    gen._screen_armour(sk, n=3, seed=1, wishlist=False)
    classes = {name for moves in TRACE.considered().values() for name, n in moves.items() if n.get("evaluated", 0) or n.get("generated", 0)}
    TRACE.reset()
    assert "base:Amethyst Ring" in classes and "base:Prismatic Ring" not in classes
    assert "base-excluded-by-loadout" not in classes
    # the class itself works: a trial that WOULD carry the base is counted under it
    trial = {"item": {"slot": "Ring 1", "raw": "Rarity: Rare\nName\nPrismatic Ring\n+1 life"}}
    TRACE.count_candidates([trial])
    seen = {name for moves in TRACE.considered().values() for name in moves}
    TRACE.reset()
    assert "base-excluded-by-loadout" in seen


def test_any_listed_base_is_refused_not_only_rings(tmp_path: Path) -> None:
    rails = _rails_with(tmp_path, {"day1": [PRISMATIC, "Opal Wand", "Onyx Amulet"], "endgame": []}, "day1")
    assert "Opal Wand" not in without_excluded(bases_of_type("Wand", max_level=70), rails)
    assert "Driftwood Wand" in without_excluded(bases_of_type("Wand", max_level=70), rails)
    assert "Onyx Amulet" not in candidate_bases("Amulet", max_level=70, excluded=rails.gear.excluded_bases)
    assert "Onyx Amulet" in candidate_bases("Amulet", max_level=70, excluded=_rails_with(tmp_path, {"day1": [PRISMATIC]}, "day1").gear.excluded_bases)
    # case and a loadout the table does not name
    assert "opal wand" in rails.gear.excluded_bases
    assert not _rails_with(tmp_path, {"day1": ["Opal Wand"]}, "t16").gear.excluded_bases


def test_a_loot_weapon_base_swap_and_a_wishlist_base_candidate_skip_the_excluded_base(tmp_path: Path) -> None:
    rails = _rails_with(tmp_path, {"day1": ["Opal Wand", PRISMATIC]}, "day1")
    loot = object.__new__(LootGear)
    loot.rails = rails
    swaps = loot.other_weapon_bases("Driftwood Wand")
    assert swaps and "Opal Wand" not in swaps
    wish = object.__new__(WishlistGear)
    wish.rails = rails
    assert PRISMATIC not in wish.base_candidates("Amethyst Ring") and "Amethyst Ring" in wish.base_candidates("Amethyst Ring")
    assert "Opal Wand" not in wish.base_candidates("Driftwood Wand")
    assert PRISMATIC in wish.base_candidates(PRISMATIC)  # a base the request itself names (a forced rare base) is not overridden
    wish.rails = _rails_with(tmp_path, {"day1": [PRISMATIC]}, "endgame")
    assert PRISMATIC in wish.base_candidates("Amethyst Ring")


def test_a_rails_stand_in_without_the_key_excludes_nothing() -> None:
    from types import SimpleNamespace

    assert without_excluded(["A", "B"], SimpleNamespace(gear=SimpleNamespace())) == ["A", "B"]
    assert without_excluded(["A", "B"], SimpleNamespace()) == ["A", "B"]
    assert ARMOUR_SLOT_TYPES["Ring 1"] == "Ring"
