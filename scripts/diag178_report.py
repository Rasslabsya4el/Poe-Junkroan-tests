"""#178: the probe's JSON into the tables of items 1, 4 and 5. Read-only."""
from __future__ import annotations

import json
import sys

FOUR = ("conditionEnemyBleeding", "multiplierBleedsOnEnemy", "overrideBleedStackPotential", "multiplierRage")
IGNITE = ("conditionEnemyIgnited", "conditionEnemyBurning", "overrideIgniteStackPotential", "multiplierIgnitesOnEnemy")


def f(x, nd=0):
    if x is None:
        return "-"
    try:
        return f"{float(x):,.{nd}f}"
    except Exception:
        return str(x)


def four(p, keys=FOUR):
    if not p:
        return "-"
    ci = p.get("config_inputs") or {}
    return " ".join(("%s=%s" % (k.replace("condition", "cond").replace("multiplier", "mul").replace("override", "ovr"), ci[k])) if k in ci else ("%s:ABSENT" % k.replace("condition", "cond").replace("multiplier", "mul").replace("override", "ovr")) for k in keys)


def main(path: str) -> None:
    d = json.load(open(path, encoding="utf-8"))
    print("## %s seed %s gear %s   run_one=%s" % (d["slug"], d["seed"], d["gear_mode"], d.get("run_one")))
    print("\n### item 1 / item 5: the points")
    rows = [("config (conservative lane) record", "p1_config_lane"),
            ("gear pass 1 record", "p2_gear1"),
            ("tree greedy, first rejudge", "p3_greedy_first"),
            ("tree greedy, last rejudge (%s rejudges)" % d.get("greedy_rejudges"), "p4_greedy_last"),
            ("tree greedy record", "p5_tree_greedy"),
            ("before the fill's first trial", "p6_before_fill"),
            ("after the fill's last trial", "p7_after_fill"),
            ("gear pass 2 record", "p8_after_gear2")]
    print("| point | CombinedDPS | BleedDPS | IgniteDPS | violation | the four inputs |")
    print("|---|---:|---:|---:|---|")
    for label, key in rows:
        p = d.get(key)
        if not p:
            continue
        st = p.get("stats") or {}
        print("| %s | %s | %s | %s | %s | %s |" % (label, f(st.get("CombinedDPS")), f(st.get("BleedDPS")),
                                                   f(st.get("IgniteDPS")), f(p.get("violation"), 4), four(p)))
    for label, key in rows:
        p = d.get(key)
        if p and any(k in (p.get("config_inputs") or {}) for k in IGNITE):
            print("  ignite inputs at %s: %s" % (label, four(p, IGNITE)))
    print("\nstage records: %s" % json.dumps({k: [round(v["value"], 1), round(v["violation"], 6)] for k, v in (d.get("stage_records") or {}).items()}))

    it3 = d.get("p_item3") or {}
    if it3:
        wi, rs = it3.get("with_inputs") or {}, it3.get("restored") or {}
        print("\n### item 3: the tree greedy record re-measured with the four inputs written back")
        print("  recorded          %s (viol %s)" % (f((d.get("p5_tree_greedy") or {}).get("value")), f((d.get("p5_tree_greedy") or {}).get("violation"), 4)))
        print("  with inputs back  %s (viol %s)  BleedDPS %s  four %s" % (f(wi.get("value")), f(wi.get("violation"), 4), f((wi.get("stats") or {}).get("BleedDPS")), four(wi)))
        print("  restored          %s (viol %s)  four %s" % (f(rs.get("value")), f(rs.get("violation"), 4), four(rs)))
        print("  derived conservative inputs at the config stage: %s" % json.dumps(it3.get("derived_inputs_at_config_stage"), sort_keys=True))
        print("  derived conservative inputs at this record:      %s" % json.dumps(it3.get("derived_inputs_here"), sort_keys=True))
        if it3.get("error"):
            print("  error: %s" % it3["error"])

    tr = d.get("transitions") or []
    print("\n### item 2: every call after which the watched inputs changed (%d)" % len(tr))
    for t in tr:
        print("  n=%-6s %-14s %-28s %-40s\n        %s\n     -> %s" % (t["n"], t["stage"], t["call"], t["caller"],
                                                                     json.dumps(t["before"]), json.dumps(t["after"])))
    print("calls wrapped: %s" % json.dumps(d.get("calls")))

    ki = d.get("keep_incumbent") or []
    sl = d.get("fill_slots") or []
    if ki or sl:
        print("\n### item 4: the fill's comparisons (objective is the pipeline's: %s)" % d.get("fill_objective_is_pipeline_objective"))
        print("| # | slot | new item Score (value / violation) | incumbent Score (value / violation) | incumbent > new | kept | returned |")
        print("|---|---|---|---|---|---|---|")
        for r in ki:
            print("| %s | %s | %s / %s | %s / %s | %s | %s | %s / %s |" % (
                r.get("i"), r.get("slot"), f(r.get("new_value")), f(r.get("new_violation"), 6),
                f(r.get("incumbent_value")), f(r.get("incumbent_violation"), 6),
                r.get("incumbent_gt_new"), r.get("kept"), f(r.get("returned_value")), f(r.get("returned_violation"), 6)))
        print("\n| # | slot | base taken | _keep_incumbent called | incumbent Score | Score after the slot | kept |")
        print("|---|---|---|---|---|---|---|")
        for r in sl:
            print("| %s | %s | %s | %s | %s / %s | %s / %s | %s |" % (
                r.get("i"), r.get("slot"), r.get("base_taken"), r.get("keep_incumbent_called"),
                f(r.get("incumbent_value")), f(r.get("incumbent_violation"), 6),
                f(r.get("value_after")), f(r.get("violation_after"), 6), r.get("kept_incumbent")))
    print("\nconfig inputs changed across the gear pass 2 fill: %s" % json.dumps(d.get("config_inputs_changed")))


if __name__ == "__main__":
    main(sys.argv[1])
