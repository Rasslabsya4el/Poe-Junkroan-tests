"""#178: where the four bleed config inputs go missing, and what the wishlist fill compared.

MEASUREMENT ONLY. Nothing in the repo under test is changed: this script wraps pipeline /
PobSession / WishlistGear methods at run time and reads PoB. Driven by environment variables:

  DIAG_SLUG     one reference slug (default z329_juggernaut_boneshatter)
  DIAG_SEED     seed (default 4)
  DIAG_GEAR     gear mode (default wishlist)
  DIAG_FULL     "1" = the whole item 1/2/3/4 machinery; "0" = item 5 only
                (the four config inputs at the `tree greedy` record and around the
                `gear pass 2 (with tree)` fill: before its first trial, after its last)
  DIAG_OUT      json output path (absolute)
  DIAG_LOG      benchmark log path (absolute)
"""
from __future__ import annotations

import json
import os
import sys
import traceback

ROOT = os.path.abspath(os.getcwd())
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "src"))

# argv wins over the environment: the run queue starts a bare command line with no env
_a = sys.argv[1:]


def _arg(i: int, env: str, default: str | None) -> str | None:
    if len(_a) > i and _a[i] not in ("", "-"):
        return _a[i]
    return os.environ.get(env, default)


SLUG = _arg(0, "DIAG_SLUG", "z329_juggernaut_boneshatter")
SEED = int(_arg(1, "DIAG_SEED", "4"))
GEAR = _arg(2, "DIAG_GEAR", "wishlist")
FULL = _arg(3, "DIAG_FULL", "1") == "1"
OUT = _arg(4, "DIAG_OUT", r"C:/Coding/poe-junkroan-v2/artifacts/runs/diag178.json")
LOG = _arg(5, "DIAG_LOG", r"C:/Coding/poe-junkroan-v2/artifacts/runs/diag178.log")
AUTHOR_CACHE = _arg(6, "DIAG_AUTHOR_CACHE", None) or None

import benchmark  # noqa: E402
from junkroan.optimizer import judging as jd  # noqa: E402
from junkroan.optimizer import pipeline as pl  # noqa: E402
from junkroan.optimizer import wishlist_gear as wg  # noqa: E402

FOUR = ("conditionEnemyBleeding", "multiplierBleedsOnEnemy", "overrideBleedStackPotential", "multiplierRage")
IGNITE = ("conditionEnemyIgnited", "conditionEnemyBurning", "overrideIgniteStackPotential", "multiplierIgnitesOnEnemy")
EXTRA = ("CombinedDPS", "TotalDPS", "BleedDPS", "IgniteDPS", "TotalDotDPS", "RampSeconds", "Life")

out: dict = {"slug": SLUG, "seed": SEED, "gear_mode": GEAR, "full": FULL, "root": ROOT}
state: dict = {"stage": "start", "n": 0, "pipeline": None, "skeleton": None, "derived": None,
               "in_fill": False, "greedy": False}
transitions: list[dict] = []
calls: dict[str, int] = {}
keep: list[dict] = []
slots: list[dict] = []
greedy_steps: dict = {}


class Stop(Exception):
    pass


def _watched(pob) -> dict:
    try:
        ci = pob.config_inputs()
    except Exception:
        return {"error": "config_inputs failed"}
    return {k: ci.get(k) for k in FOUR + IGNITE if k in ci}


def _probe(self, *, heavy: bool = True) -> dict:
    d: dict = {}
    try:
        full = self.pob.stats(tuple(self.objective.stat_keys) + EXTRA)
        s = self.objective.score(full)
        d["value"], d["violation"] = s.value, s.violation
        d["stats"] = {k: full.get(k) for k in EXTRA}
        if heavy:
            d["violations"] = {k: v for k, v in self.objective.violations(full).items() if v}
    except Exception:
        d["score_error"] = traceback.format_exc(limit=2)
    try:
        ci = dict(self.pob.config_inputs())
        d["config_inputs"] = ci
        d["four"] = {k: ci.get(k, "ABSENT") for k in FOUR}
        d["ignite"] = {k: ci.get(k, "ABSENT") for k in IGNITE}
    except Exception:
        d["config_error"] = traceback.format_exc(limit=2)
    return d


# ---------------------------------------------------------------- the lanes' derivation (post-#42: judging.read_lanes)
_orig_read_lanes = jd.read_lanes
_orig_write_lanes = jd.write_lanes


def _read_lanes(pob, **kw):
    d = _orig_read_lanes(pob, **kw)
    state["derived"] = d
    state["derived_inputs"] = dict(d.conservative.inputs)
    return d


jd.read_lanes = _read_lanes


# ------------------------------------------------- PobSession call transitions
def _caller() -> str:
    for fr in reversed(traceback.extract_stack()[:-2]):
        if "diag178_probe" in fr.filename:
            continue
        return f"{os.path.basename(fr.filename)}:{fr.lineno} {fr.name}"
    return "?"


def _wrap_pob(cls, name: str) -> None:
    orig = getattr(cls, name, None)
    if orig is None:
        return

    def wrapper(self, *a, **kw):
        state["n"] += 1
        calls[name] = calls.get(name, 0) + 1
        before = _watched(self)
        try:
            return orig(self, *a, **kw)
        finally:
            after = _watched(self)
            if before != after and len(transitions) < 400:
                transitions.append({"n": state["n"], "stage": state["stage"], "call": name,
                                    "caller": _caller(), "before": before, "after": after,
                                    "args": str(list(a))[:160] + str(sorted(kw))[:160]})

    setattr(cls, name, wrapper)


def _wrap_module_fn(mod, name: str) -> None:
    orig = getattr(mod, name)

    def wrapper(pob, *a, **kw):
        state["n"] += 1
        calls[name] = calls.get(name, 0) + 1
        before = _watched(pob)
        try:
            return orig(pob, *a, **kw)
        finally:
            after = _watched(pob)
            if before != after and len(transitions) < 400:
                transitions.append({"n": state["n"], "stage": state["stage"], "call": name,
                                    "caller": _caller(), "before": before, "after": after,
                                    "args": str(list(a))[:160]})

    setattr(mod, name, wrapper)


# ------------------------------------------------------------------- the stages
_orig_record = pl.BuildPipeline._record
_orig_rejudge = jd.Judging.rejudge


def _record(self, result, name, t0, notes=""):
    _orig_record(self, result, name, t0, notes)
    st = result.stages[-1]
    state["pipeline"] = self
    rec = {"value": st.score_value, "violation": st.violation, "notes": st.notes, "seconds": st.seconds}
    out.setdefault("stage_records", {})[name] = rec
    if not FULL:
        if name == "tree greedy":
            out["p5_tree_greedy"] = _probe(self)
        state["stage"] = f"after {name}"
        if name == "gear pass 2 (with tree)":
            out["p8_after_gear2"] = _probe(self)
            raise Stop(name)
        return
    if name == "config (conservative lane)":
        out["p1_config_lane"] = _probe(self)
        state["derived_inputs_at_config_stage"] = state.get("derived_inputs")
    if name in ("gear pass 1 (empty tree)", "gear pass 1 (rig tree)"):
        out["p2_gear1"] = _probe(self)
    if name == "tree greedy":
        out["p5_tree_greedy"] = _probe(self)
        _item3(self, result)
    if name == "gear pass 2 (with tree)":
        out["p8_after_gear2"] = _probe(self)
        raise Stop(name)
    state["stage"] = f"after {name}"


def _item3(self, result) -> None:
    """Item 3: the `tree greedy` record re-measured with the four inputs written back.

    No `rejudge` runs between the config stage and the first generator node, so the
    derivation is taken here as `Judging.rejudge` takes it (`read_lanes`), and written with
    the lanes' own `write_lanes`. The build is restored from its own XML after.
    """

    info: dict = {}
    try:
        skeleton = getattr(result, "skeleton", None) or state.get("skeleton")
        if skeleton is None:
            info["error"] = "no skeleton on the BuildResult"
            out["p_item3"] = info
            return
        xml0 = self.pob.export_xml()
        derived = _orig_read_lanes(self.pob)
        info["derived_inputs_here"] = dict(derived.conservative.inputs)
        info["derived_inputs_at_config_stage"] = state.get("derived_inputs_at_config_stage")
        _orig_write_lanes(self.pob, skeleton, derived, log=lambda _m: None)  # exactly what `rejudge` writes, nothing else
        info["with_inputs"] = _probe(self)
        self.pob.load_xml(xml0)
        info["restored"] = _probe(self)
    except Exception:
        info["error"] = traceback.format_exc(limit=3)
    out["p_item3"] = info


def _rejudge(self, skeleton, **kw):
    """`Judging.rejudge`: counted while `tree greedy` runs (its `after_apply_hook`)."""

    state["skeleton"] = skeleton
    res = _orig_rejudge(self, skeleton, **kw)
    pipe = state.get("pipeline")
    if state["greedy"] and pipe is not None:
        p = _probe(pipe, heavy=False)
        greedy_steps.setdefault("first", p)
        greedy_steps["last"] = p
        greedy_steps["n"] = greedy_steps.get("n", 0) + 1
    return res


# ------------------------------------------------------- the wishlist fill (item 4)
_orig_fill = wg.WishlistGear.fill
_orig_fill_slot = wg.WishlistGear.fill_slot
_orig_keep = wg.WishlistGear._keep_incumbent


def _fill(self, *a, **kw):
    pipe = state.get("pipeline")
    if state.get("stage") == "after tree greedy" and pipe is not None:
        out["p6_before_fill"] = _probe(pipe)
        out["fill_objective_is_pipeline_objective"] = self.objective is pipe.objective
        out["fill_objective_id"] = [id(self.objective), id(pipe.objective)]
        state["in_fill"] = FULL
        try:
            return _orig_fill(self, *a, **kw)
        finally:
            state["in_fill"] = False
            out["p7_after_fill"] = _probe(pipe)
    return _orig_fill(self, *a, **kw)


def _fill_slot(self, slot, base, **kw):
    if not (FULL and state.get("in_fill")):
        return _orig_fill_slot(self, slot, base, **kw)
    incumbent_before = self.current_raw.get(slot)
    state["keep_called"] = None
    res = _orig_fill_slot(self, slot, base, **kw)
    inc: dict = {}
    try:
        # the incumbent's own Score on the build as the fill leaves it, whether or not
        # `_keep_incumbent` was reached (`wishlist_gear.py:1652` skips it on a live replan)
        if incumbent_before and incumbent_before != res.raw:
            o = self.pob.trial_stats([{"item": {"slot": slot, "raw": incumbent_before}}], self.objective.stat_keys, mode="fast")[0]
            if o.get("ok") and o.get("stats"):
                s = self.objective.score(o["stats"])
                inc = {"incumbent_value": s.value, "incumbent_violation": s.violation}
    except Exception:
        inc = {"incumbent_error": traceback.format_exc(limit=2)}
    try:
        after = self.objective.score(self.pob.stats(self.objective.stat_keys))
        slots.append({"i": len(slots), "slot": slot, "base_asked": base, "base_taken": res.base,
                      "keep_incumbent_called": state.get("keep_called"), **inc,
                      "kept_incumbent": bool(getattr(res, "kept_incumbent", False)),
                      "incumbent_raw": (incumbent_before or "")[:90].replace("\n", " | "),
                      "new_raw": (res.raw or "")[:90].replace("\n", " | "),
                      "value_after": after.value, "violation_after": after.violation,
                      "objective_is_pipeline": self.objective is (state.get("pipeline").objective if state.get("pipeline") else None)})
    except Exception:
        slots.append({"slot": slot, "error": traceback.format_exc(limit=2)})
    return res


def _keep_incumbent(self, slot, result, score, *, resistance=None):
    if not (FULL and state.get("in_fill")):
        return _orig_keep(self, slot, result, score, resistance=resistance)
    state["keep_called"] = True
    row: dict = {"i": len(keep), "slot_index": len(slots), "slot": slot, "new_value": score.value, "new_violation": score.violation,
                 "resistance": resistance, "new_base": result.base}
    incumbent = self.current_raw.get(slot)
    row["has_incumbent"] = bool(incumbent)
    row["same_raw"] = bool(incumbent) and incumbent == result.raw
    try:
        # the very trial the comparison at wishlist_gear.py:1579-1584 makes, read here too so the
        # number exists even on the paths that return before making it
        if incumbent and incumbent != result.raw:
            o = self.pob.trial_stats([{"item": {"slot": slot, "raw": incumbent}}], self.objective.stat_keys, mode="fast")[0]
            if o.get("ok") and o.get("stats"):
                inc = self.objective.score(o["stats"])
                row["incumbent_value"], row["incumbent_violation"] = inc.value, inc.violation
                row["incumbent_gt_new"] = bool(inc > score)
            else:
                row["trial"] = "not ok"
    except Exception:
        row["probe_error"] = traceback.format_exc(limit=2)
    ret = _orig_keep(self, slot, result, score, resistance=resistance)
    row["returned_value"], row["returned_violation"] = ret.value, ret.violation
    row["kept"] = bool(getattr(result, "kept_incumbent", False))
    row["objective_is_pipeline"] = self.objective is (state.get("pipeline").objective if state.get("pipeline") else None)
    if len(keep) < 200:
        keep.append(row)
    return ret


_orig_allocate = pl.TreeOptimizer.allocate


def _allocate(self, *a, **kw):
    """`tree greedy` is one `allocate`; its steps are the `after_apply_hook` rejudges."""

    greedy_steps.clear()
    state["greedy"] = FULL
    state["stage"] = "tree greedy (running)"
    try:
        return _orig_allocate(self, *a, **kw)
    finally:
        state["greedy"] = False


pl.TreeOptimizer.allocate = _allocate
pl.BuildPipeline._record = _record
jd.Judging.rejudge = _rejudge
wg.WishlistGear.fill = _fill
wg.WishlistGear.fill_slot = _fill_slot
wg.WishlistGear._keep_incumbent = _keep_incumbent

if FULL:
    from junkroan.pob.session import PobSession

    for _m in ("set_config", "load_xml", "set_items", "equip", "set_tree", "set_skills", "set_identity", "mutate_nodes"):
        _wrap_pob(PobSession, _m)
    for _f in ("write_lanes", "apply_custom_mods", "apply_ailment_stack_caps"):
        if hasattr(jd, _f):
            _wrap_module_fn(jd, _f)

try:
    row = benchmark.run_one(SLUG, log_path=LOG, seed=SEED, gear_mode=GEAR, construction="classic",
                            loop_seconds=60.0, author_cache=AUTHOR_CACHE)
    out["run_one"] = {k: row.get(k) for k in ("ok", "error")}
except Exception:
    out["crash"] = traceback.format_exc()

out["p3_greedy_first"] = greedy_steps.get("first")
out["p4_greedy_last"] = greedy_steps.get("last")
out["greedy_rejudges"] = greedy_steps.get("n")
out["transitions"] = transitions
out["calls"] = calls
out["keep_incumbent"] = keep
out["fill_slots"] = slots

b = out.get("p6_before_fill") or {}
a = out.get("p7_after_fill") or {}
bc, ac = b.get("config_inputs") or {}, a.get("config_inputs") or {}
out["config_inputs_changed"] = {k: [bc.get(k, "ABSENT"), ac.get(k, "ABSENT")]
                                for k in sorted(set(bc) | set(ac)) if bc.get(k, "ABSENT") != ac.get(k, "ABSENT")}

with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1, default=str)

print("SLUG %s seed %s gear %s full %s" % (SLUG, SEED, GEAR, FULL))
for key in ("p1_config_lane", "p2_gear1", "p3_greedy_first", "p4_greedy_last", "p5_tree_greedy",
            "p6_before_fill", "p7_after_fill"):
    p = out.get(key)
    if not p:
        continue
    print("%-20s value %-14.1f viol %-10.4f four %s" % (key, p.get("value") or -1, p.get("violation") or -1,
                                                        json.dumps(p.get("four"))))
print("item3: %s" % json.dumps({k: (v.get("value") if isinstance(v, dict) else v) for k, v in (out.get("p_item3") or {}).items()}))
print("transitions on the four: %d" % len(transitions))
for t in transitions[:20]:
    print("  n=%d %-28s %-34s %s -> %s" % (t["n"], t["call"], t["caller"], json.dumps(t["before"]), json.dumps(t["after"])))
print("config inputs changed across the gear pass 2 fill (first trial -> last trial): %s" % json.dumps(out["config_inputs_changed"])[:1500])
print("written: %s" % OUT)
