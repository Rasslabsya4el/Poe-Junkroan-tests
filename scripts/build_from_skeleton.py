"""Intermediate prototype: a skeleton in, a complete build out.

Two modes:
  --from-fixture stormbrand   extract the author's skeleton (class, ascendancy nodes,
                              keystones, gem links, uniques, rare bases, flasks, jewels)
                              and rebuild everything else; compare to the author.
  --skeleton path.json        run a hand-written skeleton (see Skeleton.to_json()).

Run:  python scripts/build_from_skeleton.py --from-fixture stormbrand
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from functools import lru_cache
from itertools import combinations
from pathlib import Path
from typing import Callable, Iterable, Sequence
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from junkroan.optimizer.pipeline import BuildPipeline, REPORT_KEYS  # noqa: E402
from junkroan.optimizer.rails import Rails  # noqa: E402
from junkroan.optimizer.tree_graph import TreeGraph, parse_allocated_from_xml  # noqa: E402
from junkroan.optimizer.wishlist_gear import is_pure_es  # noqa: E402
from junkroan.pob.session import PobSession, decode_import_code  # noqa: E402
from junkroan.search.generator import write_saved_lists  # noqa: E402
from junkroan.search.hypothesis import is_limited_curse  # noqa: E402
from junkroan.search.skeleton import Skeleton, SocketGroup  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "tuadh_329"


def main_active_gem_index(gem_names: Sequence[str], main_active_skill: int) -> int | None:
    """The position in `gem_names` of the gem PoB's `mainActiveSkill` selects, or None when the
    group grants no active skill at all.

    `mainActiveSkill` is a 1-based index into the group's **active skill list**, never into its
    gems (PoB, Modules/CalcSetup.lua: the list is built gem by gem over each gem's
    `grantedEffectList` with the supports skipped, and the index is clamped to its length --
    `m_min(#socketGroupSkillList, group.mainActiveSkill or 1)`; Modules/Build.lua then reads
    `displaySkillList[mainActiveSkill]` as the build's main skill). A Vaal gem grants two skills
    (the Vaal one and its base) and so takes two places in that list; which of the two the author
    picked is the same gem either way, which is all a skeleton carries.

    So the author's first gem need not be their main skill: the 3.27 Raise Spectre Necromancer
    lists Minion Damage first and the 3.28 Shock Nova Hierophant lists Archmage, and reading
    `gems[0]` as the main skill made `objective_for` score those references 0 (2026-09-18). The
    3.29 Essence Drain Occultist is the same trap one step further in: its list is Spellslinger,
    Contagion, Essence Drain and the author points at 3, because Spellslinger deals no damage."""

    from junkroan.search.hypothesis import active_gems

    actives = active_gems()
    entries: list[int] = []  # one place per active skill PoB lists, holding the gem it came from
    for position, name in enumerate(gem_names):
        key = str(name or "").strip().lower()
        # the corpus flag first; the name prefix catches a transfigured Vaal gem the corpus does not
        # carry under that name ("Vaal Ground Slam of Earthshaking"), as scripts/extract_loadout.py does
        vaal = bool((actives.get(key) or {}).get("is_vaal_gem")) or key.startswith("vaal ")
        if not key or (key not in actives and not vaal):
            continue  # a support grants no active skill and takes no place in the list
        entries += [position] * (2 if vaal else 1)
    if not entries:
        return None
    return entries[min(max(int(main_active_skill or 1), 1), len(entries)) - 1]


def socket_groups_from_xml(skills: ET.Element, main_idx: int) -> tuple[list[str], str, list[SocketGroup]]:
    """(main link, its slot, the other groups) of the active skill set. A group socketed in a
    weapon swap is dropped like a swap item slot is: the author's off-hand "Arcane Surge +
    Elemental Focus" is not a live group, and carrying it in made it one in every build.

    A group with no active gem in it is dropped for the same reason (the audit's "dead support
    group"): its supports support nothing, and the sockets are the build's to use. Eight of the
    references carry one.

    The head of the main link is the active gem the author's `mainActiveSkill` names
    (`main_active_gem_index`), not the first gem of the group: everything downstream reads
    `main_link[0]` as the build's main skill (`objective_for`, `Skeleton.apply_skills`, which
    sockets it at `main_active_skill_index` 1). The supports follow in the author's order."""

    from junkroan.optimizer.audit import dead_support_group

    active_set = skills.get("activeSkillSet") or "1"
    skill_set = next((s for s in skills.findall("SkillSet") if s.get("id") == active_set), None)
    groups_xml = skill_set.findall("Skill") if skill_set is not None else skills.findall("Skill")
    main_link: list[str] = []
    main_slot = "Body Armour"
    extra: list[SocketGroup] = []
    for i, g in enumerate(groups_xml, start=1):
        gems = [gem.get("nameSpec") for gem in g.findall("Gem") if gem.get("enabled", "true") == "true" and gem.get("nameSpec")]
        if not gems:
            continue
        if i == main_idx:
            head = main_active_gem_index(gems, int(g.get("mainActiveSkill") or 1))
            main_link = gems if not head else [gems[head], *gems[:head], *gems[head + 1:]]
            main_slot = g.get("slot") or "Body Armour"
        else:
            slot = g.get("slot") or ""
            if "Swap" in slot or dead_support_group(gems):
                continue
            if not slot:  # a group PoB keeps without a socket: give it one, PoB does not check socket counts
                slot = next((s for s in ("Helmet", "Gloves", "Boots", "Weapon 1", "Weapon 2", "Body Armour") if s not in {e.slot for e in extra}), "Helmet")
            extra.append(SocketGroup(gems=gems, slot=slot, include_in_full_dps=g.get("includeInFullDPS") == "true", enabled=g.get("enabled", "true") == "true", label=g.get("label") or "", source_index=i))
    return main_link, main_slot, extra


def aura_levels_from_xml(skills: ET.Element, skeleton: Skeleton, main_idx: int, rail_level: int) -> dict[str, int]:
    """#816 row 9: the level the XML holds for each flat-reservation aura the skeleton carries, when it is below the
    rail level. `apply_skills` writes `aura_levels.get(name, rail)` for every gem, so a start whose Vitality is
    level 1 (a delivered build, tuned by `tune_flat_reservation_aura_levels`) would otherwise be re-written at the
    rail level by its first skills write. Same semantics as the pipeline's field: only names in
    `flat_reservation_auras()`, a level at or above the rail is left out (it is written at the rail anyway). The
    first enabled gem of a name in a carried group (the main group or an extra group by `source_index`) gives the level."""

    names = skeleton.flat_reservation_auras()
    if not names:
        return {}
    active_set = skills.get("activeSkillSet") or "1"
    skill_set = next((s for s in skills.findall("SkillSet") if s.get("id") == active_set), None)
    groups_xml = skill_set.findall("Skill") if skill_set is not None else skills.findall("Skill")
    carried = {main_idx, *(g.source_index for g in skeleton.extra_groups if g.enabled)}
    found: dict[str, int] = {}
    for i, g in enumerate(groups_xml, start=1):
        if i not in carried:
            continue
        for gem in g.findall("Gem"):
            name = gem.get("nameSpec")
            if name in names and name not in found and gem.get("enabled", "true") == "true" and (gem.get("level") or "").isdigit():
                found[name] = int(gem.get("level"))
    return {name: level for name, level in found.items() if 1 <= level < rail_level}


def minion_skills_from_xml(skills: ET.Element, skeleton: Skeleton, main_idx: int) -> dict[str, int]:
    """#1024: the minion skill (`skillMinionSkill`) the XML holds for each gem the skeleton carries. `skill_payload` writes
    `gem_minion_skills[name]` on the gem; a skeleton read from an export left it empty, so the first skills write put every
    minion gem back on its skill 1 (Vaal Absolution 2 -> 1, Raise Zombie 3 -> 1: FullDPS 635,471 -> 189,396 / 314,571 each).
    Keyed by the skeleton's own name (a Vaal gem by its plain name, as `Skeleton.__post_init__` names it); the first enabled
    gem of a name in a carried group (the main group or an extra group by `source_index`) gives the value."""

    from junkroan.search.vaal_twin import plain_of_vaal

    carried_names = {*skeleton.main_link, *(name for g in skeleton.extra_groups if g.enabled for name in g.gems)}
    active_set = skills.get("activeSkillSet") or "1"
    skill_set = next((s for s in skills.findall("SkillSet") if s.get("id") == active_set), None)
    groups_xml = skill_set.findall("Skill") if skill_set is not None else skills.findall("Skill")
    carried = {main_idx, *(g.source_index for g in skeleton.extra_groups if g.enabled)}
    found: dict[str, int] = {}
    for i, g in enumerate(groups_xml, start=1):
        if i not in carried:
            continue
        for gem in g.findall("Gem"):
            raw = gem.get("nameSpec") or ""
            name = plain_of_vaal(raw) or raw
            if name in carried_names and name not in found and gem.get("enabled", "true") == "true" and (gem.get("skillMinionSkill") or "").isdigit():
                found[name] = max(1, int(gem.get("skillMinionSkill")))
    return found


def drop_unsupported_gems(pob: PobSession, skeleton: Skeleton, main_index: int) -> list[str]:
    """PoB's own verdict on the author's build, read back before we rebuild it: a support gem its
    calc applies to no active skill of its group, or one a stronger copy in the group supersedes,
    is a socket spent on nothing and does not enter the skeleton (`PobSession.unsupported_gems`,
    the audit's "unsupported gem" check on the other side). One occurrence per reported row, so a
    superseded copy leaves its twin in place. Returns a line per dropped gem."""

    by_index: dict[int, list[str]] = {g.source_index: g.gems for g in skeleton.extra_groups if g.source_index}  # 0 = not from an export: no row can address it
    by_index[main_index] = skeleton.main_link
    dropped: list[str] = []
    for row in pob.unsupported_gems():
        gems = by_index.get(int(row.get("group") or 0))
        gem = str(row.get("gem") or "")
        if not gems or gem not in gems or len(gems) <= 1:
            continue
        gems.remove(gem)
        dropped.append(f"{gem} ({row.get('reason')}) from group {row.get('group')} {row.get('slot') or ''}".strip())
    return dropped


# (what makes a gem part of the family, the PoB stat that limits it, what to call it in a log line). The
# families a build can carry more gems of than the game lets it use at once. A family is either the corpus
# tags a gem must all carry (golems) or a predicate on the gem name. The curse family is the audit's own
# count (`is_limited_curse`: a curse that is a hex or a mark, not an aura; #784): a Mark takes a curse slot
# like a hex (spark-s4: limit 1, PoB's CurseList held Sniper's Mark and dropped Conductivity), while Hexblast
# -- a damage spell that eats a hex -- and Bane, which carries other people's hexes, take none.
GemFamily = tuple[str, ...] | Callable[[str], bool]
LIMITED_GEM_FAMILIES: tuple[tuple[GemFamily, str, str], ...] = ((("golem",), "ActiveGolemLimit", "golem"), (is_limited_curse, "EnemyCurseLimit", "curse"))


def tagged_gems(names: Sequence[str], tags: str | Sequence[str] | Callable[[str], bool]) -> list[str]:
    """The active gems of `names` in the family `tags` names, in order, without repeats: carrying every one
    of those corpus tags ("golem"; "curse" and "hex"), or, for a callable, the ones it accepts
    (`is_limited_curse`: the audit's curse count, a mark included)."""

    from junkroan.search.hypothesis import active_gems

    actives = active_gems()
    if callable(tags):
        member: Callable[[str], bool] = tags
    else:
        wanted = {tags} if isinstance(tags, str) else set(tags)
        member = lambda name: bool(wanted <= set((actives.get(name.strip().lower()) or {}).get("tag_keys") or []))  # noqa: E731
    out: list[str] = []
    for name in names:
        if str(name).strip().lower() in actives and member(str(name)) and name not in out:
            out.append(str(name))
    return out


def xml_with_gems_disabled(xml: str, names: Iterable[str]) -> str:
    """The build XML with every gem of those names written `enabled=false` (the gem-level flag
    `optimizer/buff_gems` uses for a guard skill). By name, so a copy in a second group goes too."""

    low = {str(n).strip().lower() for n in names}
    if not low:
        return xml
    root = ET.fromstring(xml)
    for gem in root.iter("Gem"):
        if str(gem.get("nameSpec") or "").strip().lower() in low:
            gem.set("enabled", "false")
    return ET.tostring(root, encoding="unicode")


def best_scoring_subset(candidates: Sequence[str], keep: int, score: Callable[[tuple[str, ...]], float]) -> tuple[list[str], dict[tuple[str, ...], float]]:
    """The `keep` of `candidates` PoB scores best, and every subset's score. `score` is called
    once per subset (C(4,3) = 4, C(5,3) = 10). A tie keeps the author's order: the subsets are
    enumerated in it and the first of the best ones wins."""

    subsets = list(combinations(candidates, keep)) if keep > 0 else [()]
    scored = {subset: float(score(subset)) for subset in subsets}
    best = max(subsets, key=lambda s: scored[s])  # max() keeps the first of equal scores
    return list(best), scored


def skeleton_limits(pob: PobSession, state_xml: str, stats_keys: Sequence[str]) -> dict[str, float]:
    """PoB's limit stats for the build the skeleton *guarantees*, measured by removing the
    author's ordinary tree from the build PoB holds (their ascendancy, keystones, uniques and
    jewels stay: the skeleton keeps those).

    The author's own readback is not the number to compare gems against: cold_dot reads
    ActiveGolemLimit 4 because the author allocated the notable Golem Commander (+1 golem), an
    ordinary tree node no skeleton carries and our tree optimizer did not take -- the finished
    build then ran four golem gems on a limit of 3 (the frozen campaign's audit). A gem is
    licensed by what the skeleton brings, not by a tree choice the optimizer is free to make.

    Caveat, written down rather than special-cased: a build whose curse limit is its maximum
    power charges (PoB's `CurseLimitIsMaximumPowerCharges`) loses the charges its ordinary tree
    granted along with the tree, so its EnemyCurseLimit here is a floor."""

    graph = TreeGraph.load()
    from junkroan.pob.tree_payload_normalization import canonical_active_tree_corpus

    asc = {int(n) for n in canonical_active_tree_corpus()["ascendancy_node_ids"]}
    ordinary = [n for n in parse_allocated_from_xml(state_xml) if n in graph.allocatable and n not in asc]
    if ordinary:
        pob.mutate_nodes(remove=ordinary)
    raw = pob.stats(tuple(stats_keys))
    return {k: float(v) for k, v in raw.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


def drop_over_limit_gems(pob: PobSession, skeleton: Skeleton, *, rails: Rails | None = None) -> list[str]:
    """Gems of a limited family the game cannot all use at once, dropped from the skeleton at
    derivation, keeping the subset PoB scores best.

    * **Golems.** PoB applies every enabled golem's buff whatever `ActiveGolemLimit` says (probed
      2026-09-16 on cold_dot: four golem gems, each one's buff moved the number on its own), so a
      build over the limit is scored on buffs the game cannot give it.
    * **Curses (hexes and marks).** PoB does respect `EnemyCurseLimit`: `CalcPerform.lua` fills `curseSlots` in
      `for i = 1, source.limit do` and a curse only takes a slot when one is free or its
      `determineCursePriority` beats the curse sitting there. So the number is already honest and
      the drop is about the skeleton telling the truth -- the sockets of the curses PoB never
      applies are the build's to use, and the audit's warning and the explanation agree with it.
      The family is the audit's own count (`is_limited_curse`, #784): a mark takes a slot like a hex
      (spark-s4: limit 1, Conductivity + Sniper's Mark, PoB applied only the Mark), so the subset is
      chosen among hexes and marks together; Hexblast and Bane -- "hex" without "curse" -- stay.

    Which ones to keep is PoB's call, never a name list: every subset of size = limit is scored by
    disabling the other gems of the family (the gem-level `enabled` flag) and reading the
    objective's own stat, and the best subset stays. A gem in the main link is never dropped; it
    counts against the limit and the choice is made among the extra groups. A group left empty
    goes, and one left with nothing but supports falls under the dead-group rule.

    The limit is the skeleton's, not the author's (`skeleton_limits`), and the build PoB holds is
    restored exactly as it was. Returns one log line per family touched."""

    from junkroan.optimizer.audit import dead_support_group
    from junkroan.optimizer.objective_select import objective_for

    carried = list(skeleton.main_link) + [g for grp in skeleton.extra_groups for g in grp.gems]
    # one gem of a family can only be over a limit of 0, and the game has no source for that: those
    # builds (most of them: a single curse) skip the PoB round trip entirely
    families = [f for f in LIMITED_GEM_FAMILIES if len(tagged_gems(carried, f[0])) > 1]
    if not families:
        return []
    state = pob.export_xml()
    lines: list[str] = []
    try:
        limits = skeleton_limits(pob, state, [stat for _tags, stat, _label in families])
        over: list[tuple[str, int, int, list[str], list[str]]] = []  # label, limit, keep, forced, candidates
        for tags, stat, label in families:
            if stat not in limits:
                continue
            limit = int(limits[stat])
            forced = tagged_gems(skeleton.main_link, tags)  # the main skill is the build; it is never dropped
            candidates = [n for n in tagged_gems([g for grp in skeleton.extra_groups for g in grp.gems], tags) if n not in forced]
            keep = max(0, limit - len(forced))
            if len(forced) + len(candidates) <= limit or keep >= len(candidates):
                continue
            over.append((label, limit, keep, forced, candidates))
        if not over:
            return []

        pob.load_xml(state)  # the subsets are judged on the build as the author left it, tree and all
        key = objective_for(rails or Rails.load(), skeleton.main_link[0]).maximize if skeleton.main_link else "CombinedDPS"
        base = pob.stats((key, "CombinedDPS"))
        if not isinstance(base.get(key), (int, float)) or float(base.get(key) or 0.0) <= 0.0:
            key = "CombinedDPS"  # FullDPS is 0 on a build with no group flagged for it: a subset would score nothing
        off: list[str] = []  # what earlier families dropped: later ones are judged on the build as it will be
        for label, limit, keep, forced, candidates in over:
            def score(subset: tuple[str, ...], _cands: list[str] = candidates) -> float:
                pob.load_xml(xml_with_gems_disabled(state, off + [n for n in _cands if n not in subset]))
                value = pob.stats((key,)).get(key)
                return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0

            kept, scored = best_scoring_subset(candidates, keep, score)
            dropped = [n for n in candidates if n not in kept]
            off.extend(dropped)
            for group in list(skeleton.extra_groups):
                if not any(n in dropped for n in group.gems):
                    continue
                group.gems = [n for n in group.gems if n not in dropped]
                if not group.gems or dead_support_group(group.gems):
                    skeleton.extra_groups.remove(group)
            subsets = " | ".join(f"{'+'.join(s) or '(none)'} {v:,.0f}" for s, v in scored.items())
            # a minion build reads 0 on both FullDPS (no group flagged yet) and CombinedDPS: then PoB
            # has no verdict and the author's order is all there is. Said out loud rather than hidden.
            flat = " -- every subset scores the same, so the author's order decided" if max(scored.values()) == min(scored.values()) else ""
            lines.append(f"skeleton: {len(forced) + len(candidates)} {label} gems for a {label} limit of {limit}: kept {', '.join(forced + kept) or '(none)'}, "
                         f"dropped {', '.join(dropped)} ({key} {scored[tuple(kept)]:,.0f}; subsets: {subsets}{flat})")
    finally:
        pob.load_xml(state)
    return lines


def xml_with_group_gems_disabled(xml: str, disable: Iterable[tuple[int, str, int]]) -> str:
    """The build XML with single gems written `enabled=false`: each entry is (the group's 1-based index in the
    active skill set, the gem name, which enabled copy of that name in the group: 0 = the first). Unlike
    `xml_with_gems_disabled` a copy of the same gem in another group stays on."""

    todo = list(disable)
    if not todo:
        return xml
    root = ET.fromstring(xml)
    skills = root.find("Skills")
    if skills is None:
        return xml
    active_set = skills.get("activeSkillSet") or "1"
    skill_set = next((x for x in skills.findall("SkillSet") if x.get("id") == active_set), None)
    groups_xml = skill_set.findall("Skill") if skill_set is not None else skills.findall("Skill")
    for index, name, occurrence in todo:
        if not 1 <= index <= len(groups_xml):
            continue
        copies = [g for g in groups_xml[index - 1].findall("Gem") if g.get("enabled", "true") == "true" and g.get("nameSpec") == name]
        if occurrence < len(copies):
            copies[occurrence].set("enabled", "false")
    return ET.tostring(root, encoding="unicode")


def drop_over_cap_gems(pob: PobSession, skeleton: Skeleton, main_index: int, *, rails: Rails | None = None) -> list[str]:
    """gm-links (#426): a group over its link cap loses supports PoB scores least, not the last ones.

    Repeatedly, among the group's support gems (never index 0 of the main link; the skeleton's
    `fixed_supports` stay), each one is disabled alone (the gem-level `enabled` flag, as
    `drop_over_limit_gems` does) and the objective's own stat read; the gem whose loss costs least
    goes, until the group is at its cap. A tie goes to the gem nearest the end. A group PoB cannot
    address (`source_index` 0) or one with no droppable support is left to `Skeleton.cap_links`
    (end-trim). The build PoB holds is restored exactly. Returns one log line per dropped gem."""

    from junkroan.optimizer.objective_select import objective_for
    from junkroan.search.hypothesis import active_gems

    rails = rails or Rails.load()
    actives = active_gems()

    def is_support(name: str) -> bool:
        key = str(name).strip().lower()
        return key not in actives and not key.startswith("vaal ")

    # (group index in the export, gems list the group owns, cap, protected names)
    targets: list[tuple[int, list[str], int, Sequence[str]]] = []
    if skeleton.main_link and len(skeleton.main_link) > rails.gems.main_link_max:
        targets.append((main_index, skeleton.main_link, rails.gems.main_link_max, skeleton.fixed_supports))
    for group in skeleton.extra_groups:
        if group.source_index and len(group.gems) > rails.gems.other_link_max:
            targets.append((group.source_index, group.gems, rails.gems.other_link_max, ()))
    if not targets:
        return []
    state = pob.export_xml()
    lines: list[str] = []
    try:
        key = objective_for(rails, skeleton.main_link[0]).maximize if skeleton.main_link else "CombinedDPS"
        pob.load_xml(state)
        base = pob.stats((key,)).get(key)
        if not isinstance(base, (int, float)) or isinstance(base, bool) or float(base) <= 0.0:
            key = "CombinedDPS"

        def read(off: list[tuple[int, str, int]]) -> float:
            pob.load_xml(xml_with_group_gems_disabled(state, off))
            value = pob.stats((key,)).get(key)
            return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0

        off: list[tuple[int, str, int]] = []
        for index, gems, cap, protected in targets:
            label = gems[0]
            while len(gems) > cap:
                candidates = [i for i in range(len(gems) - 1, 0, -1) if is_support(gems[i]) and gems[i] not in protected]
                if not candidates:
                    break
                with_gem = read(off)
                best: tuple[float, int, int] | None = None  # (value without, position, occurrence)
                for i in candidates:  # nearest the end first: a strict > below keeps it on a tie
                    occurrence = gems[:i].count(gems[i])
                    value = read(off + [(index, gems[i], occurrence)])
                    if best is None or value > best[0]:
                        best = (value, i, occurrence)
                assert best is not None
                without, i, occurrence = best
                name = gems.pop(i)
                off.append((index, name, occurrence))
                lines.append(f"skeleton: gm-links cap: dropped {name} from group {label} ({key} {with_gem:,.0f} with, {without:,.0f} without)")
    finally:
        pob.load_xml(state)
    return lines


@lru_cache(maxsize=1)
def _base_patterns() -> list[tuple[str, re.Pattern[str]]]:
    """Every item base PoB knows, longest name first: a magic item's name carries its base
    between the affixes ("Virile Ruby Ring of Craft"), and the longest match is the base
    ("Ruby Ring", never "Ring")."""

    from junkroan.pob.game_corpus import load_game_corpus_bundle

    names = sorted({str(r["name"]) for r in load_game_corpus_bundle("items")["records"] if r.get("name")}, key=len, reverse=True)
    return [(n, re.compile(r"\b" + re.escape(n) + r"\b", re.IGNORECASE)) for n in names]


def base_of_item_name(name_line: str) -> str | None:
    """The base item behind an item's name line, or None when PoB's corpus knows no such base."""

    for base, pattern in _base_patterns():
        if pattern.search(name_line):
            return base
    return None


def ascendancy_from_nodes(node_ids: Iterable[int], class_name: str | None = None) -> str | None:
    """The PoB ascendancy id the allocated ascendancy nodes belong to, or None.

    A guide PoB can carry allocated ascendancy nodes with no ascendancy class set: the 3.26
    Righteous Fire Chieftain exports `ascendClassName="None"` because the spec the author left
    active is their level 1-20 one, while its six allocated ascendancy nodes are all Chieftain's.
    `Skeleton.apply` would then call `set_tree(ascendancy_id="None")` and the build would lose the
    ascendancy entirely. The nodes are the evidence: the corpus maps each to the ascendancy that
    owns it, and the one owning the most of them wins (nodes of another class are ignored when
    `class_name` is given)."""

    from junkroan.search.hypothesis import ascendancies

    owner: dict[int, str] = {}
    for record in ascendancies().values():
        if class_name and (record.get("class_name") or "").lower() != class_name.strip().lower():
            continue
        for node in record.get("nodes") or []:
            owner[int(node["node_id"])] = str(record["ascendancy_id"])
    votes: dict[str, int] = {}
    for node_id in node_ids:
        if name := owner.get(int(node_id)):
            votes[name] = votes.get(name, 0) + 1
    return max(votes, key=lambda name: (votes[name], name)) if votes else None


def _fixed_ascendancy_nodes(asc_nodes: list[int], ascendancy: str, ascendancy_node_names: dict[int, str] | None, emit) -> list[int]:
    """`asc_nodes`, with any id that is not a node of `ascendancy` at the tree version our build
    uses remapped by node NAME within that same ascendancy (exactly one match) or dropped
    (spec 2026-09-22, requirement 2: a node id can survive a tree conversion as a real id that
    now belongs to an unrelated ascendancy or Atlas tree -- z328_hierophant_kinetic_fusillade's
    node 43376, a Hierophant node in its own 3.28 tree, is Aul's Atlas-tree "The King's Heritage"
    at the pinned tree version our own corpus reads, so a global "is this an ascendancy node id at
    all" check passes it while the selected-ascendancy check `set_tree` runs does not)."""

    from junkroan.search.hypothesis import ascendancies, ascendancy_aliases

    key = ascendancy_aliases().get(ascendancy.strip().lower(), ascendancy) if ascendancy and ascendancy != "None" else None
    record = ascendancies().get(str(key).lower()) if key else None
    if record is None:
        return asc_nodes  # no ascendancy selected, or one our corpus does not carry: nothing to check against
    by_id = {int(n["node_id"]): str(n.get("name") or "") for n in (record.get("nodes") or []) if not n.get("is_ascendancy_start")}
    fixed: list[int] = []
    for node_id in asc_nodes:
        if node_id in by_id:
            fixed.append(node_id)
            continue
        old_name = (ascendancy_node_names or {}).get(node_id)
        matches = sorted({nid for nid, name in by_id.items() if old_name and name.lower() == old_name.lower()})
        if len(matches) == 1:
            emit(f"fixture ascendancy node {node_id} '{old_name}' -> {matches[0]}")
            fixed.append(matches[0])
        else:
            emit(f"fixture ascendancy node {node_id} '{old_name or '?'}' -> dropped")
    return fixed


def _filtered_uniques(uniques: dict[str, str], unique_item_bases: dict[str, str], bases: dict[str, str], rails: Rails, emit) -> None:
    """Drop a unique our uniques corpus does not know, or that `Rails.unique_allowed` rejects for
    being drop-disabled (availability "legacy"), from OUR skeleton (`uniques`, `bases` mutated in
    place); the slot becomes a rare slot on the author's own item base when our item corpus knows
    that base, else it is left for the filler's own choice (spec 2026-09-22, requirements 3-4).
    The AUTHOR's side is untouched: it is built from the raw fixture XML directly, never through
    this lookup.

    Requirement 3 reads "our uniques corpus knows it AND `Rails.unique_allowed` accepts it"
    literally, which would ALSO drop a unique `unique_allowed` rejects for being a non-legacy
    availability the day-1 rails do not screen for (measured: two Necromancer references, both
    carrying "Darkness Enthroned", availability "boss" -- the audit's own "unique outside the
    rails" is only ever a WARNING for that case, `legacy` is the one it raises as an ERROR). That
    would break requirement 6 ("no other skeleton may change"; measured, both a full and a
    legacy-only pass -- see the final report). This is the narrower, requirement-6-compatible
    reading: only "unknown to our corpus" and "legacy" (`Rails.unique_allowed` already rejects
    both, by construction) leave the skeleton; a unique merely outside the day-1 rails by
    availability/level/tier is left exactly as the audit already treats it, a warning, unchanged
    by this function. A decision the spec's two statements left open, not a game-mechanics call:
    flagged in the final report for the lead."""

    from junkroan.optimizer.item_bases import base_record
    from junkroan.search.hypothesis import uniques_by_name

    for slot, name in list(uniques.items()):
        records = uniques_by_name().get(name.strip().lower())
        record = records[0] if records else None
        if record is None:
            reason = "unknown to our uniques corpus"
        elif record.get("availability", "core") == "legacy":
            assert not rails.unique_allowed(record)  # legacy is never in an allowed-availability list
            reason = "legacy: no longer obtainable"
        else:
            continue  # known to our corpus and not drop-disabled: kept, even if outside the rails otherwise (the audit's own warning, not ours to fix here)
        del uniques[slot]
        fallback_base = (record.get("base") if record is not None else None) or unique_item_bases.get(slot)
        if fallback_base and base_record(fallback_base) is not None:
            bases[slot] = fallback_base
        emit(f"fixture unique dropped from our skeleton: {slot}: {name} ({reason})")


def skeleton_from_xml(xml: str, pob: PobSession | None = None, log=None, *, rails: Rails | None = None,
                       ascendancy_node_names: dict[int, str] | None = None,
                       allocated_after_convert: set[int] | None = None) -> Skeleton:
    """The author's skeleton: class, ascendancy, keystones, links, uniques, rare bases.

    `pob` must already hold this build; then PoB itself says which of the author's supports
    apply to nothing, and those are dropped as well (the user, 2026-09-18: a skeleton carries
    nothing that supports nothing), and gems of a limited family above their limit (golems above
    `ActiveGolemLimit`, curses, marks included, above `EnemyCurseLimit`) are cut down to the subset PoB scores best
    (`drop_over_limit_gems`). Without it the derivation is pure XML and corpora.

    `rails` (default `Rails.load()`) judges the uniques this OWN skeleton keeps: a unique our
    uniques corpus does not know, or that `Rails.unique_allowed` rejects (legacy/drop-disabled,
    outside availability/level/tier), leaves the skeleton -- the slot becomes a rare slot on the
    author's own item base (or the filler's own choice when even that base is not one PoB's item
    corpus knows). The AUTHOR's own build is unaffected: it is loaded from raw XML text, never
    through this lookup.

    `ascendancy_node_names` ({node id -> display name} of the fixture's OWN pre-conversion tree,
    from `prepare_author`) lets an ascendancy node id that does not exist in the SELECTED
    ascendancy at the tree version our build uses (an id can mean an entirely different node at
    the current tree, or belong to a same-named node under a new id after a tree rework) be
    remapped by node name within the same ascendancy when exactly one node there has that name,
    or dropped otherwise (spec 2026-09-22, requirement 2).

    `allocated_after_convert` is the set of node ids the author's build still has allocated after
    `pob.convert_tree()` (read by `prepare_author` from PoB right after the first load). This XML is
    the PRE-conversion export, so an ascendancy node it lists can have been dropped by the
    conversion (no path to the class start on the current tree): our skeleton must not carry an id
    PoB no longer allocates, or `set_tree` paths through the missing prerequisite and the build
    ends over the ascendancy limit (z325_berserker_ground_slam_autocry: 9 nodes against the rails'
    8). When given, every ascendancy node id not in the set leaves the skeleton, one log line each;
    `None` (the default, every other caller) keeps today's behaviour."""

    emit = log or (lambda _m: None)
    root = ET.fromstring(xml)
    build = root.find("Build")
    graph = TreeGraph.load()
    nodes = parse_allocated_from_xml(xml)
    from junkroan.pob.tree_payload_normalization import canonical_active_tree_corpus

    corpus = canonical_active_tree_corpus()
    asc_ids = {int(n) for n in corpus["ascendancy_node_ids"]}
    proxies = {int(n) for n in corpus["start_root_proxy_node_ids"]}
    asc_nodes = [n for n in nodes if n in asc_ids and n not in proxies]
    keystones = [n for n in nodes if graph.node(n) and graph.node(n).kind == "keystone"]

    ascendancy = build.get("ascendClassName") or "None"
    if ascendancy in ("", "None") and asc_nodes:
        if inferred := ascendancy_from_nodes(asc_nodes, build.get("className")):
            emit(f"skeleton: ascendancy read from the {len(asc_nodes)} allocated ascendancy nodes: {inferred} "
                 f"(the build's ascendClassName is \"None\")")
            ascendancy = inferred

    if allocated_after_convert is not None:
        still_allocated: list[int] = []
        for node_id in asc_nodes:
            if node_id in allocated_after_convert:
                still_allocated.append(node_id)
                continue
            name = (ascendancy_node_names or {}).get(node_id) or "?"
            emit(f"fixture ascendancy node {node_id} '{name}' dropped: not allocated after tree conversion")
        asc_nodes = still_allocated

    asc_nodes = _fixed_ascendancy_nodes(asc_nodes, ascendancy, ascendancy_node_names, emit)

    main_index = int(build.get("mainSocketGroup") or 1)
    main_link, main_slot, extra = socket_groups_from_xml(root.find("Skills"), main_index)

    items = root.find("Items")
    by_id = {i.get("id"): i for i in items.findall("Item")}
    iset = next((s for s in items.findall("ItemSet") if s.get("id") == (items.get("activeItemSet") or "1")), None)
    slots = iset.findall("Slot") if iset is not None else items.findall("Slot")
    # PoB writes <Slot> in Lua pairs() order (undefined, differs per process); a fixed order keeps the
    # dicts below, and so the PoB call sequence and the seeded base draws, the same (#493)
    from junkroan.optimizer.loot_gear import ordered_slots

    rank = {n: i for i, n in enumerate(ordered_slots(sorted({s.get("name") or "" for s in slots})))}
    slots = sorted(slots, key=lambda s: rank[s.get("name") or ""])
    uniques: dict[str, str] = {}
    unique_item_bases: dict[str, str] = {}  # slot -> the author's own item base line, a fallback rare base (req 3)
    bases: dict[str, str] = {}
    sockets: dict[str, str] = {}
    flasks: dict[str, str] = {}
    jewels: dict[str, str] = {}
    for slot in slots:
        name, item_id = slot.get("name"), slot.get("itemId")
        if not name or item_id in (None, "0") or item_id not in by_id or "Swap" in name:
            continue
        text = "\n".join(l.strip() for l in (by_id[item_id].text or "").splitlines() if l.strip())
        lines = text.splitlines()
        rarity = next((l.split(":", 1)[1].strip().upper() for l in lines if l.startswith("Rarity:")), "")
        socket_line = next((l.split(":", 1)[1].strip() for l in lines if l.startswith("Sockets:")), None)
        if name.startswith("Flask"):
            flasks[name] = text
        elif "Abyssal" in name or "Jewel" in name or rarity in ("MAGIC",) and "Jewel" in lines[2]:
            jewels[name] = text
        elif rarity == "UNIQUE":
            uniques[name] = lines[1]
            unique_item_bases[name] = lines[2]
        elif rarity == "RARE":
            bases[name] = lines[2]
            if socket_line:
                sockets[name] = socket_line
        else:
            # only rares are rolled and only uniques are fixed (the user, 2026-09-18): a MAGIC or
            # NORMAL item of the author's is a slot they had not finished, so it becomes a rare slot
            # on its own base and the loot fills it. Carried as-is it was a leak of the author's gear
            # (vd_spellslinger s3 wore their "Virile Ruby Ring of Craft" through the whole run)
            base = base_of_item_name(lines[1])
            if base is None:  # a base PoB's corpus does not name: carry it rather than lose the slot
                jewels[name] = text
                continue
            bases[name] = base
            if socket_line:
                sockets[name] = socket_line
    _filtered_uniques(uniques, unique_item_bases, bases, rails or Rails.load(), emit)
    skeleton = Skeleton(
        class_name=build.get("className"), ascendancy=ascendancy, level=int(build.get("level") or 77),
        ascendancy_nodes=asc_nodes, keystones=keystones, main_link=main_link, main_slot=main_slot, extra_groups=extra,
        uniques=uniques, rare_bases=bases, sockets=sockets, flasks=flasks, jewels=jewels,
        bandit=(rails or Rails.load()).bandit, pantheon_major=build.get("pantheonMajorGod") or "None", pantheon_minor=build.get("pantheonMinorGod") or "None",
    )
    if pob is not None:
        skeleton.pure_es = is_pure_es(pob.stats(("Life", "EnergyShield", "ChaosInoculation")))
        for line in drop_unsupported_gems(pob, skeleton, main_index):
            emit(f"skeleton: dropped {line}")
        for line in drop_over_limit_gems(pob, skeleton):
            emit(line)
        for line in drop_over_cap_gems(pob, skeleton, main_index, rails=rails):
            emit(line)
    for line in skeleton.cap_links(rails):
        emit(f"skeleton: {line} (gm-links cap)")
    skeleton.aura_levels = aura_levels_from_xml(root.find("Skills"), skeleton, main_index, (rails or Rails.load()).gems.level)
    skeleton.gem_minion_skills = minion_skills_from_xml(root.find("Skills"), skeleton, main_index)
    return skeleton


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-fixture")
    ap.add_argument("--skeleton")
    ap.add_argument("--reopt-rounds", type=int, default=3, help="no-op since D58: the loop is the pipeline")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--gear", choices=("loot", "wishlist"), default="loot", help="day-1 gear model")
    ap.add_argument("--construction", choices=("classic", "rig-first"), default="classic", help="construction order")
    ap.add_argument("--author-floors", action="store_true", help="use the author's own life/EHP/resists as floors instead of the rails (fair comparison)")
    ap.add_argument("--record-calls", metavar="DIR", help="record every PoB call to DIR/skeleton-<tag>.calls.jsonl (the refactor proof of #35)")
    ap.add_argument("--loop-passes", type=int, metavar="N", help="the improvement loop's pass limit (default: the pipeline's)")
    ap.add_argument("--no-loop-time-cap", action="store_true", help="no time budget for the improvement loop: a proof run is not cut by the clock")
    args = ap.parse_args()
    loop_kwargs: dict = {}
    if args.loop_passes is not None:
        loop_kwargs["loop_max_passes"] = args.loop_passes
    if args.no_loop_time_cap:
        loop_kwargs["loop_max_seconds"] = None
    if args.from_fixture:
        xml = decode_import_code((FIXTURES / f"{args.from_fixture}.pob.txt").read_text(encoding="utf-8").strip())
        skeleton = None  # derived inside the session: PoB itself judges which of the author's supports apply to nothing
        tag = args.from_fixture
    else:
        skeleton = Skeleton.from_json(Path(args.skeleton).read_text(encoding="utf-8"))
        xml = None
        tag = Path(args.skeleton).stem
    rails = Rails.load()
    with PobSession(run_id=f"skeleton-{tag}") as session:
        recorder = None
        if args.record_calls:
            from junkroan.recording_pob import RecordingPob

            recorder = RecordingPob(session, Path(args.record_calls) / f"skeleton-{tag}.calls.jsonl")
        pob = recorder if recorder is not None else session
        author = None
        if xml:
            pob.load_xml(xml)
            # the fixture declares its own tree version (3_25-3_28 on 36 of the 37 references) and PoB
            # keeps it; our build is grown on PoB's latest tree, so the author is converted onto it
            # before anything is read off them. Node ids are additive, so nothing should be lost.
            conv = pob.convert_tree()
            print(f"author tree {conv['from']} -> {conv['to']}: {conv['nodes_after']} nodes, {len(conv['lost_node_ids'])} lost"
                  + (f" {conv['lost_node_ids']}" if conv["lost_node_ids"] else ""))
            skeleton = skeleton_from_xml(xml, pob=pob, log=print)
            author = pob.stats(REPORT_KEYS)
            print(f"author: dps={author['CombinedDPS']:,.0f} life={author['Life']} ehp={author['TotalEHP']:,.0f}")
        print("skeleton:", json.dumps({"class": f"{skeleton.class_name}/{skeleton.ascendancy}", "level": skeleton.level, "keystones": skeleton.keystones, "asc_nodes": len(skeleton.ascendancy_nodes),
                                       "main_link": skeleton.main_link, "extra_groups": len(skeleton.extra_groups), "uniques": skeleton.uniques, "rare_bases": skeleton.rare_bases}, ensure_ascii=False))
        objective = None
        if author and args.author_floors:
            from junkroan.optimizer.objective import Objective, max_hit_floors
            ms = pob.stats(("EffectiveMovementSpeedMod",)).get("EffectiveMovementSpeedMod") or 1.0
            objective = Objective(maximize="CombinedDPS", floors={"Life": author["Life"] * 0.97, **max_hit_floors(author),
                                                                  "EffectiveMovementSpeedMod": min(float(ms), rails.movement_speed_floor or float(ms))}, relations=rails.objective().relations)
            print("objective:", objective.describe())
        pipeline = BuildPipeline(pob, rails, objective=objective, log=print, construction=args.construction)
        points = None
        if xml:
            graph = TreeGraph.load()
            points = len([n for n in parse_allocated_from_xml(xml) if n in graph.allocatable])
        try:
            result = pipeline.run(skeleton, tree_points=points, seed=args.seed, gear_mode=args.gear, **loop_kwargs)
        finally:
            if recorder is not None:
                recorder.close_recording()
                print(f"recorded {recorder.recorded_calls} PoB calls to {Path(args.record_calls) / f'skeleton-{tag}.calls.jsonl'}")
                write_saved_lists(Path(args.record_calls) / f"skeleton-{tag}.lists.json")  # #978: the saved lists this run started with
    print("\n" + result.summary())
    if author:
        print(f"vs author: {result.final_stats['CombinedDPS'] / author['CombinedDPS']:.1%} of CombinedDPS under the rails config")
    out_dir = Path(__file__).resolve().parents[1] / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"skeleton-{tag}.pob.txt").write_text(result.import_code, encoding="utf-8")
    (out_dir / f"skeleton-{tag}.json").write_text(json.dumps({
        "skeleton": json.loads(skeleton.to_json()), "author": author, "final": result.final_stats, "conservative": result.conservative_stats,
        "optimistic": result.optimistic_stats, "stages": [{"name": s.name, "seconds": s.seconds, "value": s.score_value, "violation": s.violation, "notes": s.notes} for s in result.stages],
        "config_reasons": result.config_reasons, "seconds": result.seconds,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"saved artifacts/skeleton-{tag}.pob.txt")
    pob_dir = Path.home() / "Documents" / "Path of Building" / "Builds"
    if pob_dir.is_dir():
        target = pob_dir / "Junkroan"
        target.mkdir(exist_ok=True)
        (target / f"junkroan {tag}.xml").write_text(result.xml, encoding="utf-8")
        print(f"saved to PoB builds: {target / f'junkroan {tag}.xml'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
