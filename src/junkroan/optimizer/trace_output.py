"""Option classes of a delivered build, read from its PoB XML (#498)."""

from __future__ import annotations

import functools
import re
from xml.etree import ElementTree as ET

from junkroan.optimizer.flask_trace import MANA_FLASK_MARKERS, UTILITY_CRAFT_CLASS
from junkroan.optimizer.trace import output_counts


def _group_sizes(root: ET.Element) -> dict[int, int]:
    """Delivered skill groups of the active skill set by their enabled gem count (empty groups skipped)."""

    skills = root.find("Skills")
    if skills is None:
        return {}
    sets = skills.findall("SkillSet")
    active = skills.get("activeSkillSet") or "1"
    holder = next((s for s in sets if s.get("id") == active), sets[0] if sets else skills)
    sizes: dict[int, int] = {}
    for skill in holder.findall("Skill"):
        if skill.get("enabled") == "false":
            continue
        n = sum(1 for g in skill.findall("Gem") if g.get("enabled") != "false")
        if n:
            sizes[n] = sizes.get(n, 0) + 1
    return sizes


def _fill_count(root: ET.Element) -> int | None:
    """#1156: the enabled delivered socket groups, the main one excluded, whose first enabled gem is one the fill step may
    offer (`fill_candidate_names`: aura, guard, herald or buff gems); None when there is no Skills section."""

    from junkroan.search.generator import fill_candidate_names  # lazy: the generator imports the optimizer

    skills = root.find("Skills")
    if skills is None:
        return None
    sets = skills.findall("SkillSet")
    active = skills.get("activeSkillSet") or "1"
    holder = next((s for s in sets if s.get("id") == active), sets[0] if sets else skills)
    build = root.find("Build")
    main = int(build.get("mainSocketGroup") or 1) if build is not None else 1
    names = fill_candidate_names()
    count = 0
    for index, skill in enumerate(holder.findall("Skill"), start=1):
        if index == main or skill.get("enabled") == "false":
            continue
        gems = [g.get("nameSpec") or "" for g in skill.findall("Gem") if g.get("enabled") != "false"]
        count += bool(gems) and gems[0] in names
    return count


def _mod_count(explicit: list[str], candidates) -> int:
    """Mods the explicit lines make up, matched against the jewel candidates the way `scripts/check_jewels.py` does;
    a line that matches none counts as one mod of its own."""

    plain = [re.sub(r"^(?:\{[^}]*\})+", "", ln) for ln in explicit]
    by_first: dict[str, list[tuple[str, ...]]] = {}
    for c in candidates:
        by_first.setdefault(c.lines[0], []).append(tuple(c.lines))
        if c.template_lines:
            by_first.setdefault(c.template_lines[0], []).append(tuple(c.template_lines))
    mods, i = 0, 0
    while i < len(plain):
        step = 1
        for lines in by_first.get(plain[i], []):
            if tuple(plain[i:i + len(lines)]) == lines:
                step = len(lines)
                break
        i += step
        mods += 1
    return mods


def _jewel_counts(root: ET.Element, spec: ET.Element | None, nodes: list[int], candidates) -> dict[str, int]:
    """#434: the tree-socketed jewels of the active spec: `jewels:<n>`, `jewel-base:<base>`, `jewel-mods:<n>`, `jewel-socket:unallocated`."""

    if spec is None:
        return {}
    items = {i.get("id"): i.text or "" for i in root.findall("./Items/Item")}
    held = {n for n in nodes}
    counts: dict[str, int] = {}

    def bump(key: str) -> None:
        counts[key] = counts.get(key, 0) + 1

    total = 0
    for sock in spec.findall("./Sockets/Socket"):
        if (sock.get("itemId") or "0") == "0":
            continue
        total += 1
        lines = [ln.strip() for ln in items.get(sock.get("itemId"), "").strip().splitlines() if ln.strip()]
        base = lines[2] if len(lines) > 2 else "?"
        explicit: list[str] = []
        for i, ln in enumerate(lines):
            if ln.startswith("Implicits:"):
                explicit = lines[i + 1 + int(ln.split(":")[1]):]
                break
        bump(f"jewel-base:{base}")
        bump(f"jewel-mods:{_mod_count(explicit, candidates)}")
        if int(sock.get("nodeId") or 0) not in held:
            bump("jewel-socket:unallocated")
    if total:
        counts[f"jewels:{total}"] = 1
    return counts


def _flask_base_names() -> frozenset[str]:
    try:
        from junkroan.optimizer.flask_lines import flask_bases
        return frozenset(b.name for b in flask_bases(100)) | {"Divine Life Flask"}
    except Exception:
        return frozenset({"Divine Life Flask"})


@functools.cache
def _flask_base_kinds() -> dict[str, str]:
    """Flask base name -> kind ("life" | "mana" | "hybrid" | "utility" | "tincture") from the flask base data."""

    try:
        from junkroan.optimizer.flask_lines import flask_bases
        return {b.name: b.kind for b in flask_bases(100)}
    except Exception:
        return {}


def _utility_base(raw: str) -> str | None:
    """#616: the utility flask base a raw item is of, or None. The base is the longest known flask base name found as whole
    words in the name line (a magic flask carries affix words: "Bountiful Ruby Flask of the Curlew"), for a rare/unique
    in the base line after it."""

    lines = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
    if len(lines) < 2 or not lines[0].startswith("Rarity:"):
        return None
    rarity = lines[0].partition(":")[2].strip().upper()
    line = lines[2] if rarity in ("RARE", "UNIQUE") and len(lines) > 2 else lines[1]
    kinds = _flask_base_kinds()
    found = [n for n in kinds if re.search(rf"(?<!\w){re.escape(n)}(?!\w)", line)]
    if not found:
        return None
    name = max(found, key=len)
    return name if kinds[name] == "utility" else None


def _is_bare(raw: str) -> bool:
    """#596: a flask with no prefix and no suffix: Rarity NORMAL, or Rarity MAGIC whose name line is exactly a flask base
    name and which has no `Prefix:`/`Suffix:` line naming a mod (a game-import magic flask carries affix words in its name)."""

    lines = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
    rarity = lines[0].partition(":")[2].strip().upper() if lines and lines[0].startswith("Rarity:") else ""
    if rarity == "NORMAL":
        return True
    if rarity != "MAGIC" or len(lines) < 2 or lines[1] not in _flask_base_names():
        return False
    for ln in lines:
        head, sep, val = ln.partition(":")
        if sep and head in ("Prefix", "Suffix") and val.strip() not in ("", "None"):
            return False
    return True


def _is_utility(raw: str) -> bool:
    """#1162: the raw is a utility flask base (kind "utility"): not Life, Mana or Hybrid, not a tincture."""

    base = _utility_base(raw)
    return base is not None and _flask_base_kinds().get(base) == "utility"


def _flask_counts(slots, by_id, uptimes) -> dict[str, int]:
    """#575: `flask-active` = Flask slots holding an item with active="true"; `flask-active-uptime-below-100` = those
    active while `uptimes[slot]["full"]` is False; written (0 included) only when a Flask slot holds an item, the
    second only when `uptimes` is not None. #589: `flask-slot-empty` = slots `Flask 1`..`Flask 5` holding no item (absent
    slot, itemId 0/missing or an id not in the item list), and `flask-divine-life` = held Flask slots whose raw text
    contains `Divine Life Flask`; both always written (0 included). #616: `flask-duplicate-base-output` = held Flask slots
    whose item is a utility base already held in an earlier Flask slot; always written."""

    held = [s for s in slots if (s.get("name") or "").startswith("Flask")
            and s.get("itemId") not in (None, "0") and s.get("itemId") in by_id]
    filled = {s.get("name") for s in held}
    counts = {
        "flask-slot-empty": sum(1 for n in range(1, 6) if f"Flask {n}" not in filled),
        "flask-divine-life": sum(1 for s in held if "Divine Life Flask" in by_id[s.get("itemId")]),
        "flask-bare-base-output": sum(1 for s in held if _is_bare(by_id[s.get("itemId")])),
    }
    # #616: held Flask slots whose item is a utility base already held in an earlier Flask slot (three Rubies = 2)
    seen: set[str] = set()
    dup = 0
    for s in sorted(held, key=lambda x: x.get("name") or ""):
        base = _utility_base(by_id[s.get("itemId")])
        if base is not None:
            dup += base in seen
            seen.add(base)
    counts["flask-duplicate-base-output"] = dup
    if not held:
        return counts
    active = [s for s in held if (s.get("active") or "").lower() == "true"]
    counts["flask-active"] = len(active)
    # #1162: an active utility flask (a base that is not Life / Mana / Hybrid) in the delivered build; day 1 must give 0
    counts[UTILITY_CRAFT_CLASS] = sum(1 for s in active if _is_utility(by_id[s.get("itemId")]))
    if uptimes is not None:
        counts["flask-active-uptime-below-100"] = sum(
            1 for s in active if not (uptimes.get(s.get("name")) or {}).get("full", True))
        # #604: an active Mana/Hybrid Flask below 100 % uptime is a flask the mana sustain rail must not count
        counts["mana-sustain-inactive-flask"] = sum(
            1 for s in active
            if not (uptimes.get(s.get("name")) or {}).get("full", True)
            and any(m in by_id[s.get("itemId")] for m in MANA_FLASK_MARKERS))
    return counts


def trace_output_from_xml(xml: str, *, jewel_candidates=None, flask_uptimes=None) -> dict[str, int]:
    """`output_counts` over the equipped items (flasks and jewels included) and the active spec's nodes; {} on any failure.

    `flask_uptimes` (#575, `PobSession.flask_uptimes()`: slot -> {"full": bool, ...}) is optional; when None no
    `flask-active-uptime-below-100` output count is written (`flask-active` always is, read from the XML)."""

    try:
        root = ET.fromstring(xml)
        raws: list[str] = []
        flask_counts: dict[str, int] = {}
        items = root.find("Items")
        if items is not None:
            by_id = {i.get("id"): i.text or "" for i in items.findall("Item")}
            active = items.get("activeItemSet") or "1"
            item_set = next((s for s in items.findall("ItemSet") if s.get("id") == active), None)
            slots = item_set.findall("Slot") if item_set is not None else items.findall("Slot")
            for slot in slots:
                iid = slot.get("itemId")
                if iid not in (None, "0") and iid in by_id:
                    raws.append(by_id[iid])
            flask_counts = _flask_counts(slots, by_id, flask_uptimes)
        nodes: list[int] = []
        spec = None
        tree = root.find("Tree")
        if tree is not None:
            specs = tree.findall("Spec")
            idx = int(tree.get("activeSpec") or "1") - 1
            if specs:
                spec = specs[idx] if 0 <= idx < len(specs) else specs[0]
                nodes = [int(n) for n in (spec.get("nodes") or "").split(",") if n.strip()]
        counts = dict(output_counts(raws, nodes))
        counts.update(flask_counts)
        if spec is not None and spec.find("./Sockets/Socket") is not None:
            try:  # the jewel counts never cost the build its other counts
                if jewel_candidates is None:
                    from junkroan.optimizer.jewel_lines import jewel_line_candidates
                    jewel_candidates = jewel_line_candidates()
                counts.update(_jewel_counts(root, spec, nodes, jewel_candidates))
            except Exception:
                counts["jewel-counts:unreadable"] = 1
        try:  # the fill count never costs the build its other counts
            filled = _fill_count(root)
        except Exception:
            filled = None
        if filled is not None:
            counts["fill-candidate"] = filled  # #1156: 0 included, so an absent group is a number read
        for size, n in _group_sizes(root).items():
            counts[f"links:{size}"] = n  # #426: delivered groups by gem count (every group, not only the main link)
        return counts
    except Exception:
        return {}
