"""#189 unit 1: what one `Judging.rejudge` costs at the `tree greedy` build, and how many nodes `tree greedy` applies.

MEASUREMENT ONLY. No stored artefact keeps the stage builds, so the pipeline runs for one row
(default z329_juggernaut_boneshatter seed 4, wishlist gear) and stops right after the `tree greedy`
record; there 20 `rejudge` calls are timed. Args: slug seed gear (all optional).
Prints `rejudge mean <x> s over 20, nodes <n>, added <human duration>`.
"""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.abspath(os.getcwd())
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "src"))

SLUG = sys.argv[1] if len(sys.argv) > 1 else "z329_juggernaut_boneshatter"
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 4
GEAR = sys.argv[3] if len(sys.argv) > 3 else "wishlist"
CALLS = 20
LOG = os.path.join(ROOT, "tmp_189_cost.log")

import benchmark  # noqa: E402
from junkroan.optimizer import config_rules as _cr  # noqa: E402

if os.environ.get("JUNKROAN_UNCAPPED_BY_RELOAD"):  # #508: the base side of the pair, the pre-#508 two-load read
    _cr.uncapped_ailment_stats = _cr.uncapped_ailment_stats_by_reload
from junkroan.optimizer import pipeline as pl  # noqa: E402
from junkroan.optimizer.judging import Judging  # noqa: E402
from junkroan.report_format import human_duration  # noqa: E402


class Stop(BaseException):
    pass


st: dict = {"skeleton": None, "prev_nodes": set(), "prev_name": None, "in_greedy": 0}
res: dict = {}

_orig_rejudge = Judging.rejudge
_orig_record = pl.BuildPipeline._record
_orig_allocate = pl.TreeOptimizer.allocate


def _rejudge(self, skeleton, **kw):
    st["skeleton"] = skeleton
    if st["in_greedy"]:
        res["greedy_rejudges"] = res.get("greedy_rejudges", 0) + 1
    return _orig_rejudge(self, skeleton, **kw)


def _allocate(self, *a, **kw):
    st["in_greedy"] += 1
    try:
        return _orig_allocate(self, *a, **kw)
    finally:
        st["in_greedy"] -= 1


def _record(self, result, name, t0, notes=""):
    _orig_record(self, result, name, t0, notes)
    nodes = self._tree_nodes(self.pob)
    if name == "tree greedy":
        res["before_name"] = st["prev_name"]
        res["nodes"] = len(nodes - st["prev_nodes"])
        res["nodes_removed"] = len(st["prev_nodes"] - nodes)
        res["record_seconds"] = result.stages[-1].seconds
        times = []
        for _ in range(CALLS):
            t = time.perf_counter()
            self.judging.rejudge(st["skeleton"])
            times.append(time.perf_counter() - t)
        res["times"] = times
        _read_cost(self)
        raise Stop(name)
    st["prev_nodes"], st["prev_name"] = nodes, name


def _planned(self, skeleton, lanes):
    """The lane inputs `PobLanes.write` would hand `set_config` (no write), as plain data."""
    from junkroan.optimizer.config_rules import config_surfaces
    from junkroan.optimizer.judging import plan_config
    plan = plan_config(self.pob.config_inputs(), lanes, tuned_choices=getattr(skeleton, "tuned_choices", None),
                       user_config=skeleton.user_config, known_vars=set(config_surfaces()))
    return (plan.inputs, plan.conditional, plan.stack_caps, tuple(plan.custom_mods))


def _profile_parts(self):
    """Seconds per main part inside one `read_lanes` (inclusive; parts nest): PobSession methods and
    config_rules helpers, each wrapped, mean of 3 calls."""
    import functools
    from junkroan.optimizer import config_rules as cr
    parts: dict[str, float] = {}
    calls: dict[str, int] = {}
    undo = []

    def wrap(owner, attr):
        fn = getattr(owner, attr, None)
        if not callable(fn):
            return

        @functools.wraps(fn)
        def timed(*a, **kw):
            t = time.perf_counter()
            calls[attr] = calls.get(attr, 0) + 1
            try:
                return fn(*a, **kw)
            finally:
                parts[attr] = parts.get(attr, 0.0) + time.perf_counter() - t
        setattr(owner, attr, timed)
        undo.append((owner, attr, fn))

    for attr in ("config_options", "stats", "config_inputs", "calc_raw", "export_xml", "load_xml", "parse_mods",
                 "active_skill_stats", "read_state", "stats_without_ailment_caps"):
        wrap(type(self.pob), attr)
    for attr in ("build_text", "build_facts", "parse_mods_batch", "flask_add_kills_per_second", "generator_source_contexts",
                 "_gem_tags", "_main_skill_tags", "_numeric_rule", "uncapped_ailment_stack_xml", "ailment_stacks", "uncapped_ailment_stats"):
        wrap(cr, attr)
    n, total = 3, 0.0
    try:
        for _ in range(n):
            t = time.perf_counter()
            self.judging.lanes.read()
            total += time.perf_counter() - t
    finally:
        for owner, attr, fn in undo:
            setattr(owner, attr, fn)
    return total / n, {k: v / n for k, v in parts.items()}, {k: v / n for k, v in calls.items()}


def _read_cost(self):
    """Unit 2: `lanes.read()` + the compare of its planned lane inputs against those of the last rejudge."""
    skeleton = st["skeleton"]
    self.judging.rejudge(skeleton)  # the reference: the state right after a rejudge
    ref = _planned(self, skeleton, self.judging.lanes.read())
    times, same = [], 0
    for _ in range(CALLS):
        t = time.perf_counter()
        lanes = self.judging.lanes.read()
        same += _planned(self, skeleton, lanes) == ref
        times.append(time.perf_counter() - t)
    res["read_times"], res["read_same"] = times, same
    if sum(times) / len(times) > 0.65 or os.environ.get("JUNKROAN_DIAG_PARTS"):
        res["parts"] = _profile_parts(self)


_orig_run = pl.BuildPipeline.run


def _run(self, skeleton, *a, **kw):
    st["skeleton"] = skeleton
    return _orig_run(self, skeleton, *a, **kw)


pl.BuildPipeline.run = _run
Judging.rejudge = _rejudge
pl.TreeOptimizer.allocate = _allocate
pl.BuildPipeline._record = _record

try:
    row = benchmark.run_one(SLUG, log_path=LOG, seed=SEED, gear_mode=GEAR, construction="classic", loop_seconds=60.0)
except Stop:
    row = {}

if "times" not in res:
    sys.exit("the pipeline ended before the `tree greedy` record: " + str(row.get("trace") or row.get("error")))
mean = sum(res["times"]) / len(res["times"])
print(f"previous record: {res['before_name']}; nodes removed by tree greedy: {res['nodes_removed']}; "
      f"rejudge calls during tree greedy: {res.get('greedy_rejudges')}; tree greedy record {human_duration(res['record_seconds'])}")
rmean = sum(res["read_times"]) / CALLS
print(f"read+compare mean {rmean:.2f} s over {CALLS} (compare equal to the last rejudge's inputs: {res['read_same']}/{CALLS})")
print(f"nodes {res['nodes']}")
print(f"product {rmean * res['nodes'] / 60:.1f} min")
print(f"bar 1 min (0.65 s/node): {'UNDER' if rmean <= 0.65 else 'ABOVE'}")
if "parts" in res:
    total, parts, calls = res["parts"]
    print(f"where the time goes in read_lanes (mean of 3 calls, {total:.2f} s total; inclusive, parts nest):")
    for k, v in sorted(parts.items(), key=lambda kv: -kv[1]):
        print(f"  {k}: {v:.2f} s ({calls.get(k, 0):g} calls)")
    print(f"load_xml calls per read_lanes {calls.get('load_xml', 0):g}, load_xml {parts.get('load_xml', 0.0):.2f} s, total per read_lanes {total:.2f} s")
print(f"rejudge mean {mean:.2f} s over {CALLS}, nodes {res['nodes']}, added {human_duration(mean * res['nodes'])}")
