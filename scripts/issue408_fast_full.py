"""Issue #408 unit 1: item trials in fast mode against full mode, on the cold_dot template builds (seeds 4-6).

For each seed and each slot whose item has an explicit cold-resistance line: every candidate of the slot's suffix
pool (the line swap of issue #10) is trialled in `fast`, in `full`, and in `fast` with the payload's `parts = []`
(`PobSession.mean_parts = None` for that pass). Prints per slot options / accepted (ColdResist >= 75) / best Score %
per mode, and the max abs relative difference fast-vs-full of CombinedDPS, ColdResist, Life, EnergyShield over all
candidates, the unchanged item trialled in both modes, and the TREE reference: 20 node trials per seed (leaf removals
and single frontier additions), max abs(fast - full) / full of CombinedDPS.

Run (after `python scripts/machine_load.py --need 1 --role other` says GO):
    python scripts/issue408_fast_full.py [--seed 4] [--run-dir <benchmark run folder>]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# ISSUE408_SRC: another src tree (an older commit exported to a folder) to run the same measurement on
if "junkroan" not in sys.modules:  # imported by a test: the test run already chose the src tree
    sys.path.insert(0, os.environ.get("ISSUE408_SRC") or str(Path(__file__).resolve().parents[1] / "src"))

from junkroan.pob.session import decode_import_code  # noqa: E402

DEFAULT_RUN_DIR = Path(r"C:\Coding\poe-junkroan-v2\artifacts\benchmark\20260926-1759-core14-tpl-main3-s4")
BASE_KEYS = ("CombinedDPS", "Life", "ColdResist", "ColdResistOverCap", "FireResist", "LightningResist", "EnergyShield")
DIFF_KEYS = ("CombinedDPS", "ColdResist", "Life", "EnergyShield")
TREE_TRIALS = 20  # per seed: half leaf removals, half single frontier additions

_COLD = re.compile(r"(-?\d+(?:\.\d+)?)% to (Cold Resistance|Fire and Cold Resistances?|Cold and Lightning Resistances?|all Elemental Resistances)")
_ANY_RES = re.compile(r"% to (Fire|Cold|Lightning) Resistance|% to (Fire and Cold|Cold and Lightning|Fire and Lightning) Resistances?|% to all Elemental Resistances")
_TAG = re.compile(r"^(\{[^}]*\})+")


def parse_item(text: str) -> dict:
    """Rarity, name, base, implicit count, lines [(is_implicit, crafted, text)] of one PoB item text."""

    raw = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    rarity = raw[0].split(":", 1)[1].strip().upper() if raw and raw[0].startswith("Rarity:") else ""
    head = []
    i = 1
    while i < len(raw) and not raw[i].startswith("Unique ID:") and ":" not in raw[i]:
        head.append(raw[i])
        i += 1
    name = head[0] if head else ""
    base = head[-1] if head else ""
    implicits = 0
    start = len(raw)
    for j, ln in enumerate(raw):
        if ln.startswith("Implicits:"):
            implicits = int(ln.split(":", 1)[1])
            start = j + 1
            break
    lines = []
    for k, ln in enumerate(raw[start:]):
        crafted = "{crafted}" in ln
        lines.append((k < implicits, crafted, _TAG.sub("", ln).strip()))
    return {"rarity": rarity, "name": name, "base": base, "lines": lines}


def _slots_to_items(xml_text: str) -> list[tuple[str, str]]:
    """[(slot name, item text)] of the active item set, empty slots dropped."""

    root = ET.fromstring(xml_text)
    items_el = root.find("Items")
    texts = {el.get("id"): (el.text or "") for el in items_el.findall("Item")}
    active = items_el.get("activeItemSet")
    sets = items_el.findall("ItemSet")
    chosen = next((s for s in sets if s.get("id") == active), sets[0] if sets else items_el)
    result = []
    for slot in chosen.findall("Slot"):
        item_id = slot.get("itemId")
        if item_id and item_id != "0" and item_id in texts:
            result.append((slot.get("name", ""), texts[item_id]))
    return result


RES_CAP = 75.0
BASE_KEYS = ("CombinedDPS", "Life", "ColdResist", "ColdResistOverCap", "FireResist", "LightningResist")


def _is_cold(text: str) -> bool:
    return bool(_COLD.search(text))


def base_type(base: str) -> str:
    """`Two-Stone Ring (Cold/Lightning)` -> `Two-Stone Ring` (PoB's item header carries the variant in brackets)."""

    return re.sub(r"\s*\([^)]*\)\s*$", "", base).strip()


def item_level(raw: str, default: int = 84) -> int:
    m = re.search(r"^\s*Item Level:\s*(\d+)", raw, re.M)
    return int(m.group(1)) if m else default


def replace_line(raw: str, old_text: str, new_lines: list[str], *, old_mod_id: str | None = None, new_mod_id: str | None = None) -> str:
    """The item text with the explicit line whose untagged text is `old_text` replaced by `new_lines`
    (already tagged text lines, e.g. `{tags:...}{suffix}+30% to Lightning Resistance`). Every other line stays.
    The `Suffix:` header of the old mod (`old_mod_id`) becomes the new mod's header; with no such header
    (a bench craft) the first `Suffix: None` is filled instead. Raises ValueError when the line is not found."""

    lines = raw.split("\n")
    first_explicit = len(lines)
    for i, ln in enumerate(lines):
        if ln.strip().startswith("Implicits:"):
            first_explicit = i + 1 + int(ln.split(":", 1)[1])
            break
    at = next((i for i in range(first_explicit, len(lines)) if _TAG.sub("", lines[i].strip()).strip() == old_text), None)
    if at is None:
        raise ValueError(f"line not found in item text: {old_text!r}")
    indent = lines[at][: len(lines[at]) - len(lines[at].lstrip())]
    lines[at:at + 1] = [indent + t for t in new_lines]
    if new_mod_id:
        header_at = None
        if old_mod_id:
            pattern = re.compile(r"\s*Suffix:\s*(\{[^}]*\})*" + re.escape(old_mod_id) + r"\s*$")
            header_at = next((i for i, ln in enumerate(lines) if pattern.match(ln)), None)
        if header_at is None:
            header_at = next((i for i, ln in enumerate(lines) if ln.strip() == "Suffix: None"), None)
        if header_at is not None:
            hi = lines[header_at]
            lines[header_at] = hi[: len(hi) - len(hi.lstrip())] + "Suffix: {range:0.5}" + new_mod_id
    return "\n".join(lines)


def swap_accepted(stats: dict, baseline: dict) -> bool:
    """ColdResist stays >= 75, and no other resistance falls below 75 (one that was already below is
    held at its own level)."""

    if float(stats.get("ColdResist") or 0) < RES_CAP:
        return False
    for key in ("FireResist", "LightningResist"):
        floor = min(RES_CAP, float(baseline.get(key) or 0))
        if float(stats.get(key) or 0) < floor - 1e-9:
            return False
    return True


class PoolProvider:
    """Candidates of a PobSession build: each explicit, non-unique cold line, with the slot's suffix pool
    (`WishlistGear._median_mods`, median tier at the item's ilvl; mod groups of the item and cold lines skipped)."""

    def __init__(self, pob, wishlist) -> None:
        self.pob, self.wishlist = pob, wishlist
        self._mods: dict[str, dict] = {}
        self._rendered: dict[tuple[str, int, str], list[str]] = {}

    def _mod_index(self, base: str) -> dict[str, dict]:
        if base not in self._mods:
            self._mods[base] = {str(m["mod_id"]): m for m in self.pob.list_item_mods(base, ilvl=100)["mods"]}
        return self._mods[base]

    def _render(self, base: str, ilvl: int, mod_id: str) -> list[str]:
        key = (base, ilvl, mod_id)
        if key not in self._rendered:
            crafted = self.pob.craft_rare(base, suffixes=[mod_id], ilvl=ilvl)
            if crafted.get("problems"):
                raise ValueError(f"craft_rare {mod_id} on {base}: {crafted['problems']}")
            self._rendered[key] = [ln if ln.lstrip().startswith("{") else "{suffix}" + ln for ln in crafted["explicit_lines"]]
        return self._rendered[key]

    def __call__(self, items: dict[str, str]) -> list[dict]:
        out = []
        for slot, raw in items.items():
            item = parse_item(raw)
            if item["rarity"] == "UNIQUE":
                continue
            # No explicit cold line, nothing to swap: never ask PoB for the slot's mods (a magic flask's
            # display name, e.g. "Prepared Divine Life Flask of the Cure", is no base PoB knows; #10).
            if not any(not implicit and _is_cold(text) for implicit, _crafted, text in item["lines"]):
                continue
            base, ilvl = base_type(item["base"]), item_level(raw)
            index = self._mod_index(base)
            header_ids = [h for h in re.findall(r"^\s*(?:Prefix|Suffix):\s*(?:\{[^}]*\})*(\w+)\s*$", raw, re.M) if h != "None"]
            used_groups = {str(index[h]["group"]) if h in index else h for h in header_ids}
            old_id = next((h for h in header_ids if h in index and any(_is_cold(t) for t in index[h]["lines"])), None)
            pool = None
            for implicit, crafted, text in item["lines"]:
                if implicit or not _is_cold(text):
                    continue
                if pool is None:
                    pool = [m for m in self.wishlist._median_mods(base, ilvl, affix_type="Suffix")
                            if m.group not in used_groups and not any(_is_cold(t) for t in m.lines)]
                options = []
                for m in pool:
                    new_lines = self._render(base, ilvl, m.mod_id)
                    try:
                        new_raw = replace_line(raw, text, new_lines, old_mod_id=old_id, new_mod_id=m.mod_id)
                    except ValueError:
                        continue
                    options.append({"line": " / ".join(_TAG.sub("", t.strip()).strip() for t in new_lines), "raw": new_raw})
                out.append({"slot": slot, "old_line": text, "options": options})
        return out


def rel_diff(a: float | None, b: float | None) -> float:
    """abs(a - b) / abs(b) (abs(a - b) when b is 0)."""

    a, b = float(a or 0), float(b or 0)
    return abs(a - b) / abs(b) if b else abs(a - b)


def run_modes(pob, trials: list[dict], keys: tuple[str, ...]) -> dict[str, list[dict]]:
    """The same trials in fast, in full, and in fast with no mean_parts (payload parts = [])."""

    out = {"fast": pob.trial_stats(trials, keys, mode="fast"), "full": pob.trial_stats(trials, keys, mode="full")}
    saved, pob.mean_parts = pob.mean_parts, None
    try:
        out["fast0"] = pob.trial_stats(trials, keys, mode="fast")
    finally:
        pob.mean_parts = saved
    return out


def max_diffs(res: dict[str, list[dict]], a: str, b: str) -> dict[str, float]:
    worst = {k: 0.0 for k in DIFF_KEYS}
    for ra, rb in zip(res[a], res[b]):
        if not (ra.get("ok") and rb.get("ok")):
            continue
        if (ra.get("removed_node_ids"), ra.get("added_node_ids")) != (rb.get("removed_node_ids"), rb.get("added_node_ids")):
            continue  # a tree trial whose node set differs between modes (full cascades a removal, fast does not): not the same trial
        for k in DIFF_KEYS:
            worst[k] = max(worst[k], rel_diff(ra["stats"].get(k), rb["stats"].get(k)))
    return worst


def worst_trial(res: dict[str, list[dict]], trials: list[dict], a: str, b: str, key: str = "CombinedDPS") -> str:
    """Counts of comparable trial pairs (both ok, same node set) / the rest and the trial with the biggest gap of `key`."""

    ok = [(rel_diff(ra["stats"].get(key), rb["stats"].get(key)), t, ra, rb)
          for ra, rb, t in zip(res[a], res[b], trials) if ra.get("ok") and rb.get("ok")
          and (ra.get("removed_node_ids"), ra.get("added_node_ids")) == (rb.get("removed_node_ids"), rb.get("added_node_ids"))]
    failed = len(trials) - len(ok)
    if not ok:
        return f"comparable pairs 0, excluded {failed}"
    gap, t, ra, rb = max(ok, key=lambda x: x[0])
    return (f"comparable pairs {len(ok)}, excluded {failed}; worst {key} gap {gap:.3g} at {t}: {a} {ra['stats'].get(key)} vs {b} {rb['stats'].get(key)} "
            f"(removed {ra.get('removed_node_ids')} / {rb.get('removed_node_ids')}, added {ra.get('added_node_ids')} / {rb.get('added_node_ids')})")


def fmt_best(best: tuple | None) -> str:
    return "none" if best is None else f"{best[0]:+.2f}% ({best[1]})"


def measure_seed(run_dir: Path, seed: int, slug: str = "cold_dot") -> None:
    from junkroan.optimizer.objective_select import objective_for
    from junkroan.optimizer.random_parts import apply_mean_parts, main_skill_of
    from junkroan.optimizer.rails import Rails
    from junkroan.optimizer.tree_graph import TreeGraph
    from junkroan.optimizer.wishlist_gear import WishlistGear
    from junkroan.pob.session import PobSession

    code = (Path(run_dir) / f"{slug}-s{seed}.pob.txt").read_text(encoding="utf-8").strip()
    with PobSession(run_id=f"issue408-s{seed}") as pob:
        pob.load_import_code(code)
        apply_mean_parts(pob)
        skill, _part = main_skill_of(pob.read_state())
        print(f"== seed {seed}: main skill {skill}, mean_parts = {pob.mean_parts!r}", flush=True)
        rails = Rails.load()
        objective = objective_for(rails, skill)
        keys = tuple(dict.fromkeys((*BASE_KEYS, *objective.stat_keys)))
        base = pob.stats(keys)
        s0 = objective.score(base)
        slot_texts = dict(_slots_to_items(decode_import_code(code)))
        provider = PoolProvider(pob, WishlistGear(pob, objective, rails))
        print(f"   baseline: CombinedDPS {base.get('CombinedDPS'):,.0f}, ColdResist {base.get('ColdResist')}, Life {base.get('Life')}, EnergyShield {base.get('EnergyShield')}")
        for cand in provider(slot_texts):
            slot, options = cand["slot"], cand["options"]
            if not options:
                continue
            trials = [{"item": {"slot": slot, "raw": o["raw"]}} for o in options]
            res = run_modes(pob, trials, keys)
            summary = {}
            for mode in ("fast", "full", "fast0"):
                acc = [(objective.score(r["stats"]), o["line"]) for r, o in zip(res[mode], options) if r.get("ok", True) and swap_accepted(r["stats"], base)]
                best = max(acc, default=None, key=lambda x: x[0])
                summary[mode] = (len(acc), None if best is None else ((best[0].value / s0.value - 1) * 100, best[1]))
            print(f"  {slot} | {cand['old_line']} | options {len(options)}")
            for mode in ("fast", "full", "fast0"):
                label = {"fast": "fast (parts as session)", "full": "full", "fast0": "fast parts=[]"}[mode]
                print(f"     {label:24s} accepted {summary[mode][0]:2d}/{len(options)}  best Score {fmt_best(summary[mode][1])}")
            for a, b in (("fast", "full"), ("fast0", "full")):
                d = max_diffs(res, a, b)
                print(f"     max rel diff {a} vs {b}: " + ", ".join(f"{k} {v:.3g}" for k, v in d.items()))
            same = [{"item": {"slot": slot, "raw": slot_texts[slot]}}]
            ures = run_modes(pob, same, keys)
            print("     unchanged item CombinedDPS: " + ", ".join(f"{m} {ures[m][0]['stats'].get('CombinedDPS'):,.3f}" for m in ("fast", "full", "fast0"))
                  + " | ColdResist: " + ", ".join(f"{m} {ures[m][0]['stats'].get('ColdResist')}" for m in ("fast", "full", "fast0")), flush=True)

        # TREE reference
        tree = pob.tree_light()
        allocated = {int(n) for n in tree.get("user_allocated_node_ids") or ()}
        graph = TreeGraph.load()
        start = graph.class_starts.get(str(tree.get("class_id") or ""))
        if start is not None:
            allocated.add(start)
        leaves = [n for n in graph.removable_leaves(allocated) if n in graph.allocatable]
        front = sorted(n for n in graph.frontier(allocated) if (graph.node(n) and graph.node(n).kind == "normal"))
        half = TREE_TRIALS // 2

        def pick(xs: list[int], n: int) -> list[int]:
            return [xs[int(i * len(xs) / n)] for i in range(n)] if len(xs) >= n else list(xs)

        trials = [{"remove": [n]} for n in pick(leaves, half)] + [{"add": [n]} for n in pick(front, TREE_TRIALS - half)]
        res = run_modes(pob, trials, keys)
        print(f"  TREE trials: {len(trials)} ({len(leaves)} leaves, {len(front)} frontier normals available)")
        for a in ("fast", "fast0"):
            d = max_diffs(res, a, "full")
            print(f"     max rel diff {a} vs full: " + ", ".join(f"{k} {v:.3g}" for k, v in d.items()), flush=True)
        print("     " + worst_trial(res, trials, "fast", "full"), flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--seed", type=int, choices=(4, 5, 6), default=None)
    args = parser.parse_args(argv)
    for seed in ((args.seed,) if args.seed else (4, 5, 6)):
        measure_seed(args.run_dir, seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
