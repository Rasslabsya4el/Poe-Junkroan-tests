"""Why a build looks the way it does, from the optimizer's own trace (ROADMAP Phase 6).

Everything here is read back from what the pipeline recorded: the picks PoB
made (skill part, supports, utilities), the tree steps with their measured
gains, the config lanes with the proof behind every conservative input, the
stage trajectory, the audit. No prose about strength is authored here; every
sentence carries the number it came from.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

_STAGE_SHORT = {
    "skeleton applied": "skeleton",
    "config (conservative lane)": "config",
    "gear pass 1 (empty tree)": "gear 1",
    "tree greedy": "tree",
    "gear pass 2 (with tree)": "gear 2",
    "tree rebuilt on gear": "tree rebuilt",
    "supports re-picked": "supports",
    "utility links": "utilities",
    "tree refine": "refine",  # the screen's cheap path; the loop's stages are "loop pass N" and need no short name
    "config (final lanes)": "final config",
    "fixed point check": "fixed point",  # 7.3: one more pass of local moves on the finished build
}


def _fmt(v: Any) -> str:
    return f"{v:,.0f}" if isinstance(v, (int, float)) else str(v)


def _plain(name: str) -> str:
    """Step names carry the pass that made them ("Golem's Blood (swap -3)"); the node is what matters."""

    return name.split(" (swap")[0].strip()


def _pct(a: float, b: float) -> str:
    return f"{(a / b - 1):+.0%}" if b else "n/a"


def explain(result: Any, *, variants: Sequence[tuple[str, float]] = (), reference: float | None = None) -> str:
    """Markdown: structure, weapon, links, tree, gear, config proofs, numbers, audit, trajectory."""

    sk = result.skeleton
    aura_levels = dict(getattr(sk, "aura_levels", {}) or {})
    f = result.final_stats or {}
    stat = getattr(result, "objective_stat", "CombinedDPS")
    lines: list[str] = ["**Why this build looks like this**", ""]

    # structure
    asc = f"{sk.class_name}/{sk.ascendancy}"
    keystones = list(getattr(result, "keystones", []) or [])
    var_by_label = {label: value for label, value in variants}
    ks_notes = []
    for k in keystones:
        v = var_by_label.get(f"without {k}")
        ks_notes.append(f"{k}" + (f" (rebuilt without it: {_fmt(v)}, {_pct(v, f.get('CombinedDPS') or 0)})" if v is not None else ""))
    lines.append(f"- Structure: {asc}; keystones: {', '.join(ks_notes) or 'none'}" + (f"; forbidden by the request: {', '.join(sk.forbid_keystones)}" if sk.forbid_keystones else "") + ".")

    # weapon
    w1 = sk.uniques.get("Weapon 1") or sk.rare_bases.get("Weapon 1")
    w2 = sk.uniques.get("Weapon 2") or sk.rare_bases.get("Weapon 2")
    alts = [(label[len("weapon "):], v) for label, v in variants if label.startswith("weapon ")]
    if w1:
        lines.append(f"- Weapon: {w1}" + (f" + {w2}" if w2 else "") + (" (alternatives rebuilt as whole builds: " + ", ".join(f"{b} {_fmt(v)}" for b, v in alts) + ")" if alts else "") + ".")

    # links
    picks = list(getattr(result, "picks", []) or [])
    part = next((p for p in picks if p.get("what") == "skill part"), None)
    supports = [p for p in picks if p.get("what") == "supports"]
    utilities = [p for p in picks if p.get("what") == "utilities"]
    main = " + ".join(f"{name} (level {aura_levels[name]})" if name in aura_levels else name for name in sk.main_link)
    lines.append(f"- Main link: {main}" + (f"; skill part '{part['choice']}' (best of the parts by PoB)" if part else "")
                 + (f"; supports chosen by PoB ({supports[-1]['choice']}; value {_fmt(supports[-1].get('before'))} -> {_fmt(supports[-1].get('value'))})" if supports else "") + ".")

    def _group(g) -> str:
        # a group PoB dropped to buy a floor stays in the build, disabled (D72): say so, or the
        # explanation reads as if the build were still running the aura
        return ", ".join(f"{name} (level {aura_levels[name]})" if name in aura_levels else name for name in g.gems) + ("" if getattr(g, "enabled", True) else " [off: dropped to meet a floor]")

    extra = [g.gems for g in sk.extra_groups]
    fixed = [_group(g) for g in sk.extra_groups if not getattr(g, "picked", False)]
    picked = [_group(g) for g in sk.extra_groups if getattr(g, "picked", False)]
    if extra:
        lines.append("- Other links: " + ("; ".join(fixed) if fixed else "none from the request")
                     + (f"; picked by PoB: {'; '.join(picked)}" + (f" ({_fmt(utilities[-1].get('before'))} -> {_fmt(utilities[-1].get('value'))})" if utilities else "") if picked else "") + ".")

    # tree
    steps = list(getattr(result, "tree_steps", []) or [])
    if steps:
        best: dict[str, dict] = {}  # a node taken, swapped out and taken again appears once, with its largest measured gain
        for s in steps:
            if s.get("kind") in ("notable", "keystone", "mastery", "cluster") and (s.get("gain") or 0) > 0:
                name = _plain(s["name"])
                if name not in best or s["gain"] > best[name]["gain"]:
                    best[name] = {**s, "name": name}
        top = sorted(best.values(), key=lambda s: -s["gain"])[:8]
        total = f.get("CombinedDPS") or 0
        lines.append(f"- Tree: {len(steps)} kept steps; largest single gains when taken: " + ", ".join(f"{s['name']} {_fmt(s['gain'])}" + (f" ({s['gain'] / total:.0%})" if total else "") for s in top) + ".")
        masteries = list(dict.fromkeys(_plain(s["name"]) for s in steps if s.get("kind") == "mastery"))
        if masteries:
            lines.append(f"- Masteries: {', '.join(masteries)}.")
    leaves = list(getattr(result, "tree_leaves", []) or [])
    if leaves:
        from junkroan.optimizer.objective import Objective
        from junkroan.optimizer.tree_hygiene import render_tree_leaf_table

        lines.extend(("", render_tree_leaf_table(leaves, objective=Objective(maximize=stat))))

    # gear
    uniques = [f"{slot}: {name}" for slot, name in sk.uniques.items()]
    gear_how = ("rares follow the day-1 template: life plus one resistance at the authors' per-slot median tier and an open-or-craft line, boots with movement speed, weapons fully open with three open lines and one craft; up to two items add a marked extra resistance line when needed (D79)"
                 if getattr(result, "gear_mode", "loot") == "wishlist" else
                 "rares are the best of the rails' loot rolls per slot plus one bench craft")
    lines.append(f"- Gear: {gear_how}" + (f"; uniques: {', '.join(uniques)}" if uniques else "; no uniques") + ".")
    shopping = list(getattr(result, "gear_shopping", []) or [])
    if shopping:
        lines.append("- Day-1 shopping list:")
        for item in shopping:
            head = f"{item['slot']}: {item['base']}" + (f" ({item['implicit']})" if item.get("implicit") else "")
            details = []
            for line in item.get("lines") or []:
                if line.get("skipped"):
                    details.append(f"{line['kind']} {line['line']} [unavailable]")
                    continue
                tier = f" T{line['tier']}" if line.get("tier") else ""
                delta = f", delta {_fmt(line['delta'])}" if isinstance(line.get("delta"), (int, float)) else ""
                kind = "extra resistance line" if line.get("kind") == "extra_resistance" else line["kind"]
                details.append(f"{kind}{tier} {line['line']}{delta}")
            lines.append(f"  {head}: " + "; ".join(details) + ".")

    # config
    reasons: Mapping[str, str] = getattr(result, "config_reasons", {}) or {}
    on = [(k, v) for k, v in reasons.items() if not str(v).startswith("off") and k != "enemyIsBoss"]
    if on:
        lines.append("- The conservative number relies on: " + "; ".join(f"{k} ({str(v)[:90]})" for k, v in on) + ".")
    c, o = (result.conservative_stats or {}).get(stat), (result.optimistic_stats or {}).get(stat)
    if isinstance(c, (int, float)) and isinstance(o, (int, float)) and c:
        lines.append(f"- Optimistic lane (every unproven toggle on): {stat} {_fmt(o)} ({_pct(o, c)} over conservative).")
    for note in getattr(result, "pending_facts", ()) or ():
        lines.append(f"- Pending research fact (not in the conservative number until approved): {note}.")

    # numbers
    ramp = f.get("RampSeconds")
    budget = f.get("RampBudget")
    number = result.scored_number()  # #1055: the maximised output's real number (the stage's when final_stats lacks its key)
    lines.append(f"- Numbers: {stat} {_fmt(number) if number is not None else 'n/a'} conservative" + (f" ({_pct(number, reference)} vs the reference {_fmt(reference)})" if reference and number is not None else "")
                 + f"; life {f.get('Life')}, max hit {_fmt(min((f.get(k) for k in ('PhysicalMaximumHitTaken', 'FireMaximumHitTaken', 'ColdMaximumHitTaken', 'LightningMaximumHitTaken') if isinstance(f.get(k), (int, float))), default=None))} (bossing: no block), EHP {_fmt(f.get('TotalEHP'))} (mapping), resists {f.get('FireResist')}/{f.get('ColdResist')}/{f.get('LightningResist')}/{f.get('ChaosResist')}, movement {f.get('EffectiveMovementSpeedMod', 0):.2f}"
                  + (f", ramp {ramp:.1f} s against a {budget:.1f} s budget" if isinstance(ramp, (int, float)) and isinstance(budget, (int, float)) else "") + ".")
    pinnacle = getattr(result, "pinnacle_ramp_dps", None)
    pinnacle_seconds = getattr(result, "pinnacle_ramp_seconds", None)
    if isinstance(pinnacle, (int, float)) and isinstance(pinnacle_seconds, (int, float)):
        lines.append(f"- Pinnacle boss ramp ({pinnacle_seconds:g} s, report only): {stat} {_fmt(pinnacle)}.")

    # mapping: text, never a score (the objective is bossing)
    mapping = list(getattr(result, "mapping", []) or [])
    if mapping:
        lines.append("- Mapping (not scored): " + "; ".join(mapping) + ".")

    # audit
    audit = list(getattr(result, "audit", []) or [])
    lines.append("- Audit: " + ("clean" if not audit else "; ".join(str(a) for a in audit)) + ".")

    # trajectory
    traj = [(_STAGE_SHORT.get(s.name, s.name), s.score_value) for s in (result.stages or []) if isinstance(s.score_value, (int, float)) and s.score_value > 0]
    if traj:
        lines.append("- Trajectory: " + " -> ".join(f"{n} {_fmt(v)}" for n, v in traj) + ".")
    return "\n".join(lines)


def pareto_front(rows: Sequence[Mapping[str, Any]], *, keys: Sequence[str] = ("value", "ehp")) -> set[int]:
    """Indices of rows no other row dominates (>= on every key, > on one)."""

    front: set[int] = set()
    for i, r in enumerate(rows):
        dominated = False
        for j, o in enumerate(rows):
            if i == j:
                continue
            if all((o.get(k) or 0) >= (r.get(k) or 0) for k in keys) and any((o.get(k) or 0) > (r.get(k) or 0) for k in keys):
                dominated = True
                break
        if not dominated:
            front.add(i)
    return front


__all__ = ["explain", "pareto_front"]
