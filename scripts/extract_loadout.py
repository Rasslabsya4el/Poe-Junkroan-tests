"""One loadout of a multi-loadout author PoB, written out as a single-loadout build.

A hand-written guide PoB (Zizaran / Maxroll league starters) carries several stages in one
file: an item set, a tree spec and a skill set per stage, linked by the author's own `{n}`
marker, by a shared title, or by nothing at all. The benchmark (`scripts/benchmark.py`,
`skeleton_from_xml`) reads one build: the active item set, the active spec, the active skill
set. This script reduces such a file to the stage asked for.

What is kept, and what PoB reads it as (vendor/pob/source, Classes/ItemsTab.lua,
Classes/SkillsTab.lua, Classes/TreeTab.lua):

* `<Items activeItemSet="1">` with the one chosen `<ItemSet id="1">`. `activeItemSet` is an
  item set **id**, so the kept set is renumbered to 1. `<Items useSecondWeaponSet>` is what
  PoB saves from the active set, so it follows the kept set.
* `<Tree activeSpec="1">` with the one chosen `<Spec>`. `activeSpec` is a **position** in the
  spec list (TreeTab: `self.specList[self.activeSpec]`), not an id; specs carry no id.
* `<Skills activeSkillSet="1">` with the one chosen `<SkillSet id="1">` (an id again).
* `<Config activeConfigSet="1">` with the one chosen `<ConfigSet id="1">` (an id again). A guide PoB
  carries a config set per stage as well, and they are not interchangeable: the Essence Drain
  build's "Slinger 28+" set holds the author's leveling crutch `+200% to all resistances`, its
  "ALTERNATIVE SETUP" set holds the custom mods of a Pact of Ghorr staff build. Which one belongs
  to the loadout is decided by title, then by the author's `{n}` markers (`choose_config_set`).
* `<Build level>`: the level the loadout is for, when one is known (the spec title, or the
  manifest). `characterLevelAutoMode` is then written "false", because PoB's auto mode
  (Build.lua `EstimatePlayerProgress`) otherwise overwrites the level with its own estimate
  from the allocated node count and the fixture's stated level would be a lie.
* `<Build mainSocketGroup>`: an index into the *active* skill set's socket groups. It is kept
  when it is in range and its group holds the build's main skill, and otherwise moved to the
  first group that does (the author's index points at the stage they left the file on).
* `<Item>` entries referenced by the kept item set's `<Slot itemId>` **and** by the kept
  spec's tree-jewel `<Sockets><Socket itemId>`. Everything else is dropped.

The loadout to cut is the manifest's `early_loadout`, never the word "early" in a title: in
zizaran_328/hierophant_shock_nova_archmage the set literally called "Early Game" is act 1 and the
first-maps set is "Early Mapping". A build whose `early_loadout` is null (no staged loadouts) is
skipped and named, and a kept spec under 60 allocated nodes is warned about: that is a leveling
tree, not a maps one.

Run:
    python scripts/extract_loadout.py                     # every zizaran_* fixture folder
    python scripts/extract_loadout.py --league 327        # one of them
    python scripts/extract_loadout.py juggernaut_boneshatter
    python scripts/extract_loadout.py --source path.pob.txt --out out.pob.txt \
        --item-set "Early Game" --spec "Level 68 - Merc Lab .*" --skill-set "Maps {1,2,3}" --level 68

Out: tests/fixtures/zizaran_<league>/early/<slug>.pob.txt (an import code), plus sources.json and
README.md per folder when the manifests drive the run.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Sequence
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from junkroan.pob.session import decode_import_code, encode_import_code  # noqa: E402

FIXTURE_ROOT = ROOT / "tests" / "fixtures"
# a kept spec below this many allocated nodes is a leveling tree, not the early-maps one the
# benchmark wants: the run says so out loud instead of quietly producing a level-20 reference
MIN_MAPS_NODES = 60


def league_folders(league: str | None = None) -> list[Path]:
    """The zizaran_<league> fixture folders holding a manifest, oldest first."""

    folders = sorted(p for p in FIXTURE_ROOT.glob("zizaran_*") if (p / "manifest.json").is_file())
    if league:
        wanted = f"zizaran_{league.replace('.', '').strip()}"  # "327" and "3.27" both name zizaran_327
        folders = [p for p in folders if p.name == wanted]
        if not folders:
            raise SystemExit(f"no fixture folder {wanted} under {FIXTURE_ROOT}")
    return folders


# PoB colour escapes in a title: "^4Early Game {1}", "^xFF0000Endgame"
_COLOUR = re.compile(r"\^(?:x[0-9a-fA-F]{6}|[0-9])")
# the authors' own loadout marker: "Endgame {2,4}" belongs to stages 2 and 4
_MARKER = re.compile(r"\{\s*(\d+(?:\s*,\s*\d+)*)\s*\}")


def plain_title(title: str | None) -> str:
    """A set title without PoB's colour escapes, for matching and for reports."""

    return _COLOUR.sub("", title or "").strip()


def markers(title: str | None) -> set[str]:
    """The `{n}` stage markers an author wrote into a set title: "Endgame {2,4}" -> {"2", "4"}."""

    return {n.strip() for group in _MARKER.findall(title or "") for n in group.split(",") if n.strip()}


def select_titled(elements: Sequence[ET.Element], wanted: str, kind: str) -> tuple[ET.Element, int]:
    """The one element of `elements` whose title is `wanted`, and its 1-based position.

    Tried in order: the raw title, the title without colour escapes, the same two
    case-insensitively, then `wanted` as a regular expression over the plain title. A pattern
    that matches nothing, or more than one, raises with every title listed: a fixture must never
    be built from a guess."""

    titles = [e.get("title") or "" for e in elements]
    plains = [plain_title(t) for t in titles]
    for candidates, probe in ((titles, wanted), (plains, wanted),
                              ([t.lower() for t in titles], wanted.lower()), ([p.lower() for p in plains], wanted.lower())):
        hits = [i for i, t in enumerate(candidates) if t == probe]
        if len(hits) == 1:
            return elements[hits[0]], hits[0] + 1
        if len(hits) > 1:
            raise ValueError(f"{kind} title {wanted!r} is not unique: positions {[i + 1 for i in hits]} of {titles}")
    try:
        pattern = re.compile(wanted, re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"no {kind} titled {wanted!r} (and it is not a regex: {exc}); titles: {titles}") from exc
    hits = [i for i, t in enumerate(plains) if pattern.search(t)]
    if len(hits) == 1:
        return elements[hits[0]], hits[0] + 1
    raise ValueError(f"{kind} {wanted!r} matches {len(hits)} of the titles {titles}")


def gem_names(group: ET.Element) -> list[str]:
    """The gem names of one socket group, in the author's order (disabled gems included: the
    group is chosen by what is socketed, not by what is switched on)."""

    return [g.get("nameSpec") or "" for g in group.findall("Gem") if (g.get("nameSpec") or "").strip()]


def is_vaal(name: str, actives: dict) -> bool:
    """A Vaal gem, which grants two active skills (the Vaal one and its base) and so contributes
    two entries to PoB's list. The corpus flag first; the name prefix catches a transfigured Vaal
    gem the corpus does not carry under that name ("Vaal Ground Slam of Earthshaking")."""

    return bool((actives.get(name) or {}).get("is_vaal_gem")) or name.startswith("vaal ")


def align_main_active_skill(group: ET.Element, main_skill: str | None, notes: list[str]) -> None:
    """Point the group's `mainActiveSkill` at the build's main skill.

    A socket group can hold several active skills, and PoB's `mainActiveSkill` is a 1-based index
    into them (measured 2026-09-18 on the Essence Drain build: 1 = Spellslinger, 2 = Contagion,
    3 = Essence Drain, and only 3 gives a number -- Spellslinger itself deals no damage, so the
    author's `mainActiveSkill="1"` reads as CombinedDPS 0 and the reference would be worthless).
    Which gems are active skills comes from the gem corpus, never from a name list.

    The author's own selection is left alone when it cannot be read with certainty: a Vaal main
    skill (the author picking index 2 of "Vaal Ground Slam of Earthshaking" means the sustainable
    base skill, a deliberate choice), or a main skill the corpus does not list."""

    from junkroan.search.hypothesis import active_gems

    actives = active_gems()
    wanted = {n.lower() for n in main_skill_names(main_skill)}
    current = int(group.get("mainActiveSkill") or 1)
    if not wanted:
        return
    index, found, vaal_before = 0, None, False
    for gem in group.findall("Gem"):
        name = (gem.get("nameSpec") or "").strip().lower()
        if not name or gem.get("enabled", "true") == "false" or not (name in actives or is_vaal(name, actives)):
            continue
        vaal = is_vaal(name, actives)
        if found is None and name in wanted:
            if vaal:  # two entries, and which of them the author wants is their call
                notes.append(f"mainActiveSkill left at {current}: the main skill {name!r} is a Vaal gem (two entries, the author's pick stands)")
                return
            found = index + 1
        elif found is None and vaal:
            vaal_before = True  # the index below counts two entries for it, PoB's own behaviour
        index += 2 if vaal else 1
    if found is None:
        notes.append(f"mainActiveSkill left at {current}: the corpus lists no active gem of {sorted(wanted)} in the main group")
        return
    if vaal_before:
        notes.append(f"mainActiveSkill {found} assumes a Vaal gem before the main skill grants two entries")
    if current != found:
        notes.append(f"mainActiveSkill {current} -> {found} ({sorted(wanted)[0]!r} is active skill {found} of {index} in the main group)")
    group.set("mainActiveSkill", str(found))
    group.set("mainActiveSkillCalcs", str(found))


def main_skill_names(main_skill: str | None) -> list[str]:
    """The names a manifest's `main_skill` can appear under as a gem.

    The string itself, the string without its parenthetical ("Explosive Arrow (Ballista Totem)"
    -> "Explosive Arrow", "Essence Drain (+ Contagion / Bane)" -> "Essence Drain") and, when the
    manifest names alternatives, each of them ("Sunder / Eviscerate" -> "Sunder", "Eviscerate":
    the author levels with one and swaps to the other, and only one is in the early loadout)."""

    if not main_skill:
        return []
    out = [main_skill.strip()]
    bare = re.sub(r"\s*\(.*$", "", main_skill).strip()
    for name in [bare, *re.split(r"\s*[/+]\s*", bare)]:
        if name and name.lower() not in {o.lower() for o in out}:
            out.append(name)
    return out


def choose_main_group(groups: Sequence[ET.Element], current: int, main_skill: str | None, notes: list[str]) -> int:
    """The `mainSocketGroup` index the kept skill set should carry.

    The author's index is a position in whichever skill set they left active, so it can point at
    another set's group entirely ("Level 38+" of the Explosive Arrow build opens on Flame Dash).
    It is kept when it is in range and its group holds the main skill; otherwise the first group
    that holds the main skill wins, and the move is written into the report.

    An early loadout often runs another skill than the build's headline one (the Ice Nova
    Hierophant maps on Firestorm, the Lacerate Gladiator on Sunder): then nothing holds the main
    skill, and the largest live group wins -- the main link is the long one, an aura or a guard
    group is two or three gems. The author's index breaks a tie, and the choice is reported."""

    wanted = {n.lower() for n in main_skill_names(main_skill)}
    live = [i for i, g in enumerate(groups, start=1) if gem_names(g)]
    if not live:
        raise ValueError("the chosen skill set has no socket group with a gem in it")

    def holds(index: int) -> bool:
        return bool(wanted & {n.strip().lower() for n in gem_names(groups[index - 1])})

    in_range = 1 <= current <= len(groups)
    if wanted:
        if in_range and holds(current):
            return current
        hit = next((i for i in live if holds(i)), None)
        if hit is not None:
            why = "out of range" if not in_range else f"holds {gem_names(groups[current - 1]) or '(no gem)'}"
            notes.append(f"mainSocketGroup {current} ({why}) -> {hit}, the group holding {sorted(wanted)[0]!r}")
            return hit
        # the loadout runs another skill than the build's headline one: the longest group is its main link
        widest = max(len(gem_names(groups[i - 1])) for i in live)
        best = [i for i in live if len(gem_names(groups[i - 1])) == widest]
        pick = current if current in best else best[0]
        notes.append(f"no socket group of the kept skill set holds {main_skill!r}: mainSocketGroup {current} -> {pick}, "
                     f"the largest live group ({widest} gems: {gem_names(groups[pick - 1])})")
        return pick
    if in_range and gem_names(groups[current - 1]):
        return current
    notes.append(f"mainSocketGroup {current} is not a live group of the kept skill set -> {live[0]}")
    return live[0]


def choose_config_set(config_sets: Sequence[ET.Element], chosen_titles: Sequence[str], active_id: str, notes: list[str]) -> ET.Element:
    """The config set that belongs to the loadout whose (plain) set titles are `chosen_titles`.

    In order: a config set titled exactly like one of them (the Essence Drain build titles all
    four of its set types the same way); else the one sharing most of the loadout's `{n}` markers
    ("Default {1,3}" over "Ailment Avoid {2,4}" for a loadout marked {1,2,3}); else the build's
    own active set, with a note -- a guess between two configs is worth less than saying that the
    author's last state was kept."""

    wanted = {t.lower() for t in chosen_titles if t}
    hits = [c for c in config_sets if plain_title(c.get("title")).lower() in wanted]
    if len(hits) == 1:
        return hits[0]
    loadout_markers = {m for t in chosen_titles for m in markers(t)}
    if loadout_markers:
        scored = [(len(markers(c.get("title")) & loadout_markers), c) for c in config_sets]
        best = max(score for score, _ in scored)
        winners = [c for score, c in scored if score == best]
        if best > 0 and len(winners) == 1:
            return winners[0]
    active = next((c for c in config_sets if c.get("id") == active_id), config_sets[0])
    if len(config_sets) > 1:  # one set is not a choice
        notes.append(f"config set: no title or marker of the loadout names one, kept the build's active set "
                     f"{plain_title(active.get('title'))!r} of {[plain_title(c.get('title')) for c in config_sets]}")
    return active


def extract_loadout(
    xml: str,
    *,
    item_set: str,
    spec: str,
    skill_set: str | None = None,
    config_set: str | None = None,
    level: int | None = None,
    main_skill: str | None = None,
) -> tuple[str, dict]:
    """One loadout of a multi-loadout PoB XML as a single-loadout PoB XML, and a report of what
    was chosen (titles, the ids and positions they had, the level, the main socket group, the
    item count, and every note the choice produced)."""

    root = ET.fromstring(xml)
    build, tree, skills, items = (root.find(t) for t in ("Build", "Tree", "Skills", "Items"))
    if build is None or tree is None or items is None:
        raise ValueError("not a PoB build XML: <Build>, <Tree> and <Items> are all required")
    notes: list[str] = []

    specs = tree.findall("Spec")
    chosen_spec, spec_index = select_titled(specs, spec, "spec")
    for element in specs:
        if element is not chosen_spec:
            tree.remove(element)
    tree.set("activeSpec", "1")

    skill_sets = skills.findall("SkillSet") if skills is not None else []
    chosen_skill_set, skill_set_pos = None, None
    if skill_set is not None:
        if not skill_sets:
            raise ValueError("the build has no <SkillSet>: nothing to choose from")
        chosen_skill_set, skill_set_pos = select_titled(skill_sets, skill_set, "skill set")
    elif skill_sets:
        active = skills.get("activeSkillSet") or "1"
        chosen_skill_set = next((s for s in skill_sets if s.get("id") == active), skill_sets[0])
        skill_set_pos = skill_sets.index(chosen_skill_set) + 1
    skill_set_id = chosen_skill_set.get("id") if chosen_skill_set is not None else None
    if chosen_skill_set is not None:
        for element in skill_sets:
            if element is not chosen_skill_set:
                skills.remove(element)
        chosen_skill_set.set("id", "1")
        skills.set("activeSkillSet", "1")

    item_sets = items.findall("ItemSet")
    if not item_sets:
        raise ValueError("the build has no <ItemSet>: nothing to choose from")
    chosen_item_set, item_set_pos = select_titled(item_sets, item_set, "item set")
    item_set_id = chosen_item_set.get("id")
    for element in item_sets:
        if element is not chosen_item_set:
            items.remove(element)
    chosen_item_set.set("id", "1")
    items.set("activeItemSet", "1")
    # PoB saves this one off the active item set (ItemsTab:Save); with the other sets gone it
    # must follow the kept one, or a weapon-swap build would load on the wrong hand
    items.set("useSecondWeaponSet", chosen_item_set.get("useSecondWeaponSet") or "false")

    worn = {slot.get("itemId") for slot in chosen_item_set.findall("Slot")}
    jewels = {socket.get("itemId") for socket in chosen_spec.iter("Socket")}
    keep_ids = {i for i in (worn | jewels) if i not in (None, "", "0")}
    all_items = items.findall("Item")
    for element in all_items:
        if element.get("id") not in keep_ids:
            items.remove(element)
    kept_ids = {e.get("id") for e in items.findall("Item")}
    if missing := sorted(keep_ids - kept_ids, key=lambda s: int(s) if s.isdigit() else 0):
        notes.append(f"slots point at item ids the build does not carry: {missing}")

    config = root.find("Config")
    config_sets = config.findall("ConfigSet") if config is not None else []
    chosen_config = None
    if config_sets:
        if config_set is not None:
            chosen_config, _ = select_titled(config_sets, config_set, "config set")
        else:
            chosen_config = choose_config_set(config_sets, [plain_title(e.get("title")) for e in
                                                            (chosen_item_set, chosen_spec, chosen_skill_set) if e is not None],
                                              config.get("activeConfigSet") or "1", notes)
        config_set_id = chosen_config.get("id")
        for element in config_sets:
            if element is not chosen_config:
                config.remove(element)
        chosen_config.set("id", "1")
        config.set("activeConfigSet", "1")

    if level is not None:
        build.set("level", str(int(level)))
        # PoB's auto mode would overwrite it from the node count (Build.lua EstimatePlayerProgress)
        build.set("characterLevelAutoMode", "false")

    main_index = int(build.get("mainSocketGroup") or 1)
    if chosen_skill_set is not None:
        main_index = choose_main_group(chosen_skill_set.findall("Skill"), main_index, main_skill, notes)
        build.set("mainSocketGroup", str(main_index))
        align_main_active_skill(chosen_skill_set.findall("Skill")[main_index - 1], main_skill, notes)

    groups = chosen_skill_set.findall("Skill") if chosen_skill_set is not None else []
    report = {
        "item_set": {"title": chosen_item_set.get("title"), "plain": plain_title(chosen_item_set.get("title")), "was_id": item_set_id, "was_position": item_set_pos},
        "spec": {"title": chosen_spec.get("title"), "plain": plain_title(chosen_spec.get("title")), "was_position": spec_index,
                 "tree_version": chosen_spec.get("treeVersion"), "allocated_nodes": len([n for n in (chosen_spec.get("nodes") or "").split(",") if n.strip()])},
        "skill_set": None if chosen_skill_set is None else {"title": chosen_skill_set.get("title"), "plain": plain_title(chosen_skill_set.get("title")), "was_id": skill_set_id, "was_position": skill_set_pos, "groups": len(groups)},
        "config_set": None if chosen_config is None else {"title": chosen_config.get("title"), "plain": plain_title(chosen_config.get("title")), "was_id": config_set_id, "of": len(config_sets)},
        "level": int(build.get("level") or 0),
        "class": build.get("className"),
        "ascendancy": build.get("ascendClassName"),
        "main_socket_group": main_index,
        "main_group_gems": gem_names(groups[main_index - 1]) if groups and 1 <= main_index <= len(groups) else [],
        "items_kept": len(kept_ids),
        "items_dropped": len(all_items) - len(kept_ids),
        "tree_jewels": len({i for i in jewels if i not in (None, "", "0")}),
        "notes": notes,
    }
    return ET.tostring(root, encoding="unicode"), report


def extract_file(source: Path, out: Path, **kwargs) -> dict:
    """`extract_loadout` on an import-code file, written back out as an import code."""

    text = source.read_text(encoding="utf-8").strip()
    xml = text if text.startswith("<") else decode_import_code(text)
    new_xml, report = extract_loadout(xml, **kwargs)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(encode_import_code(new_xml), encoding="utf-8", newline="\n")
    return {**report, "source": source.name, "out": out.name}


def manifest_rows(folder: Path, slugs: Sequence[str] | None = None) -> tuple[dict, list[dict], list[str]]:
    """(the folder's manifest, the builds to extract, the slugs skipped for having no
    `early_loadout`). A build without one has no staged loadouts to cut: it is named, never
    guessed at."""

    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    rows = [b for b in manifest["builds"] if not slugs or b["slug"] in slugs]
    skipped = [b["slug"] for b in rows if not b.get("early_loadout")]
    return manifest, [b for b in rows if b.get("early_loadout")], skipped


def write_index(folder: Path, manifest: dict, reports: list[dict], rows: list[dict]) -> Path:
    """sources.json (what `scripts/fixture_stats.py` reads) and README.md (which loadout of
    which author build each file is) for one extracted folder."""

    out_dir = folder / "early"
    league = manifest.get("league") or folder.name.replace("zizaran_", "")
    by_slug = {r["slug"]: r for r in rows}
    sources = {
        "source": f"Zizaran {league} league-starter guides, one early-game loadout per build (scripts/extract_loadout.py)",
        "league": league,
        "collected": manifest.get("collected"),
        "note": f"Extracted from tests/fixtures/{folder.name}/<file>: the item set, tree spec, skill set and config set the manifest's early_loadout names, as a single-loadout PoB. Regenerate with `python scripts/extract_loadout.py`.",
        "builds": [{
            "slug": rep["slug"], "title": by_slug[rep["slug"]]["title"], "level": rep["level"],
            "class": rep["class"],
            # the manifest's ascendancy is the build's; the XML's is what PoB will compute with, and
            # the two differ where the author never set an ascendancy class (3.26 Righteous Fire
            # Chieftain: ascendClassName "None" with the ascendancy nodes allocated all the same)
            "ascendancy": by_slug[rep["slug"]].get("ascendancy") or rep["ascendancy"],
            **({} if (by_slug[rep["slug"]].get("ascendancy") or rep["ascendancy"]) == rep["ascendancy"] else {"ascendancy_in_pob": rep["ascendancy"]}),
            "main_skill": by_slug[rep["slug"]]["main_skill"],
            "tree_version": rep["spec"]["tree_version"], "pob_url": by_slug[rep["slug"]]["pob_url"],
            "from": {"file": rep["source"], "item_set": rep["item_set"]["plain"], "spec": rep["spec"]["plain"], "skill_set": (rep["skill_set"] or {}).get("plain"),
                     "config_set": (rep["config_set"] or {}).get("plain"),
                     "linked_by": by_slug[rep["slug"]]["early_loadout"]["linked_by"], "level_source": by_slug[rep["slug"]]["early_loadout"]["level_source"]},
        } for rep in reports],
    }
    (out_dir / "sources.json").write_text(json.dumps(sources, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

    lines = [
        f"# Zizaran {league} league starters: the early-game loadout of each build",
        "",
        f"Part of the second reference set for the benchmark (`scripts/benchmark.py --set ziz`, where these builds are",
        f"named `z{folder.name.replace('zizaran_', '')}_<slug>` because the same slug exists in several leagues).",
        f"The files in `tests/fixtures/{folder.name}/` are the authors' own guide PoBs and carry several loadouts each",
        "(an item set, a tree spec, a skill set and a config set per stage). The benchmark reads one build, so each",
        "file here is one stage of one author build, cut out by `scripts/extract_loadout.py` from the loadout",
        "`../manifest.json` names in `early_loadout` -- never from the word \"early\" in a title.",
        "Regenerate them all with:",
        "",
        "```powershell",
        "python scripts/extract_loadout.py",
        "```",
        "",
        "| file | author build | item set | tree spec | skill set | config set | linked by | level (source) | nodes | main group |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for rep in reports:
        row = by_slug[rep["slug"]]
        early = row["early_loadout"]
        gems = ", ".join(rep["main_group_gems"][:3]) + (" ..." if len(rep["main_group_gems"]) > 3 else "")
        cfg = rep["config_set"] or {}
        lines.append(
            f"| {rep['out']} | {row['title']} | {rep['item_set']['plain']} | {rep['spec']['plain']} | {(rep['skill_set'] or {}).get('plain')} | "
            f"{cfg.get('plain')} (1 of {cfg.get('of')}) | {early['linked_by']} | {rep['level']} ({early['level_source']}) | "
            f"{rep['spec']['allocated_nodes']} | #{rep['main_socket_group']}: {gems} |"
        )
    skipped = [b["slug"] for b in manifest["builds"] if not b.get("early_loadout")]
    if skipped:
        lines += ["", f"Not extracted (no `early_loadout` in the manifest: the build has no staged loadouts): {', '.join(skipped)}."]
    notes = [f"- **{rep['slug']}**: {note}" for rep in reports for note in rep["notes"]]
    if notes:
        lines += ["", "## What the extraction had to decide", "", *notes]
    stats_file = out_dir / "stats.json"
    if stats_file.is_file():
        stats = {row["slug"]: row for row in json.loads(stats_file.read_text(encoding="utf-8"))}
        if all(rep["slug"] in stats for rep in reports):
            lines += ["", f"## What PoB reads them as (`python scripts/fixture_stats.py {folder.name}/early`, stats.json)", "",
                      "| build | level | nodes | life | EHP | CombinedDPS | FullDPS |", "|---|---|---|---|---|---|---|"]
            for rep in reports:
                row = stats[rep["slug"]]
                lines.append(f"| {rep['slug']} | {row['level']} | {row['tree']['allocated_nodes']} | {row['Life']:,} | {row['TotalEHP']:,.0f} | "
                             f"{(row['CombinedDPS'] or 0):,.0f} | {(row['FullDPS'] or 0):,.0f} |")
    lines += [
        "",
        "## Caveats",
        "",
        "- A guide PoB carries a **config set** per stage as well, and they are not interchangeable (the Essence Drain",
        "  build's \"Slinger 28+\" set holds the author's leveling crutch `+200% to all resistances`; its \"ALTERNATIVE",
        "  SETUP\" set holds the custom mods of a Pact of Ghorr staff build). The extractor picks the config set titled",
        "  like the loadout, else the one sharing most of its `{n}` markers, else keeps the build's active one and says so.",
        "- The gems in these files are the authors' own (mostly level 20-21 / quality 20-30). The benchmark does not",
        "  score them that way: `scripts/benchmark.py` writes the rails' gems (level 18, quality 0, the main skill at",
        "  the rails' `main_skill_quality`) onto the author's build before it reads a single number off it, because a",
        "  generated build is always socketed at those (D23, D68). The file keeps the author's values; the row in",
        "  results.json records them as `author_gem_levels`.",
        "- `<Build level>` is the level the loadout is written for (the manifest's `early_loadout.level`, from the spec",
        "  title or estimated from the node count); PoB's auto level mode is switched off in these files so that stated",
        "  level is the one PoB uses.",
        "- Everything else in the file is the author's: the tree is on the league's own tree version and the gear may be",
        "  whatever the author had at that stage. PoB computes it all with the pinned 3.29 data.",
        "",
    ]
    (out_dir / "README.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return out_dir


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slugs", nargs="*", help="manifest slugs to extract; none = every build of every zizaran_* manifest")
    ap.add_argument("--league", help="one fixture folder only: 327 or 3.27")
    ap.add_argument("--source", type=Path, help="one .pob.txt / XML file instead of the manifest")
    ap.add_argument("--out", type=Path, help="output file (with --source)")
    ap.add_argument("--item-set", help="item set title or regex (with --source)")
    ap.add_argument("--spec", help="tree spec title or regex (with --source)")
    ap.add_argument("--skill-set", help="skill set title or regex (with --source)")
    ap.add_argument("--config-set", help="config set title or regex; without it the loadout's title / {n} markers decide (with --source)")
    ap.add_argument("--main-skill", help="the build's main skill, for the mainSocketGroup check (with --source)")
    ap.add_argument("--level", type=int, help="the level the loadout is for (with --source)")
    ap.add_argument("--no-index", action="store_true", help="do not rewrite the folder's sources.json / README.md")
    args = ap.parse_args()

    if args.source:
        if not (args.out and args.item_set and args.spec):
            ap.error("--source needs --out, --item-set and --spec")
        report = extract_file(args.source, args.out, item_set=args.item_set, spec=args.spec, skill_set=args.skill_set,
                              config_set=args.config_set, level=args.level, main_skill=args.main_skill)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    total, warnings, skipped_all = 0, [], []
    for folder in league_folders(args.league):
        manifest, rows, skipped = manifest_rows(folder, args.slugs or None)
        if not rows and not skipped:
            continue
        print(f"== {folder.name} ({manifest.get('league')}): {len(rows)} builds")
        skipped_all += [f"{folder.name}/{slug}" for slug in skipped]
        for slug in skipped:
            print(f"   skipped {slug}: the manifest has no early_loadout (no staged loadouts in the PoB)")
        reports = []
        for row in rows:
            early = row["early_loadout"]
            report = extract_file(folder / row["file"], folder / "early" / f"{row['slug']}.pob.txt",
                                  item_set=early["item_set"], spec=early["spec"], skill_set=early["skill_set"],
                                  config_set=early.get("config_set"), level=early.get("level"), main_skill=row.get("main_skill"))
            report["slug"] = row["slug"]
            reports.append(report)
            print(f"   {row['slug']:34s} L{report['level']:<3d} nodes={report['spec']['allocated_nodes']:<4d} items={report['items_kept']:<3d} (-{report['items_dropped']}) "
                  f"group #{report['main_socket_group']} {report['main_group_gems'][:1]} <- {report['item_set']['plain']!r} / {report['spec']['plain']!r} / "
                  f"{(report['skill_set'] or {}).get('plain')!r} / config {(report['config_set'] or {}).get('plain')!r}")
            for note in report["notes"]:
                print(f"       note: {note}")
            if report["spec"]["allocated_nodes"] < MIN_MAPS_NODES:
                warning = (f"{folder.name}/{row['slug']}: the loadout's spec {report['spec']['plain']!r} allocates only "
                           f"{report['spec']['allocated_nodes']} nodes (< {MIN_MAPS_NODES}) -- a leveling tree, not an early-maps one")
                warnings.append(warning)
                print(f"       WARNING: {warning}")
        total += len(reports)
        if reports and not args.no_index and not args.slugs:
            out_dir = write_index(folder, manifest, reports, rows)
            print(f"   wrote {out_dir / 'sources.json'} and {out_dir / 'README.md'}")
    print(f"\n{total} builds extracted"
          + (f"; skipped (no early_loadout): {', '.join(skipped_all)}" if skipped_all else "")
          + (f"\nWARNINGS:\n  " + "\n  ".join(warnings) if warnings else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
