"""Rare gear filler: choose affixes slot by slot with PoB as the judge.

For one slot: enumerate the mods PoB allows on the base (under the rails' tier
and item-level caps), and add affixes greedily. Each candidate item is crafted
through PoB (`craft_rare`) and evaluated through the what-if calculator's item
override (`trial_stats` mode fast). Selection uses the same rule as the tree
optimizer: reduce constraint violation first (resists, attributes, life), then
objective gain. The chosen item is equipped with `equip` (other slots untouched).

No game knowledge lives here: what a mod does is PoB's business.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence

# the fill order and the keep/reject ordering live with the loot filler: one definition, three fillers
from junkroan.optimizer.loot_gear import RARE_SLOT_ORDER, _rank, ordered_slots
from junkroan.optimizer.objective import Objective, Score
from junkroan.optimizer.rails import GearRails, Rails
from junkroan.optimizer.red_line_gate import red_lines_blocking
from junkroan.optimizer.trace import TRACE
from junkroan.pob.session import PobSession
from junkroan.search.forced import affix_template


@dataclass(slots=True)
class AffixChoice:
    mod_id: str
    affix_type: str  # "Prefix" | "Suffix"
    group: str
    tier: int
    line: str
    range: float = 0.5


@dataclass(slots=True)
class SlotResult:
    slot: str
    base: str
    affixes: list[AffixChoice] = field(default_factory=list)
    raw: str = ""
    before: Score | None = None
    after: Score | None = None
    steps: list[str] = field(default_factory=list)
    seconds: float = 0.0


class GearFiller:
    """The affix ceiling of a base: what the best legal rare on it could be.

    Its one caller is the weapon-base screen (D41, `search/generator._ceiling`), which
    compares weapon types by what their affix pool can do for the skill. The three tier
    caps below were rails until D67; nothing else ever read them, so they live here as
    this screen's own constants (measured on 94 reference rares: median 0 T1 mods per
    rare, max 3). Day-1 items come from `loot_gear.LootGear` or `wishlist_gear.WishlistGear`.
    """

    def __init__(
        self,
        pob: PobSession,
        objective: Objective,
        rails: Rails | None = None,
        *,
        log: Callable[[str], None] | None = None,
        min_gain: float = 0.001,
        max_tier: int = 8,  # worst tier still worth listing (1 = best)
        max_t1_per_item: int = 1,
        max_t2_per_item: int = 2,
    ) -> None:
        self.pob = pob
        self.objective = objective
        self.rails = rails or Rails.load()
        self.log = log or (lambda _m: None)
        self.min_gain = min_gain
        self.max_tier, self.max_t1_per_item, self.max_t2_per_item = max_tier, max_t1_per_item, max_t2_per_item
        self._mods_cache: dict[tuple[str, int], list[dict]] = {}

    # -- data ----------------------------------------------------------------

    def legal_mods(self, base: str) -> list[dict]:
        """Legal explicit mods on `base` at the rails' item level, annotated with tier."""

        key = (base, self.rails.gear.item_level)
        if key not in self._mods_cache:
            listed = self.pob.list_item_mods(base)  # full ladders so tiers are absolute ranks
            ladders: dict[str, list[dict]] = {}
            for mod in listed["mods"]:
                ladders.setdefault(mod["group"], []).append(mod)
            rows: list[dict] = []
            for group, ladder in ladders.items():
                for tier, mod in enumerate(ladder, start=1):
                    if mod["level"] <= self.rails.gear.item_level and tier <= self.max_tier:
                        rows.append({**mod, "tier": tier})
            self._mods_cache[key] = rows
        return self._mods_cache[key]

    # -- one slot ------------------------------------------------------------

    def _forced_seed(self, base: str, lines: Sequence[str], mods: Sequence[dict]) -> list[AffixChoice]:
        """One mod per forced line (its best tier under the T1/T2 caps) to pre-seed the greedy craft (#510).
        Raises ValueError when the base cannot roll a line: the caller skips that base."""

        seeded: list[AffixChoice] = []
        for line in lines:
            want = affix_template(line)
            rows = [m for m in mods if any(affix_template(str(t)) == want for t in m.get("lines") or [])
                    and m["group"] not in {c.group for c in seeded}]
            rows.sort(key=lambda m: m["tier"])
            for m in rows:
                if (m["tier"] == 1 and sum(1 for c in seeded if c.tier == 1) >= self.max_t1_per_item) or (
                        m["tier"] == 2 and sum(1 for c in seeded if c.tier == 2) >= self.max_t2_per_item):
                    continue
                seeded.append(AffixChoice(m["mod_id"], m["type"], m["group"], m["tier"], m["lines"][0]))
                break
            else:
                raise ValueError(f"mod line {line!r} cannot roll on {base}")
        return seeded

    def fill_slot(self, slot: str, base: str, *, sockets: str | None = None, keep_equipped: bool = True,
                  forced: Sequence[str] | None = None) -> SlotResult:
        t0 = time.perf_counter()
        gear = self.rails.gear
        result = SlotResult(slot=slot, base=base)
        keys = self.objective.stat_keys
        score = self.objective.score(self.pob.stats(keys))
        result.before = score
        chosen: list[AffixChoice] = []
        mods = self.legal_mods(base)
        if forced:  # the request's mod lines ride the whole craft: no ceiling without them (#510)
            chosen = self._forced_seed(base, forced, mods)
            item = self._craft(base, chosen, sockets=sockets)
            # a marked red line no longer drops the item (#1124); the lane is not known here: marked on either lane
            if item["problems"] or red_lines_blocking(item["unsupported_lines"]):
                raise ValueError(f"forced lines {list(forced)!r} cannot be crafted on {base}")
            result.raw = item["raw"]
            self.pob.equip({slot: item["raw"]})
            score = self.objective.score(self.pob.stats(keys))
            result.steps.append("forced: " + ", ".join(c.line for c in chosen))

        while len(chosen) < gear.max_explicit_mods:
            used_groups = {c.group for c in chosen}
            n_prefix = sum(1 for c in chosen if c.affix_type == "Prefix")
            n_suffix = sum(1 for c in chosen if c.affix_type == "Suffix")
            n_t1 = sum(1 for c in chosen if c.tier == 1)
            n_t2 = sum(1 for c in chosen if c.tier == 2)
            candidates = [
                m for m in mods
                if m["group"] not in used_groups
                and (m["type"] != "Prefix" or n_prefix < gear.max_prefixes)
                and (m["type"] != "Suffix" or n_suffix < gear.max_suffixes)
                and (m["tier"] != 1 or n_t1 < self.max_t1_per_item)
                and (m["tier"] != 2 or n_t2 < self.max_t2_per_item)
            ]
            # one candidate per (group, tier) is enough: within a group only the best allowed tier
            best_per_group: dict[str, dict] = {}
            for m in candidates:
                cur = best_per_group.get(m["group"])
                if cur is None or m["tier"] < cur["tier"]:
                    best_per_group[m["group"]] = m
            candidates = list(best_per_group.values())
            if not candidates:
                result.steps.append("no candidates left")
                break

            crafted: list[tuple[dict, dict]] = []
            for m in candidates:
                trial_affixes = chosen + [AffixChoice(m["mod_id"], m["type"], m["group"], m["tier"], m["lines"][0])]
                item = self._craft(base, trial_affixes, sockets=sockets)
                if item["problems"] or red_lines_blocking(item["unsupported_lines"]):  # no lane known: marked on either lane passes (#1124)
                    continue
                crafted.append((m, item))
            if not crafted:
                result.steps.append("no craftable candidates")
                break
            gf_trials = [{"item": {"slot": slot, "raw": item["raw"]}} for _m, item in crafted]
            TRACE.count_candidates(gf_trials)
            outcomes = self.pob.trial_stats(gf_trials, keys, mode="fast")
            best = None
            for (m, item), outcome in zip(crafted, outcomes):
                if not outcome.get("ok") or not outcome.get("stats"):
                    continue
                trial_score = self.objective.score(outcome["stats"])
                key = self._rank_key(score, trial_score)
                if best is None or key > best[0]:
                    best = (key, m, item, trial_score)
            if best is None:
                result.steps.append("no evaluable candidates")
                break
            _key, m, item, trial_score = best
            improved = (trial_score.violation < score.violation - 1e-9) or (
                trial_score.feasible and trial_score.value >= score.value * (1.0 + self.min_gain)
            ) or (not score.feasible and trial_score > score)
            if not improved:
                result.steps.append("no affix improves the build")
                break
            chosen.append(AffixChoice(m["mod_id"], m["type"], m["group"], m["tier"], m["lines"][0]))
            result.raw = item["raw"]
            result.steps.append(
                f"+ {m['type'][0]} T{m['tier']} {m['lines'][0]}  value {score.value:,.0f} -> {trial_score.value:,.0f} "
                f"viol {score.violation:.3f} -> {trial_score.violation:.3f} [{len(crafted)} cands]"
            )
            # commit for real so later candidates see the partially built item
            self.pob.equip({slot: item["raw"]})
            score = self.objective.score(self.pob.stats(keys))

        result.affixes = chosen
        result.after = score
        result.seconds = time.perf_counter() - t0
        for line in result.steps:
            self.log(f"[{slot}] {line}")
        return result

    # -- all slots -----------------------------------------------------------

    def fill(self, bases_by_slot: Mapping[str, str], *, sockets_by_slot: Mapping[str, str] | None = None, passes: int = 1) -> list[SlotResult]:
        results: list[SlotResult] = []
        order = ordered_slots(bases_by_slot)
        for _pass in range(passes):
            for slot in order:
                if _pass > 0:
                    self.pob.equip({slot: None})  # re-fill from empty, seeing every other slot filled
                results.append(self.fill_slot(slot, bases_by_slot[slot], sockets=(sockets_by_slot or {}).get(slot)))
        return results

    # -- helpers -------------------------------------------------------------

    def _craft(self, base: str, affixes: Sequence[AffixChoice], *, sockets: str | None) -> dict:
        return self.pob.craft_rare(
            base,
            prefixes=[{"mod_id": a.mod_id, "range": a.range} for a in affixes if a.affix_type == "Prefix"],
            suffixes=[{"mod_id": a.mod_id, "range": a.range} for a in affixes if a.affix_type == "Suffix"],
            ilvl=self.rails.gear.item_level,
            quality=self.rails.gear.quality,
            sockets=sockets,
        )

    @staticmethod
    def _rank_key(current: Score, trial: Score) -> tuple[float, float]:
        """The loot filler's `_rank`, nan-free: a candidate that leaves an infinitely infeasible
        build where it found it (an empty weapon slot) compares by value, never as nan."""

        return _rank(current, trial)


__all__ = ["GearFiller", "SlotResult", "AffixChoice", "RARE_SLOT_ORDER"]
