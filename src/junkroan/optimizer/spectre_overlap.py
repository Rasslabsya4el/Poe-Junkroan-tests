"""Spectre-count multiplier for Volley links on a mortar spectre (#542, D62).

The record `mortar_spectre_volley_overlap` in `mechanics/pending_facts.json` says how many of a
Volley link's projectiles land on one boss target as separate mortar explosions. PoB multiplies a
spectre's FullDPS by its count only, so each lane the fact acts on scales the count by this number:
both lanes since the owner's word of 2026-10-16 (#1143, the fact is approved); only the optimistic
lane while it is pending.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping
from xml.etree import ElementTree

from junkroan.mechanics.pending_facts import applies, fact, would_move

FACT_ID = "mortar_spectre_volley_overlap"

# (gem, record param). The corpus writes these gem names without the " Support" suffix, a build's
# gem list may carry it; both spellings are read.
_VOLLEY_PARAMS = (("Greater Volley", "greater_volley_support"), ("Volley", "volley_support"))


def volley_overlap_multiplier(lane: str, support_names: Iterable[str], minion_skill_name: str | None) -> int:
    if not applies(FACT_ID, lane) or not minion_skill_name or "mortar" not in minion_skill_name.lower():
        return 1
    names = {n.strip().removesuffix(" Support").strip().lower() for n in support_names}
    record = fact(FACT_ID)
    for gem, key in _VOLLEY_PARAMS:
        if gem.lower() in names:
            value = record.param(key)
            return int(value) if value else 1
    return 1


# -- the PoB side (#542): read the delivered build, price the fact on its optimistic lane ------------


def _main_spectre(state: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]] | None:
    """(socket group, active skill entry, gem entry) of the main skill when it summons a minion
    whose active skill PoB names, else None. Every field is PoB's own read-back."""

    skills = state.get("skills_state") or {}
    main_id = skills.get("main_socket_group_id") or (state.get("build_state") or {}).get("main_socket_group_id")
    group = next((g for g in skills.get("socket_groups") or () if isinstance(g, Mapping) and g.get("socket_group_id") == main_id), None)
    if group is None:
        return None
    entries = group.get("active_skill_entries") or ()
    index = int(group.get("main_active_skill_index") or 1)
    if not 1 <= index <= len(entries) or not isinstance(entries[index - 1], Mapping):
        return None
    entry = entries[index - 1]
    if not entry.get("minion_skill_name"):
        return None
    gem = next((g for g in group.get("gems") or () if isinstance(g, Mapping) and g.get("gem_entry_id") == entry.get("source_gem_entry_id")), None)
    return (group, entry, gem) if gem is not None else None


# Collections PoB writes from Lua tables in hash order: every reopen of the same build reshuffles them
# (any `set_skills` does it too), so "the build did not move" compares them as sets. Gems, skills and
# skill sets are ordered by the player and stay as written.
_UNORDERED_PARENTS = ("Sockets", "Overrides", "ConfigSet")


def canonical_xml(xml_text: str) -> str:
    """`xml_text` with PoB's hash-ordered lists put in a fixed order: the passive `nodes` and
    `masteryEffects` of each Spec, the tree URL (rebuilt from them), and the children of the
    unordered parents. Two exports of the same build are equal in this form."""

    root = ElementTree.fromstring(xml_text)
    for el in root.iter():
        for key in ("nodes", "masteryEffects"):
            if key in el.attrib:
                el.set(key, ",".join(sorted(re.findall(r"\{[^}]*\}|[^,]+", el.get(key, "")))))
        if el.tag == "URL":
            el.text = ""
        if el.tag in _UNORDERED_PARENTS:
            kids = sorted(list(el), key=lambda k: ElementTree.tostring(k, encoding="unicode"))
            for kid in list(el):
                el.remove(kid)
            el.extend(kids)
    return ElementTree.tostring(root, encoding="unicode")


def _with_gem_count(xml_text: str, group_id: str, socket_index: int, gem_name: str, old: int, new: int) -> str:
    """`xml_text` with one gem's `count` attribute rewritten in place (a text edit of that one tag:
    nothing else of the build changes). The gem is found by the read-back's own address: the active
    skill set (PoB writes its resolved id into `Skills@activeSkillSet` on export), the socket group's
    number (`skills.main.socket_group.<n>`), the socket index; its name and old count must agree or
    this raises."""

    group_no = int(group_id.split(".")[-1])
    root = ElementTree.fromstring(xml_text)
    skills = root.find("Skills")
    skill_sets = list(skills.findall("SkillSet")) if skills is not None else []
    set_id = skills.get("activeSkillSet") if skills is not None else None
    scope = next((s for s in skill_sets if s.get("id") == set_id), None) if skill_sets else skills
    if scope is None:
        raise RuntimeError(f"spectre overlap: no SkillSet {set_id} in the build XML")
    gem = scope.findall("Skill")[group_no - 1].findall("Gem")[socket_index - 1]
    if gem.get("nameSpec") != gem_name or int(gem.get("count") or 1) != old:
        raise RuntimeError(f"spectre overlap: XML gem {gem.get('nameSpec')!r} x{gem.get('count')} is not the read-back gem {gem_name!r} x{old}")
    # the same tag in the text: the n-th `<Gem` of the n-th `<Skill` of the set
    start = 0
    if skill_sets:
        start = [m.start() for m in re.finditer(r"<SkillSet\b", xml_text)][skill_sets.index(scope)]
    from_skill = start + [m.start() for m in re.finditer(r"<Skill\b(?![Ss])", xml_text[start:])][group_no - 1]
    tag_start = from_skill + [m.start() for m in re.finditer(r"<Gem\b", xml_text[from_skill:])][socket_index - 1]
    tag_end = xml_text.index(">", tag_start)
    new_tag, hits = re.subn(r'\bcount="\d+"', f'count="{new}"', xml_text[tag_start:tag_end])
    if hits != 1:
        raise RuntimeError("spectre overlap: the gem tag does not carry exactly one count attribute")
    return xml_text[:tag_start] + new_tag + xml_text[tag_end:]


@dataclass(frozen=True)
class OverlapReading:
    """The delivered build read at the spectre count the fact scales it to. `conservative` is None while
    the fact does not act on that lane (pending); `note` says what the fact does (or would do) to the
    conservative number."""

    conservative: dict[str, Any] | None
    optimistic: dict[str, Any]
    note: str


def spectre_overlap_stats(pob: Any, conservative_stats: Mapping[str, Any] | None = None) -> OverlapReading | None:
    """Both lanes of the delivered build read with the spectre count scaled by the fact (#542, #1143).

    None when the main skill is no spectre with a mortar-type minion skill under a Volley link: no PoB
    call is made then beyond the state read. Otherwise the count is swapped once for c * m through the
    build XML (m = the link's projectile count, read from the lane the fact acts on; the optimistic read
    starts from the same derived count c, so it is never multiplied twice), both lanes are read, the
    original XML is loaded back and must export as it did before (`canonical_xml`: PoB reshuffles its
    hash-ordered lists on every reopen), or this raises: the delivered build and its exported XML do not move."""

    found = _main_spectre(pob.read_state())
    if found is None:
        return None
    group, entry, gem = found
    support_names = [str(s.get("name") or "") for s in entry.get("support_links") or () if isinstance(s, Mapping)]
    minion_skill = str(entry["minion_skill_name"])
    multiplier = volley_overlap_multiplier("optimistic", support_names, minion_skill)
    if multiplier <= 1:
        return None
    on_conservative = volley_overlap_multiplier("conservative", support_names, minion_skill) == multiplier
    count = max(1, int(gem.get("count") or 1))
    before = conservative_stats if conservative_stats is not None else pob.calc("baseline")
    snapshot = pob.export_xml()
    scaled = _with_gem_count(snapshot, str(group["socket_group_id"]), int(gem["socket_index"]), str(gem["gem_name"]), count, count * multiplier)
    try:
        pob.load_xml(scaled)
        optimistic = pob.calc("conditional")
        after = pob.calc("baseline")
    finally:
        pob.load_xml(snapshot)
    if canonical_xml(pob.export_xml()) != canonical_xml(snapshot):
        raise RuntimeError("spectre overlap: the exported XML moved after the count swap was undone")
    what = f"FullDPS at spectre count {count} -> {count * multiplier}"
    if on_conservative:
        note = _moved(float(before.get("FullDPS") or 0.0), float(after.get("FullDPS") or 0.0), what)
    else:
        note = would_move(FACT_ID, float(before.get("FullDPS") or 0.0), float(after.get("FullDPS") or 0.0), what)
    return OverlapReading(after if on_conservative else None, optimistic, note)


def _moved(before: float, after: float, what: str) -> str:
    """`would_move`'s counterpart for an approved fact: what the fact did to the conservative number."""

    rec = fact(FACT_ID)
    share = f"{(after - before) / abs(before) * 100.0:+.1f}%" if before else "from nothing"
    return rec.reason(f"moved the conservative number by {share} ({what} {before:,.0f} -> {after:,.0f})") if rec else ""
