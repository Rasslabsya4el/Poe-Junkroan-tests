"""#802 rules 2-3: at delivery every socketed gem that has a Vaal version is written as it, the Vaal half off.

The search chooses among plain gems; a Vaal version with `enable_global_1` false / `enable_global_2` true is the plain gem
(row 1 of the ticket: 0 outputs differ on 6 of 6). The swap is a rename in the build's gem list, level and quality as they
stand. A Vaal skill without a global effect is still an active skill beside the plain one, so each group's main skill is
kept by the name it had before the swap.
"""

from __future__ import annotations

from typing import Any, Callable
from xml.etree import ElementTree as ET

from junkroan.optimizer.trace import TRACE
from junkroan.optimizer.trace_gems import count_delivered_gem, count_generated
from junkroan.search.vaal_twin import vaal_twin

# the attributes that name a gem to PoB besides `nameSpec`; the harness's own skill writer leaves them out too
_GEM_IDENTITY = ("gemId", "skillId", "variantId")


def _active_set_groups(root: ET.Element) -> list[ET.Element]:
    skills = root.find("Skills")
    if skills is None:
        return []
    sets = skills.findall("SkillSet")
    if not sets:
        return skills.findall("Skill")
    wanted = skills.get("activeSkillSet") or "1"
    chosen = next((s for s in sets if s.get("id") == wanted), sets[0])
    return chosen.findall("Skill")


def _main_names(pob: Any) -> list[str | None]:
    """Per socket group of the active set, the name of its main active skill (None when it lists none)."""

    out: list[str | None] = []
    for group in (pob.read_state().get("skills_state") or {}).get("socket_groups") or []:
        entries = group.get("active_skill_entries") or []
        index = int(group.get("main_active_skill_index") or 1)
        out.append(str(entries[index - 1].get("name")) if 0 < index <= len(entries) else None)
    return out


def _active_names(pob: Any, group_index: int) -> list[str]:
    groups = (pob.read_state().get("skills_state") or {}).get("socket_groups") or []
    return [str(e.get("name")) for e in (groups[group_index].get("active_skill_entries") or [])] if group_index < len(groups) else []


def _position(raw: str | None) -> int:
    """PoB's loader: `tonumber(node.attrib.mainActiveSkill) or 1`; a nil position is saved as the string "nil"."""
    try:
        return int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1


def deliver_vaal_twins(pob: Any, objective: Any, log: Callable[[str], None], *, level_rail: int, quality_rail: int) -> list[tuple[str, str]]:
    """Write every gem with a Vaal version as it; returns the (plain, Vaal) pairs written.

    The build is evaluated once more in that form: the objective before and after go to the log, and the Vaal and
    transfigured gems of the delivered build are counted at the PoB boundary (generated at the swap, evaluated by the
    stat read after it). Nothing is written when no gem has a twin, or when a group's main skill cannot be kept (the
    build is loaded back as it was)."""

    xml = pob.export_xml()
    root = ET.fromstring(xml)
    groups = _active_set_groups(root)
    before_names = _main_names(pob)
    if len(groups) != len(before_names):
        log(f"vaal delivery: skipped, {len(groups)} socket groups in the export against {len(before_names)} read from PoB")
        return []
    swapped: list[tuple[str, str, ET.Element]] = []
    for group in groups:
        for gem in group.findall("Gem"):
            twin = vaal_twin(gem.get("nameSpec") or "")
            if twin is None:
                continue
            swapped.append((gem.get("nameSpec"), twin, gem))
    if not swapped:
        return []
    before = objective.score(pob.stats(objective.stat_keys))
    for _plain, twin, gem in swapped:
        gem.set("nameSpec", twin)
        for attr in _GEM_IDENTITY:
            gem.attrib.pop(attr, None)
        gem.set("enableGlobal1", "false")
        gem.set("enableGlobal2", "true")
    pob.load_xml(ET.tostring(root, encoding="unicode"))

    fixed = False
    for index, (group, wanted) in enumerate(zip(groups, before_names)):
        if wanted is None:
            continue
        names = _active_names(pob, index)
        position = _position(group.get("mainActiveSkill"))
        if 0 < position <= len(names) and names[position - 1] == wanted:
            continue
        if wanted not in names:
            pob.load_xml(xml)
            log(f"vaal delivery: reverted, main skill {wanted!r} of group {index + 1} is not among {names} after the swap")
            return []
        group.set("mainActiveSkill", str(names.index(wanted) + 1))
        group.set("mainActiveSkillCalcs", str(names.index(wanted) + 1))
        fixed = True
    if fixed:
        pob.load_xml(ET.tostring(root, encoding="unicode"))
    if _main_names(pob) != before_names:
        pob.load_xml(xml)
        log(f"vaal delivery: reverted, main skills {_main_names(pob)} after the swap against {before_names}")
        return []

    pairs = [(plain, twin) for plain, twin, _gem in swapped]
    with TRACE.move("vaal delivery"):
        count_generated([twin for _plain, twin in pairs], role="gem")
        after = objective.score(pob.stats(objective.stat_keys))
        for _plain, twin, gem in swapped:
            count_delivered_gem(twin, level=int(gem.get("level") or 0), quality=int(gem.get("quality") or 0),
                                level_rail=level_rail, quality_rail=quality_rail)
    log(f"vaal delivery: {len(pairs)} of {len(swapped)} gems written as their Vaal version ({', '.join(f'{p} -> {t}' for p, t in pairs)}); "
        f"objective {before.value:,.4f} -> {after.value:,.4f}")
    return pairs
