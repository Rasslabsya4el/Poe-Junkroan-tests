"""#169 MEASUREMENT ONLY: time fast_trials on the zombie_army_early / winter_orb final builds.

Code runs against the pinned snapshot @42565a9 via PYTHONPATH; this script itself is data-only
(no edits under src/). Loads the saved .pob.txt import codes, decodes them, and times
PobSession.trial_stats(mode="fast") the way `gear`/`refine` moves call it (Objective.stat_keys,
one what-if trial per call). Writes a JSON result file and prints tables for the report.

Usage:
    python scripts/diag169_fast_trials.py --items 1 --out <path>.json
    python scripts/diag169_fast_trials.py --items 2,3,4,5 --out <path>.json
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

# Running as `python scripts/diag169_fast_trials.py` puts this file's own directory
# (which also holds a top-level `junkroan.py` CLI shim) first on sys.path, shadowing
# the real `junkroan` package on PYTHONPATH. Drop it before importing.
sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]

from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails
from junkroan.pob.session import PobSession, decode_import_code

BENCH_ROOT = Path("C:/Coding/poe-junkroan-v2/artifacts/benchmark/20260927-0322-ziz-tpl-main3-s4")
ZOMBIE_POB = BENCH_ROOT / "z326_necromancer_zombie_army_early-s4.pob.txt"
WINTER_POB = BENCH_ROOT / "z329_elementalist_winter_orb-s5.pob.txt"

# The five minion skills #162 named as a guess, and the socket-group label(s) each active gem
# lives in within the zombie build's decoded XML (measured from the file itself, see report).
MINION_SKILLS = [
    "Raise Zombie",
    "Vaal Summon Skeletons",
    "Raise Spectre",
    "Summon Stone Golem of Safeguarding",
    "Summon Skeletons",
]

def load_decoded(path: Path) -> str:
    return decode_import_code(path.read_text(encoding="utf-8"))


def objective() -> Objective:
    return Rails.load().objective()


def open_session(run_id: str) -> PobSession:
    return PobSession(run_id=run_id)


def real_trial(pob: PobSession) -> dict:
    """A one-node-removal trial: the kind refine's leaf check and gear's node-repair send
    (tree_optimizer.py:970, `_measure([{"remove": [leaf]} for leaf in leaves], ...)`), not
    a no-op -- an identity add=[]/remove=[] trial changes nothing and PoB answers it from
    cache in ~0.01 s, which is not what the loop measured (#162)."""

    tree = pob.tree_light()
    allocated = tree.get("user_allocated_node_ids") or []
    if not allocated:
        raise RuntimeError("build has no user_allocated_node_ids to build a removal trial from")
    return {"add": [], "remove": [int(allocated[0])], "mastery": {}}


def time_calls(pob: PobSession, keys, n: int, mode: str = "fast") -> list[float]:
    trial = real_trial(pob)
    out = []
    for _ in range(n):
        t0 = time.perf_counter()
        pob.trial_stats([dict(trial)], keys, mode=mode)
        out.append(time.perf_counter() - t0)
    return out


def time_calls_n_trials(pob: PobSession, keys, trial_count: int, repeats: int, mode: str = "fast") -> list[float]:
    base = real_trial(pob) if trial_count else None
    trials = [dict(base) for _ in range(trial_count)]
    out = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        pob.trial_stats(trials, keys, mode=mode)
        out.append(time.perf_counter() - t0)
    return out


def stat_snapshot(pob: PobSession, keys) -> dict:
    trial = real_trial(pob)
    return pob.trial_stats([dict(trial)], keys, mode="fast")[0].get("stats") or {}


def summarize(times: list[float]) -> dict:
    return {"n": len(times), "mean_s": statistics.mean(times), "median_s": statistics.median(times), "total_s": sum(times)}


def disable_gem_xml(xml: str, gem_name: str) -> tuple[str, int]:
    """Set enabled="false" on every <Gem ... nameSpec="gem_name" .../> in flagged (includeInFullDPS)
    skill groups. Returns (new_xml, count_disabled). Data-only text edit, not a src/ change."""

    blocks = re.split(r"(?=<Skill label=)", xml)
    count = 0
    out = []
    for b in blocks:
        head = re.match(r'(<Skill label="[^"]*"[^>]*includeInFullDPS="(true|false)"[^>]*enabled="(true|false)"[^>]*>)', b)
        head2 = re.match(r'(<Skill label="[^"]*"[^>]*enabled="(true|false)"[^>]*includeInFullDPS="(true|false)"[^>]*>)', b)
        flagged = False
        if head and head.group(2) == "true" and head.group(3) == "true":
            flagged = True
        elif head2 and head2.group(2) == "true" and head2.group(3) == "true":
            flagged = True
        if flagged and f'nameSpec="{gem_name}"' in b:
            def _sub(m: re.Match) -> str:
                nonlocal count
                tag = m.group(0)
                if f'nameSpec="{gem_name}"' in tag and 'enabled="true"' in tag:
                    count += 1
                    return tag.replace('enabled="true"', 'enabled="false"')
                return tag
            b = re.sub(r"<Gem\b[^>]*/>", _sub, b)
        out.append(b)
    return "".join(out), count


def find_flagged_groups(xml: str) -> list[dict]:
    blocks = re.split(r"(?=<Skill label=)", xml)
    groups = []
    for b in blocks:
        m = re.match(r'<Skill label="([^"]*)"\s+enabled="(true|false)"\s+slot="[^"]*"\s+includeInFullDPS="(true|false)"', b)
        if not m:
            continue
        label, enabled, flagged = m.groups()
        gems = re.findall(r'<Gem\b[^>]*nameSpec="([^"]*)"[^>]*enabled="(true|false)"', b)
        groups.append({"label": label, "enabled": enabled == "true", "flagged": flagged == "true", "gems": gems})
    return groups


# Records checked read-only for #169 round 2 item 1 (`results.json` rows, `moves` list, the two
# builds' `.log` files): no field anywhere carries trials-per-`fast_trials`-call. `pob_calls()`
# (session.py:175-184) only ever counts CALLS and their total seconds (results.json "pob_calls"
# key, matches #162's 1,162/7115.2s and 1,941/1165.5s); `trials_measured` (tree_optimizer.py:250,
# 678, 694) counts trials but is never written to results.json or the logs. So the recorded
# median batch size is NOT AVAILABLE; the two numbers below are the code's own documented batch
# constants instead (sourced, not estimated): the loop's per-slot gear re-roll batches
# `rails.gear.loot_best_of_n` items (`rails.py:122`, default 200 -- wishlist_gear.py:989, the
# per-slot craftable-candidates trial `self.pob.trial_stats([{"item": ...} for _name, raw in
# craftable], self.objective.stat_keys, mode="fast")`); `refine`'s swap batch is bounded by
# `top_candidates` (`tree_optimizer.py:903`, default 80; its own docstring at :917 says "~400 on
# a finished tree").
GEAR_BATCH = 200  # rails.py:122 loot_best_of_n
REFINE_BATCH = 80  # tree_optimizer.py:903 top_candidates default


def item_raw(xml: str, slot: str) -> tuple[str, str]:
    """(slot, raw item text) for `slot` from the decoded PoB XML's <ItemSet>/<Items>."""

    # PoB writes the <Slot> attributes in either order (zombie: itemPbURL/name/itemId, winter_orb:
    # name/itemId/itemPbURL), so read the tag first and its attributes independently.
    m = None
    for tag in re.findall(r"<Slot\b[^>]*/>", xml):
        if re.search(rf'\bname="{re.escape(slot)}"', tag):
            m = re.search(r'\bitemId="(\d+)"', tag)
            break
    if not m or m.group(1) == "0":
        raise RuntimeError(f"no <Slot name={slot!r}> in the decoded XML")
    item_id = m.group(1)
    body = re.search(rf'<Item\b[^>]*\bid="{item_id}"[^>]*>\n(.*?)\n\t\t</Item>', xml, re.S)
    if not body:
        raise RuntimeError(f"no <Item id={item_id}> body for slot {slot!r}")
    # The <Item> body is the item's plain-text raw (what `craft_rare`/`equip`/an item trial take)
    # followed by PoB's own <ModRange .../> metadata tags, which are not part of the raw text.
    text = body.group(1).split("\n\t\t\t<ModRange")[0]
    return slot, "\n".join(line.strip("\t") for line in text.strip("\n").split("\n"))


def gear_move_trial(pob: PobSession, xml: str, slot: str, n: int) -> list[dict]:
    """The shape `wishlist_gear.py:989` sends: one item-swap trial per candidate, `n` of them."""

    slot_name, raw = item_raw(xml, slot)
    return [{"item": {"slot": slot_name, "raw": raw}} for _ in range(n)]


def refine_move_trial(pob: PobSession, n: int) -> list[dict]:
    """The shape `tree_optimizer.py:970` sends: one leaf-removal trial per candidate leaf,
    cycling the build's own allocated nodes for `n` distinct candidates."""

    allocated = pob.tree_light().get("user_allocated_node_ids") or []
    if not allocated:
        raise RuntimeError("build has no user_allocated_node_ids")
    return [{"add": [], "remove": [int(allocated[i % len(allocated)])], "mastery": {}} for i in range(n)]


def item1_batch(out: dict) -> None:
    """Round-2 ask: reproduce the recorded per-call cost with the real batch shapes gear/refine
    send (GEAR_BATCH / REFINE_BATCH trials per call), not a single trial -- see the note above
    `GEAR_BATCH` for why the exact recorded batch size cannot be read from the records."""

    obj = objective()
    keys = list(obj.stat_keys)
    rows = []
    for label, path, gear_slot in (
        ("zombie_army_early-s4", ZOMBIE_POB, "Body Armour"),
        ("winter_orb-s5", WINTER_POB, "Body Armour"),
    ):
        xml = load_decoded(path)
        for kind, batch, builder in (
            ("gear (wishlist_gear.py:989)", GEAR_BATCH, lambda pob: gear_move_trial(pob, xml, gear_slot, GEAR_BATCH)),
            ("refine (tree_optimizer.py:970)", REFINE_BATCH, lambda pob: refine_move_trial(pob, REFINE_BATCH)),
        ):
            with open_session(f"diag169-item1b-{label}-{kind[:5]}") as pob:
                pob.load_xml(xml)
                trials = builder(pob)
                times = []
                for _ in range(20):
                    t0 = time.perf_counter()
                    pob.trial_stats(list(trials), keys, mode="fast")
                    times.append(time.perf_counter() - t0)
            s = summarize(times)
            per_trial = s["mean_s"] / batch
            rows.append({"build": label, "move": kind, "trials_per_call": batch, "s_per_call_mean": s["mean_s"], "s_per_call_median": s["median_s"], "s_per_trial": per_trial})
            print(f"item1b {label} {kind}: batch={batch} mean/call={s['mean_s']:.3f}s median/call={s['median_s']:.3f}s per_trial={per_trial*1000:.2f}ms")
    out["item1_batch"] = rows
    zombie_per_trial = [r["s_per_trial"] for r in rows if r["build"] == "zombie_army_early-s4"]
    winter_per_trial = [r["s_per_trial"] for r in rows if r["build"] == "winter_orb-s5"]
    factor = (statistics.mean(zombie_per_trial) / statistics.mean(winter_per_trial)) if winter_per_trial and statistics.mean(winter_per_trial) else None
    out["item1_batch_per_trial_factor"] = factor
    print(f"item1b per-trial factor (zombie/winter_orb, mean over both move kinds): {factor}")


def item1(out: dict) -> None:
    obj = objective()
    keys = list(obj.stat_keys)
    for label, path in (("zombie_army_early-s4", ZOMBIE_POB), ("winter_orb-s5", WINTER_POB)):
        xml = load_decoded(path)
        with open_session(f"diag169-item1-{label}") as pob:
            pob.load_xml(xml)
            times = time_calls(pob, keys, 20)
        out.setdefault("item1", {})[label] = summarize(times)
        print(f"item1 {label}: n={len(times)} mean={statistics.mean(times):.3f}s median={statistics.median(times):.3f}s")


def item2(out: dict) -> None:
    obj = objective()
    keys = list(obj.stat_keys)
    xml = load_decoded(ZOMBIE_POB)
    groups = find_flagged_groups(xml)
    flagged_enabled = [g for g in groups if g["flagged"] and g["enabled"]]
    with open_session("diag169-item2-zero") as pob:
        pob.load_xml(xml)
        zero = time_calls_n_trials(pob, keys, 0, 10)
    with open_session("diag169-item2-one") as pob:
        pob.load_xml(xml)
        one = time_calls_n_trials(pob, keys, 1, 10)
    out["item2"] = {
        "zero_trial_batch_s": summarize(zero),
        "one_trial_batch_s": summarize(one),
        "flagged_full_dps_groups": [{"label": g["label"], "gems": g["gems"]} for g in flagged_enabled],
        "flagged_full_dps_group_count": len(flagged_enabled),
    }
    print(f"item2: N=0 batch mean={statistics.mean(zero):.3f}s, N=1 batch mean={statistics.mean(one):.3f}s, flagged groups={len(flagged_enabled)}")


def variant_row(label: str, pob: PobSession, keys: list[str], obj: Objective, n: int, baseline_stats: dict | None) -> dict:
    times = time_calls(pob, keys, n)
    stats = stat_snapshot(pob, keys)
    score = obj.score(stats)
    row = {
        "label": label,
        "per_call": summarize(times),
        "CombinedDPS": stats.get("CombinedDPS"),
        "PhysicalMaximumHitTaken": stats.get("PhysicalMaximumHitTaken"),
        "Life": stats.get("Life"),
        "score_violation": score.violation,
        "score_value": score.value,
    }
    if baseline_stats is not None:
        for k in ("CombinedDPS", "PhysicalMaximumHitTaken", "Life"):
            base_v = baseline_stats.get(k)
            cur_v = stats.get(k)
            row[f"diff_{k}"] = (cur_v - base_v) if (base_v is not None and cur_v is not None) else None
    return row


def item3(out: dict) -> None:
    obj = objective()
    keys = list(obj.stat_keys)
    xml = load_decoded(ZOMBIE_POB)
    n = 10
    rows = []
    baseline_stats = None
    with open_session("diag169-item3-a") as pob:
        pob.load_xml(xml)
        row_a = variant_row("(a) as saved", pob, keys, obj, n, None)
        baseline_stats = {"CombinedDPS": row_a["CombinedDPS"], "PhysicalMaximumHitTaken": row_a["PhysicalMaximumHitTaken"], "Life": row_a["Life"]}
        rows.append(row_a)

    for skill in MINION_SKILLS:
        edited_xml, disabled_count = disable_gem_xml(xml, skill)
        with open_session(f"diag169-item3-b-{skill.replace(' ', '_')}") as pob:
            pob.load_xml(edited_xml)
            row = variant_row(f"(b) {skill} out of FullDPS (disabled {disabled_count} gem(s))", pob, keys, obj, n, baseline_stats)
            rows.append(row)

    # (c) only main skill counted: flag every group except "Main" out of FullDPS by disabling its gems'
    # main active skill (use disable_gem_xml on every flagged group's first active gem except Main's).
    groups = find_flagged_groups(xml)
    edited_xml = xml
    for g in groups:
        if not g["flagged"] or not g["enabled"] or g["label"] == "Main":
            continue
        for gem_name, enabled in g["gems"]:
            if enabled == "true":
                edited_xml, _ = disable_gem_xml(edited_xml, gem_name)
    with open_session("diag169-item3-c") as pob:
        pob.load_xml(edited_xml)
        rows.append(variant_row("(c) only main skill counted", pob, keys, obj, n, baseline_stats))

    # (d) fulldps_shortcut on
    with open_session("diag169-item3-d") as pob:
        pob.load_xml(xml)
        pob.fulldps_shortcut = True
        rows.append(variant_row("(d) fulldps_shortcut on", pob, keys, obj, n, baseline_stats))

    out["item3_zombie"] = rows
    for r in rows:
        print(f"item3 zombie {r['label']}: mean={r['per_call']['mean_s']:.3f}s CombinedDPS={r['CombinedDPS']}")


def item4(out: dict) -> None:
    obj = objective()
    keys = list(obj.stat_keys)
    xml = load_decoded(ZOMBIE_POB)
    n = 20
    with open_session("diag169-item4-a") as pob:
        pob.load_xml(xml)
        trial = real_trial(pob)
        a_scores = []
        for _ in range(n):
            outcome = pob.trial_stats([dict(trial)], keys, mode="fast")[0]
            s = obj.score(outcome.get("stats") or {})
            a_scores.append((s.violation, s.value))
    with open_session("diag169-item4-d") as pob:
        pob.load_xml(xml)
        pob.fulldps_shortcut = True
        trial = real_trial(pob)
        d_scores = []
        for _ in range(n):
            outcome = pob.trial_stats([dict(trial)], keys, mode="fast")[0]
            s = obj.score(outcome.get("stats") or {})
            d_scores.append((s.violation, s.value))
    equal = 0
    max_diff = 0.0
    for (av, aval), (dv, dval) in zip(a_scores, d_scores):
        if av == dv and aval == dval:
            equal += 1
        else:
            max_diff = max(max_diff, abs(av - dv), abs(aval - dval))
    out["item4"] = {"equal_count": equal, "of": n, "max_diff": max_diff, "a_scores": a_scores, "d_scores": d_scores}
    print(f"item4: equal {equal}/{n}, max diff {max_diff}")


def item5(out: dict) -> None:
    obj = objective()
    keys = list(obj.stat_keys)
    xml = load_decoded(WINTER_POB)
    n = 10
    rows = []
    baseline_stats = None
    with open_session("diag169-item5-a") as pob:
        pob.load_xml(xml)
        row_a = variant_row("(a) as saved", pob, keys, obj, n, None)
        baseline_stats = {"CombinedDPS": row_a["CombinedDPS"], "PhysicalMaximumHitTaken": row_a["PhysicalMaximumHitTaken"], "Life": row_a["Life"]}
        rows.append(row_a)

    groups = find_flagged_groups(xml)
    edited_xml = xml
    for g in groups:
        if not g["flagged"] or not g["enabled"] or g["label"] == "Main":
            continue
        for gem_name, enabled in g["gems"]:
            if enabled == "true":
                edited_xml, _ = disable_gem_xml(edited_xml, gem_name)
    with open_session("diag169-item5-c") as pob:
        pob.load_xml(edited_xml)
        rows.append(variant_row("(c) only main skill counted", pob, keys, obj, n, baseline_stats))

    with open_session("diag169-item5-d") as pob:
        pob.load_xml(xml)
        pob.fulldps_shortcut = True
        rows.append(variant_row("(d) fulldps_shortcut on", pob, keys, obj, n, baseline_stats))

    out["item5_winter_orb"] = rows
    for r in rows:
        print(f"item5 winter_orb {r['label']}: mean={r['per_call']['mean_s']:.3f}s CombinedDPS={r['CombinedDPS']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", default="1,2,3,4,5")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    items = {s.strip() for s in args.items.split(",") if s.strip()}
    out: dict = {}
    if "1" in items:
        item1(out)
    if "1b" in items:
        item1_batch(out)
    if "2" in items:
        item2(out)
    if "3" in items:
        item3(out)
    if "4" in items:
        item4(out)
    if "5" in items:
        item5(out)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
