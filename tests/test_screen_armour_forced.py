"""The armour screen's rolls carry a slot's forced affix line (#523, no PoB): `_best_roll` rolls with `forced=` the
slot's mod choices, sends only rolls that carry every line, and skips a base that cannot roll it."""

from __future__ import annotations

from junkroan.optimizer.loot_gear import raw_carries
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.trace import TRACE
from junkroan.search.generator import ARMOUR_SLOT_TYPES, SkeletonGenerator, candidate_bases
from junkroan.search.skeleton import Skeleton

LINE = "Adds 1 to 2 Cold Damage to Attacks"
CARRY = f"{{tags:cold}}{{prefix}}{LINE}"
N = 4


class _Pob:
    def __init__(self) -> None:
        self.forced_kwargs: list = []  # the `forced` argument of every random_rares call
        self.sent: list[tuple[str, str]] = []
        self.no_roll: set[str] = set()  # bases whose mod list lacks the line
        self.forced_calls = 0

    def equip(self, mapping) -> None:
        pass

    def list_item_mods(self, base, ilvl=None, pool="explicit") -> dict:
        lines = [] if base in self.no_roll else [LINE]
        return {"mods": [{"mod_id": "cold1", "lines": lines}, {"mod_id": "life1", "lines": ["+1 life"]}]}

    def random_rares(self, base, *, n, ilvl=None, quality=None, seed=None, forced=None) -> list[dict]:
        self.forced_kwargs.append(forced)
        if forced is not None:
            self.forced_calls += 1
        rolls = []
        for i in range(n):
            # a forced roll carries the line; on the second forced base every other roll drops it (the filter must remove those)
            carries = forced is not None and not (self.forced_calls == 2 and i % 2)
            rolls.append({"raw": f"{base} {i}\n" + (f"{CARRY}\n" if carries else "") + "+1 life"})
        return rolls

    def trial_stats(self, trials, keys, mode="fast") -> list[dict]:
        for t in trials:
            self.sent.append((t["item"]["slot"], t["item"]["raw"]))
            TRACE.count_trial(t)
        return [{"ok": True, "stats": {"CombinedDPS": 1.0}} for _ in trials]


def _screen(pob: _Pob, **kw):
    gen = SkeletonGenerator(pob, Rails.load(), objective=Objective(maximize="CombinedDPS"), log=lambda _m: None, gear_mode="loot")
    sk = Skeleton(class_name="Ranger", ascendancy="Deadeye", level=77, main_link=["Lightning Arrow"], **kw)
    TRACE.reset()
    TRACE.set_forced(sk.forced_affixes or None)
    chosen = gen._screen_armour(sk, n=N, seed=1, wishlist=False)
    moves = TRACE.considered()
    TRACE.reset()
    return chosen, moves


def test_forced_line_rides_every_ring_roll_and_nothing_lacking_it_is_sent() -> None:
    pob = _Pob()
    chosen, moves = _screen(pob, forced_affixes={"Ring 1": [LINE]})
    ring = [raw for slot, raw in pob.sent if slot == "Ring 1"]
    assert ring and all(raw_carries(raw, LINE) for raw in ring)
    assert pob.forced_calls >= 2 and len(ring) < N * pob.forced_calls  # the second base's lacking rolls were dropped
    assert "Ring 1" in chosen
    missing = moves.get("(unattributed)", {}).get("forced-missing:affix:Ring 1", {"generated": 0, "evaluated": 0})
    assert missing == {"generated": 0, "evaluated": 0}


def test_a_base_that_cannot_roll_the_line_is_not_screened_and_no_base_means_no_slot() -> None:
    pob = _Pob()
    pob.no_roll = set(candidate_bases(ARMOUR_SLOT_TYPES["Ring 1"], max_level=Rails.load().gear.item_level, excluded=Rails.load().gear.excluded_bases))
    chosen, _ = _screen(pob, forced_affixes={"Ring 1": [LINE]})
    assert "Ring 1" not in chosen
    assert not [1 for slot, _r in pob.sent if slot == "Ring 1"]


def test_without_forced_affixes_random_rares_gets_no_forced_and_every_roll_is_sent() -> None:
    pob = _Pob()
    chosen, _ = _screen(pob)
    assert pob.forced_kwargs and all(f is None for f in pob.forced_kwargs)
    ring = [raw for slot, raw in pob.sent if slot == "Ring 1"]
    assert ring and len(ring) == N * len(candidate_bases(ARMOUR_SLOT_TYPES["Ring 1"], max_level=Rails.load().gear.item_level, excluded=Rails.load().gear.excluded_bases))
    assert "Ring 1" in chosen
